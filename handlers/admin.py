"""
Команды для старосты / администраторов чата.
Поддержка штрафов и списания очков по юзернейму (@username) прямо в ЛС с ботом.
"""

from typing import Optional
from aiogram import Router, types, Bot, F
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import config
from database import db
from handlers.moderation import apply_mute

router = Router()


async def is_admin(message: types.Message, bot: Bot = None) -> bool:
    """Проверка прав: команды доступны ТОЛЬКО владельцу бота (ID 5325601154)."""
    if not message.from_user:
        return False

    user_id = message.from_user.id
    return user_id == config.report_user_id or user_id in config.admin_ids


async def apply_penalty_by_username_or_id(
    message: types.Message,
    bot: Bot,
    username_or_id: str,
    amount: int = 1,
    reason: str = "штраф от администратора",
):
    """Списание очков с пользователя по @username или ID."""
    clean_target = username_or_id.strip()
    target_data = await db.get_user_by_username(clean_target)

    if not target_data:
        await message.reply(
            f"❌ Участник <b>{clean_target}</b> не найден в базе данных бота.\n"
            "<i>Убедитесь, что он писал хотя бы одно сообщение в чате, или проверьте правильность написания юзернейма.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    chat_id = target_data["chat_id"]
    target_user_id = target_data["user_id"]
    target_name = target_data["first_name"] or target_data["username"] or f"ID {target_user_id}"
    target_username = f"@{target_data['username']}" if target_data["username"] else target_name

    # Списываем очки
    new_points = await db.deduct_points(chat_id, target_user_id, amount=amount)
    await db.record_violation(chat_id, target_user_id, "admin_warn", reason, amount)

    # Проверка на обнуление очков (мут на 3 часа)
    mute_note = ""
    if new_points <= 0:
        await apply_mute(bot, chat_id, target_user_id, config.zero_points_mute_hours)
        await db.reset_points(chat_id, target_user_id)
        mute_note = (
            f"\n🚨 <b>Баланс достиг 0! Участник отправлен в мут на {config.zero_points_mute_hours} часа.</b> "
            f"(Очки восстановлены до {config.initial_points})"
        )

    # Ответ администратору
    await message.reply(
        f"📉 <b>Списано -{amount} очко с {target_username}!</b>\n\n"
        f"👤 Участник: <b>{target_name}</b> (ID: <code>{target_user_id}</code>)\n"
        f"📊 Текущий баланс: <b>{new_points}/{config.initial_points} очков</b>\n"
        f"📝 Причина: <i>{reason}</i>{mute_note}",
        parse_mode=ParseMode.HTML,
    )

    # Отправка уведомления в группу, если штраф выдан из ЛС
    if message.chat.type == "private" and chat_id:
        try:
            if mute_note:
                await bot.send_message(
                    chat_id,
                    f"🚨 <b>Участник {target_username} исчерпал все очки по решению администратора и отправлен в мут на {config.zero_points_mute_hours} часа!</b>\n"
                    f"Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await bot.send_message(
                    chat_id,
                    f"⚠️ <b>Администратор оштрафовал {target_username} на -{amount} очко!</b>\n"
                    f"Причина: <i>{reason}</i>\n"
                    f"📊 Осталось очков: <b>{new_points}/{config.initial_points}</b>.",
                    parse_mode=ParseMode.HTML,
                )
        except Exception:
            pass


@router.message(Command("warn", "штраф", "minus", "минус"))
async def cmd_warn(message: types.Message, bot: Bot):
    """
    Команда списания очка:
    1. Через ответ на сообщение в группе: /warn
    2. По юзернейму: /warn @username
    3. С указанием количества и причины: /warn @username 2 спам
    """
    if not await is_admin(message, bot):
        await message.reply("❌ Эта команда доступна только администраторам.")
        return

    text = message.text or ""
    parts = text.split(maxsplit=3)

    # Вариант 1: ответ на сообщение
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        amount = 1
        reason = "штраф от администратора"
        if len(parts) > 1 and parts[1].lstrip("-").isdigit():
            amount = abs(int(parts[1]))
            if len(parts) > 2:
                reason = parts[2]
        elif len(parts) > 1:
            reason = " ".join(parts[1:])

        await apply_penalty_by_username_or_id(
            message=message,
            bot=bot,
            username_or_id=str(target_user.id),
            amount=amount,
            reason=reason,
        )
        return

    # Вариант 2: указан юзернейм в аргументах
    if len(parts) > 1:
        target_user_str = parts[1]
        amount = 1
        reason = "штраф от администратора"
        if len(parts) > 2 and parts[2].lstrip("-").isdigit():
            amount = abs(int(parts[2]))
            if len(parts) > 3:
                reason = parts[3]
        elif len(parts) > 2:
            reason = parts[2]

        await apply_penalty_by_username_or_id(
            message=message,
            bot=bot,
            username_or_id=target_user_str,
            amount=amount,
            reason=reason,
        )
        return

    await message.reply(
        "ℹ️ <b>Как снять очко:</b>\n"
        "• <code>/warn @username</code> — снять 1 очко с участника\n"
        "• <code>/warn @username 2 спам</code> — снять 2 очка с причиной\n"
        "• Или ответьте командой <code>/warn</code> на сообщение нарушителя в чате\n"
        "• В личке с ботом можно просто написать: <code>@username -1</code>",
        parse_mode=ParseMode.HTML,
    )


@router.message(F.chat.type == "private", F.text.startswith("@"))
async def handle_direct_username_penalty(message: types.Message, bot: Bot):
    """
    Быстрое списание очка в ЛС при отправке:
    @username
    @username -1
    @username 2 причина
    """
    if not await is_admin(message, bot):
        return

    text = message.text.strip()
    parts = text.split(maxsplit=2)
    target_username = parts[0]

    # Проверяем, это пополнение (+N) или списание (-N)
    if len(parts) > 1 and parts[1].startswith("+") and parts[1].lstrip("+").isdigit():
        # Пополнение очков
        amount = int(parts[1].lstrip("+"))
        target_data = await db.get_user_by_username(target_username)
        if not target_data:
            await message.reply(f"❌ Участник <b>{target_username}</b> не найден в базе.", parse_mode=ParseMode.HTML)
            return

        chat_id = target_data["chat_id"]
        target_user_id = target_data["user_id"]
        target_name = target_data["first_name"] or target_username
        new_points = await db.add_points(chat_id, target_user_id, amount)

        await message.reply(
            f"✅ <b>Пополнение баланса!</b>\n"
            f"👤 Участник: <b>{target_name}</b> ({target_username})\n"
            f"📈 Начислено: <b>+{amount} очков</b>\n"
            f"📊 Новый баланс: <b>{new_points}/{config.initial_points} очков</b>",
            parse_mode=ParseMode.HTML,
        )

        if chat_id:
            try:
                await bot.send_message(
                    chat_id,
                    f"🎉 <b>Администратор пополнил баланс участника {target_username} на +{amount} очк.!</b>\n"
                    f"📊 Текущий баланс: <b>{new_points}/{config.initial_points}</b>.",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        return

    amount = 1
    reason = "штраф от администратора"

    if len(parts) > 1 and parts[1].lstrip("-+").isdigit():
        amount = abs(int(parts[1]))
        if len(parts) > 2:
            reason = parts[2]
    elif len(parts) > 1:
        reason = " ".join(parts[1:])

    await apply_penalty_by_username_or_id(
        message=message,
        bot=bot,
        username_or_id=target_username,
        amount=amount,
        reason=reason,
    )


@router.message(Command("unmute", "размут"))
async def cmd_unmute(message: types.Message, bot: Bot):
    """Снять мут с пользователя."""
    if not await is_admin(message, bot):
        await message.reply("❌ Эта команда доступна только администраторам чата.")
        return

    target_chat_id = message.chat.id
    target_user_id = None
    target_name = "Участник"

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = target_user.first_name
    else:
        args = message.text.split()
        if len(args) > 1:
            query = args[1]
            user_data = await db.get_user_by_username(query)
            if user_data:
                target_chat_id = user_data["chat_id"]
                target_user_id = user_data["user_id"]
                target_name = user_data["first_name"] or query

    if not target_user_id:
        await message.reply(
            "ℹ️ Ответьте на сообщение или укажите юзернейм: <code>/unmute @username</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # 1. Снимаем виртуальный мут в БД
    await db.remove_user_mute(target_chat_id, target_user_id)

    # 2. Снимаем ограничения в Telegram API, если применимо
    try:
        permissions = types.ChatPermissions(
            can_send_messages=True,
            can_send_audios=True,
            can_send_documents=True,
            can_send_photos=True,
            can_send_videos=True,
            can_send_video_notes=True,
            can_send_voice_notes=True,
            can_send_polls=True,
            can_send_other_messages=True,
            can_add_web_page_previews=True,
        )
        await bot.restrict_chat_member(
            chat_id=target_chat_id,
            user_id=target_user_id,
            permissions=permissions,
        )
    except Exception:
        pass

    await message.reply(
        f"✅ Мут с участника <b>{target_name}</b> успешно снят!",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("addpoints", "дать_очки", "plus", "плюс", "пополнить", "пополнение", "give"))
async def cmd_addpoints(message: types.Message, bot: Bot):
    """Пополнить очки участнику (доступно ТОЛЬКО владельцу бота)."""
    if not await is_admin(message, bot):
        await message.reply("⛔ Команда пополнения очков доступна только создателю бота.")
        return

    parts = message.text.split()
    target_chat_id = message.chat.id
    target_user_id = None
    target_name = "Участник"
    target_username = ""
    amount = 1

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = target_user.first_name
        target_username = f" (@{target_user.username})" if target_user.username else ""
        if len(parts) > 1 and parts[1].lstrip("-+").isdigit():
            amount = int(parts[1].lstrip("+"))
    elif len(parts) > 1:
        query = parts[1]
        user_data = await db.get_user_by_username(query)
        if user_data:
            target_chat_id = user_data["chat_id"]
            target_user_id = user_data["user_id"]
            target_name = user_data["first_name"] or query
            target_username = f" (@{user_data['username']})" if user_data["username"] else ""
        if len(parts) > 2 and parts[2].lstrip("-+").isdigit():
            amount = int(parts[2].lstrip("+"))

    if not target_user_id:
        await message.reply(
            "ℹ️ <b>Как пополнить очки участнику:</b>\n"
            "• <code>/plus @username 2</code> — начислить 2 очка\n"
            "• <code>/пополнить @username</code> — начислить 1 очко\n"
            "• Или ответьте на сообщение участника: <code>/plus 1</code>\n"
            "• В личке с ботом можно написать: <code>@username +1</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    new_points = await db.add_points(target_chat_id, target_user_id, amount)
    await message.reply(
        f"✅ <b>Баланс пополнен!</b>\n"
        f"👤 Участник: <b>{target_name}</b>{target_username}\n"
        f"📈 Начислено: <b>+{amount} очков</b>\n"
        f"📊 Текущий баланс: <b>{new_points}/{config.initial_points} очков</b>.",
        parse_mode=ParseMode.HTML,
    )

    if target_chat_id and message.chat.type == "private":
        try:
            await bot.send_message(
                target_chat_id,
                f"🎉 <b>Администратор пополнил баланс участника {target_name}{target_username} на +{amount} очк.!</b>\n"
                f"📊 Текущий баланс: <b>{new_points}/{config.initial_points}</b>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


@router.message(Command("resetpoints", "сброс_очков"))
async def cmd_resetpoints(message: types.Message, bot: Bot):
    """Сбросить очки участника до начальных 10."""
    if not await is_admin(message, bot):
        await message.reply("❌ Доступно только администраторам.")
        return

    parts = message.text.split()
    target_chat_id = message.chat.id
    target_user_id = None
    target_name = "Участник"

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
        target_user_id = target_user.id
        target_name = target_user.first_name
    elif len(parts) > 1:
        query = parts[1]
        user_data = await db.get_user_by_username(query)
        if user_data:
            target_chat_id = user_data["chat_id"]
            target_user_id = user_data["user_id"]
            target_name = user_data["first_name"] or query

    if not target_user_id:
        await message.reply(
            "ℹ️ Ответьте на сообщение или напишите: <code>/resetpoints @username</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    new_points = await db.reset_points(target_chat_id, target_user_id)
    await message.reply(
        f"🔄 Очки участника <b>{target_name}</b> сброшены до стандартных <b>{new_points}</b>.",
        parse_mode=ParseMode.HTML,
    )

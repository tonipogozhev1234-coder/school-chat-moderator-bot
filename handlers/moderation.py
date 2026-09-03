"""
Обработчик модерации всех входящих сообщений:
- Проверка активного мута (включая админов — удаление всех сообщений)
- Проверка на спам (-1 очко)
- Проверка на мат (-1 очко)
- Проверка на оскорбления (мут на 2 часа)
- Контроль нулевого баланса очков (мут на 24 часа)
"""

from datetime import datetime, timedelta, timezone
from typing import Tuple
from aiogram import Router, types, Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from config import config
from database import db
from filters.text_filter import check_text_violation, ViolationType
from filters.spam_detector import spam_detector

router = Router()


async def apply_mute(
    bot: Bot,
    chat_id: int,
    user_id: int,
    duration_hours: int,
) -> Tuple[bool, bool]:
    """
    Накладывает мут на пользователя:
    1. Записывает время окончания в базу данных (виртуальный мут — работает даже если участник админ!)
    2. Пытается применить системный мут в Telegram через restrictChatMember.
    Возвращает: (is_telegram_restricted: bool, is_virtual_only: bool)
    """
    # 1. Всегда включаем виртуальный мут в БД (автоудаление любых сообщений нарушителя)
    await db.set_user_mute(chat_id, user_id, duration_hours)

    # 2. Пытаемся замутить через Telegram API
    until_date = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
    try:
        permissions = types.ChatPermissions(
            can_send_messages=False,
            can_send_audios=False,
            can_send_documents=False,
            can_send_photos=False,
            can_send_videos=False,
            can_send_video_notes=False,
            can_send_voice_notes=False,
            can_send_polls=False,
            can_send_other_messages=False,
            can_add_web_page_previews=False,
        )
        await bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=user_id,
            permissions=permissions,
            until_date=until_date,
        )
        return True, False
    except TelegramAPIError:
        # Участник является администратором чата — Telegram API не позволяет напрямую ограничить админа.
        # В этом случае работает наш виртуальный мут (бот просто сразу удаляет любые его новые сообщения)!
        return False, True


@router.message()
async def process_chat_message(message: types.Message, bot: Bot):
    """Главный фильтр сообщений чата."""
    is_private = (message.chat.type == "private")

    # Игнорируем других ботов и служебные сообщения
    if not message.from_user or message.from_user.is_bot:
        return

    user = message.from_user
    chat_id = message.chat.id
    user_id = user.id
    user_name = user.first_name or user.username or f"ID_{user_id}"

    # 0. ПРОВЕРКА АКТИВНОГО МУТА (РАБОТАЕТ ДЛЯ ВСЕХ, ВКЛЮЧАЯ АДМИНОВ В ГРУППАХ!)
    if not is_private:
        is_muted, remaining_sec = await db.is_user_muted(chat_id, user_id)
        if is_muted:
            try:
                await message.delete()
            except Exception:
                pass
            return

    # Игнорируем команды (они обрабатываются в роутерах команд)
    text = message.text or message.caption or ""
    if text.startswith("/"):
        return

    # Регистрируем/обновляем пользователя в базе данных
    await db.get_or_create_user(
        chat_id=chat_id,
        user_id=user_id,
        username=user.username,
        first_name=user.first_name,
    )

    # 1. ПРОВЕРКА НА ОСКОРБЛЕНИЯ (Высший приоритет -> Мут на 2 часа)
    violation, matched = check_text_violation(text)
    if violation == ViolationType.INSULT:
        await db.record_violation(
            chat_id=chat_id,
            user_id=user_id,
            violation_type="insult",
            details=matched or "",
            points_deducted=0,
        )

        if is_private:
            await message.reply(
                f"🤐 <b>{user_name}</b>, за это оскорбление в группе вы бы получили <b>МУТ НА {config.insult_mute_hours} ЧАСА</b>!\n"
                "💡 <i>Ведите себя вежливо и уважайте одноклассников.</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        # В группе: удаляем и накладываем мут
        if config.delete_violating_messages:
            try:
                await message.delete()
            except Exception:
                pass

        is_tg, is_virt = await apply_mute(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            duration_hours=config.insult_mute_hours,
        )

        admin_note = (
            "\n<i>(Поскольку у вас статус админа чата, бот включил режим автоудаления всех ваших сообщений на 2 часа)</i>"
            if is_virt
            else ""
        )
        await message.answer(
            f"🤐 <b>{user_name}</b> отправлен в мут на <b>{config.insult_mute_hours} часа</b> за оскорбление!{admin_note}\n"
            "💡 <i>Ведите себя вежливо и уважайте одноклассников.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # 2. ПРОВЕРКА НА СПАМ И ФЛУД (-1 очко)
    is_spam, spam_reason = spam_detector.is_spam(chat_id, user_id, text)
    if is_spam:
        new_points = await db.deduct_points(chat_id, user_id, config.spam_penalty)
        await db.record_violation(
            chat_id=chat_id,
            user_id=user_id,
            violation_type="spam",
            details=spam_reason,
            points_deducted=config.spam_penalty,
        )

        if is_private:
            if new_points <= 0:
                await db.reset_points(chat_id, user_id)
                await message.reply(
                    f"🚨 <b>{user_name}</b>, вы исчерпали все очки (0/{config.initial_points}) за спам!\n"
                    f"В группе вы бы отправились в мут на <b>{config.zero_points_mute_hours} часа</b>. Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.reply(
                    f"⚠️ <b>{user_name}</b>, спам запрещён ({spam_reason})!\n"
                    f"Штраф: <b>-{config.spam_penalty} очко</b>. Осталось очков: <b>{new_points}/{config.initial_points}</b>.",
                    parse_mode=ParseMode.HTML,
                )
            return

        if config.delete_violating_messages:
            try:
                await message.delete()
            except Exception:
                pass

        if new_points <= 0:
            # Очки исчерпаны -> Мут на 3 часа
            is_tg, is_virt = await apply_mute(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                duration_hours=config.zero_points_mute_hours,
            )
            await db.reset_points(chat_id, user_id)
            spam_detector.reset_user(chat_id, user_id)

            zero_word = "часа" if config.zero_points_mute_hours in (2, 3, 4) else "часов"
            admin_note = (
                f"\n<i>(Для участников с правами админа активен режим автоудаления сообщений на {config.zero_points_mute_hours} {zero_word})</i>"
                if is_virt
                else ""
            )
            await message.answer(
                f"🚨 <b>{user_name}</b> исчерпал все очки (0/{config.initial_points}) и отправлен в мут на <b>{config.zero_points_mute_hours} {zero_word}</b> за постоянный спам ({spam_reason})!{admin_note}\n"
                f"Очки восстановлены до {config.initial_points}.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                f"⚠️ <b>{user_name}</b>, спам запрещён ({spam_reason})!\n"
                f"Штраф: <b>-{config.spam_penalty} очко</b>. Осталось очков: <b>{new_points}/{config.initial_points}</b>.",
                parse_mode=ParseMode.HTML,
            )
        return

    # 3. ПРОВЕРКА НА МАТ (-1 очко)
    if violation == ViolationType.MAT:
        new_points = await db.deduct_points(chat_id, user_id, config.mat_penalty)
        await db.record_violation(
            chat_id=chat_id,
            user_id=user_id,
            violation_type="mat",
            details=matched or "",
            points_deducted=config.mat_penalty,
        )

        if is_private:
            if new_points <= 0:
                await db.reset_points(chat_id, user_id)
                await message.reply(
                    f"🚨 <b>{user_name}</b>, вы исчерпали все очки (0/{config.initial_points})!\n"
                    f"В группе вы бы отправились в мут на <b>{config.zero_points_mute_hours} часа</b>. Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.reply(
                    f"⚠️ <b>{user_name}</b>, за мат штраф <b>-{config.mat_penalty} очко</b>!\n"
                    f"Осталось очков: <b>{new_points}/{config.initial_points}</b>.\n"
                    "💡 <i>(В личке мут не применяется. Добавьте бота в группу класса и дайте права Администратора)</i>",
                    parse_mode=ParseMode.HTML,
                )
            return

        if config.delete_violating_messages:
            try:
                await message.delete()
            except Exception:
                pass

        if new_points <= 0:
            # Очки исчерпаны -> Мут на 3 часа
            is_tg, is_virt = await apply_mute(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                duration_hours=config.zero_points_mute_hours,
            )
            await db.reset_points(chat_id, user_id)

            zero_word = "часа" if config.zero_points_mute_hours in (2, 3, 4) else "часов"
            admin_note = (
                f"\n<i>(Для участников с правами админа активен режим автоудаления сообщений на {config.zero_points_mute_hours} {zero_word})</i>"
                if is_virt
                else ""
            )
            await message.answer(
                f"🚨 <b>{user_name}</b> исчерпал все очки (0/{config.initial_points}) и отправлен в мут на <b>{config.zero_points_mute_hours} {zero_word}</b> за нецензурную брань!{admin_note}\n"
                f"Очки восстановлены до {config.initial_points}.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                f"⚠️ <b>{user_name}</b>, не выражайся! В чате действует цензура.\n"
                f"Штраф: <b>-{config.mat_penalty} очко</b>. Осталось очков: <b>{new_points}/{config.initial_points}</b>.",
                parse_mode=ParseMode.HTML,
            )
        return

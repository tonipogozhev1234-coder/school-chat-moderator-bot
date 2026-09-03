"""
Команды для старосты / администраторов чата.
"""

from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import config
from database import db

router = Router()


async def is_admin(message: types.Message, bot: Bot) -> bool:
    """Проверка, является ли автор сообщения админом группы или бота."""
    if not message.from_user:
        return False

    user_id = message.from_user.id
    if user_id in config.admin_ids:
        return True

    if message.chat.type in ("group", "supergroup"):
        member = await bot.get_chat_member(message.chat.id, user_id)
        if member.status in ("administrator", "creator"):
            return True

    return False


@router.message(Command("unmute", "размут"))
async def cmd_unmute(message: types.Message, bot: Bot):
    """Снять мут с пользователя."""
    if not await is_admin(message, bot):
        await message.reply("❌ Эта команда доступна только администраторам чата.")
        return

    target_user = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target_user = message.reply_to_message.from_user
    else:
        # Проверяем аргументы команды
        args = message.text.split()
        if len(args) > 1 and args[1].isdigit():
            user_id = int(args[1])
            try:
                chat_member = await bot.get_chat_member(message.chat.id, user_id)
                target_user = chat_member.user
            except Exception:
                pass

    if not target_user:
        await message.reply(
            "ℹ️ Ответьте этой командой на сообщение пользователя или укажите ID: <code>/unmute 123456789</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # 1. Снимаем виртуальный мут в БД
    await db.remove_user_mute(message.chat.id, target_user.id)

    # 2. Снимаем ограничения в Telegram API, если они были установлены
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
            chat_id=message.chat.id,
            user_id=target_user.id,
            permissions=permissions,
        )
    except Exception:
        pass  # Если участник админ в Telegram, ошибка допустима, виртуальный мут уже снят

    await message.reply(
        f"✅ Мут с участника <b>{target_user.first_name}</b> успешно снят!",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("addpoints", "дать_очки"))
async def cmd_addpoints(message: types.Message, bot: Bot):
    """Добавить очки участнику."""
    if not await is_admin(message, bot):
        await message.reply("❌ Доступно только администраторам.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("ℹ️ Ответьте на сообщение участника: <code>/addpoints 3</code>", parse_mode=ParseMode.HTML)
        return

    args = message.text.split()
    amount = 1
    if len(args) > 1 and args[1].lstrip("-").isdigit():
        amount = int(args[1])

    target_user = message.reply_to_message.from_user
    new_points = await db.add_points(message.chat.id, target_user.id, amount)

    await message.reply(
        f"✅ Участнику <b>{target_user.first_name}</b> начислено <b>{amount}</b> очков.\n"
        f"Текущий баланс: <b>{new_points}</b>.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("resetpoints", "сброс_очков"))
async def cmd_resetpoints(message: types.Message, bot: Bot):
    """Сбросить очки участника до 10."""
    if not await is_admin(message, bot):
        await message.reply("❌ Доступно только администраторам.")
        return

    if not message.reply_to_message or not message.reply_to_message.from_user:
        await message.reply("ℹ️ Ответьте на сообщение участника командой <code>/resetpoints</code>", parse_mode=ParseMode.HTML)
        return

    target_user = message.reply_to_message.from_user
    new_points = await db.reset_points(message.chat.id, target_user.id)

    await message.reply(
        f"🔄 Очки участника <b>{target_user.first_name}</b> сброшены до стандартных <b>{new_points}</b>.",
        parse_mode=ParseMode.HTML,
    )

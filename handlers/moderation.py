"""
Обработчик модерации всех входящих сообщений:
- Проверка на спам (-1 очко)
- Проверка на мат (-1 очко)
- Проверка на оскорбления (мут на 2 часа)
- Контроль нулевого баланса очков (мут на 24 часа)
"""

from datetime import datetime, timedelta, timezone
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
) -> bool:
    """Ограничение прав пользователя на отправку сообщений (мут)."""
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
        await db.record_mute(chat_id, user_id)
        return True
    except TelegramAPIError as e:
        print(f"[ERROR] Не удалось ограничить пользователя {user_id} в чате {chat_id}: {e}")
        return False


@router.message()
async def process_chat_message(message: types.Message, bot: Bot):
    """Главный фильтр сообщений чата."""
    # Работаем только в группах и супергруппах
    if message.chat.type not in ("group", "supergroup"):
        return

    # Игнорируем других ботов и служебные сообщения
    if not message.from_user or message.from_user.is_bot:
        return

    # Игнорируем команды (они обрабатываются в других роутерах)
    text = message.text or message.caption or ""
    if text.startswith("/"):
        return

    user = message.from_user
    chat_id = message.chat.id
    user_id = user.id
    user_name = user.first_name or user.username or f"ID_{user_id}"

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

        # Удаляем оскорбительное сообщение
        if config.delete_violating_messages:
            try:
                await message.delete()
            except Exception:
                pass

        # Накладываем мут на 2 часа
        success = await apply_mute(
            bot=bot,
            chat_id=chat_id,
            user_id=user_id,
            duration_hours=config.insult_mute_hours,
        )

        if success:
            await message.answer(
                f"🤐 <b>{user_name}</b> отправлен в мут на <b>{config.insult_mute_hours} часа</b> за оскорбление!\n"
                "💡 <i>Ведите себя вежливо и уважайте одноклассников.</i>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                f"⚠️ <b>{user_name}</b> нарушил правила (оскорбление), но бот не смог выдать мут.\n"
                "<i>Выдайте боту права Администратора с возможностью блокировать пользователей!</i>",
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

        if config.delete_violating_messages:
            try:
                await message.delete()
            except Exception:
                pass

        if new_points <= 0:
            # Очки исчерпаны -> Мут на 24 часа
            success = await apply_mute(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                duration_hours=config.zero_points_mute_hours,
            )
            await db.reset_points(chat_id, user_id)
            spam_detector.reset_user(chat_id, user_id)

            if success:
                await message.answer(
                    f"🚨 <b>{user_name}</b> исчерпал все очки (0/{config.initial_points}) и отправлен в мут на <b>{config.zero_points_mute_hours} часов</b> за постоянный спам ({spam_reason})!\n"
                    f"Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.answer(
                    f"🚨 У <b>{user_name}</b> закончились очки (0/{config.initial_points}), но бот не смог выдать мут. Проверьте права администратора!",
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

        if config.delete_violating_messages:
            try:
                await message.delete()
            except Exception:
                pass

        if new_points <= 0:
            # Очки исчерпаны -> Мут на 24 часа
            success = await apply_mute(
                bot=bot,
                chat_id=chat_id,
                user_id=user_id,
                duration_hours=config.zero_points_mute_hours,
            )
            await db.reset_points(chat_id, user_id)

            if success:
                await message.answer(
                    f"🚨 <b>{user_name}</b> исчерпал все очки (0/{config.initial_points}) и отправлен в мут на <b>{config.zero_points_mute_hours} часов</b> за нецензурную брань!\n"
                    f"Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.answer(
                    f"🚨 У <b>{user_name}</b> закончились очки (0/{config.initial_points}), но бот не смог выдать мут. Проверьте права администратора!",
                    parse_mode=ParseMode.HTML,
                )
        else:
            await message.answer(
                f"⚠️ <b>{user_name}</b>, не выражайся! В чате действует цензура.\n"
                f"Штраф: <b>-{config.mat_penalty} очко</b>. Осталось очков: <b>{new_points}/{config.initial_points}</b>.",
                parse_mode=ParseMode.HTML,
            )
        return

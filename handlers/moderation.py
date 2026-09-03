"""
Обработчик модерации всех входящих сообщений:
- Проверка активного мута (включая админов — удаление всех сообщений)
- Проверка на спам (-1 очко)
- Проверка на мат (-1 очко)
- Проверка на оскорбления (мут на 2 часа)
- Контроль нулевого баланса очков (мут на 24 часа)
"""

import html
from datetime import datetime, timedelta, timezone
from typing import Tuple
from aiogram import Router, types, Bot
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile
from aiogram.exceptions import TelegramAPIError

from config import config
from database import db
from filters.text_filter import check_text_violation, ViolationType
from filters.spam_detector import spam_detector
from utils.screenshot import create_message_screenshot

router = Router()


async def send_violation_report(
    bot: Bot,
    message: types.Message,
    violation_type: str,
    matched_word: str,
    points_left: int,
):
    """
    Отправляет скриншот и отчет о нарушении всем администраторам (владельцу и доверенным админам).
    """
    target_admin_ids = set()
    if config.report_user_id:
        target_admin_ids.add(config.report_user_id)
    for aid in config.admin_ids:
        if aid:
            target_admin_ids.add(aid)

    if not target_admin_ids:
        return

    try:
        chat_title = message.chat.title or "Личный диалог"
        user = message.from_user
        user_name = user.first_name if user else "Аноним"
        username_str = f" (@{user.username})" if user and user.username else ""
        user_id = user.id if user else 0
        text = message.text or message.caption or "(без текста)"

        # 1. Генерируем графический скриншот-карточку
        caption = (
            f"📸 <b>Фиксация нарушения правил чата!</b>\n\n"
            f"🏫 <b>Чат:</b> {html.escape(chat_title)}\n"
            f"👤 <b>Нарушитель:</b> {html.escape(user_name)}{username_str} (ID: <code>{user_id}</code>)\n"
            f"⚠️ <b>Тип:</b> {violation_type.upper()}\n"
            f"🔍 <b>Зафиксировано:</b> <code>{html.escape(matched_word)}</code>\n"
            f"📊 <b>Осталось очков:</b> <code>{points_left}</code>\n\n"
            f"💬 <b>Текст:</b>\n"
            f"<blockquote>{html.escape(text)}</blockquote>"
        )

        img_buf = create_message_screenshot(
            chat_title=chat_title,
            user_name=user_name,
            user_id=user_id,
            text=text,
            matched_word=matched_word,
            violation_type=violation_type,
            points_left=points_left,
        )
        photo_bytes = img_buf.read() if img_buf else None

        # 2. Рассылаем каждому администратору
        for admin_id in target_admin_ids:
            try:
                await bot.forward_message(
                    chat_id=admin_id,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                )
            except Exception:
                pass

            try:
                if photo_bytes:
                    photo = BufferedInputFile(photo_bytes, filename="violation_screenshot.png")
                    await bot.send_photo(
                        chat_id=admin_id,
                        photo=photo,
                        caption=caption,
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=caption,
                        parse_mode=ParseMode.HTML,
                    )
            except Exception as e:
                print(f"[ERROR] Не удалось отправить скриншот администратору {admin_id}: {e}")
    except Exception as e:
        print(f"[ERROR] Ошибка генерации отчета о нарушении: {e}")



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
        await db.reset_clean_messages(chat_id, user_id)

        if is_private:
            await message.reply(
                f"🤐 <b>{user_name}</b>, за это оскорбление в группе вы бы получили <b>МУТ НА {config.insult_mute_hours} ЧАСА</b>!\n"
                "💡 <i>Ведите себя вежливо и уважайте одноклассников.</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Отправляем скриншот и отчет администратору (5325601154) до удаления сообщения
        await send_violation_report(bot, message, "оскорбление", matched or "", 0)

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
        await db.reset_clean_messages(chat_id, user_id)

        if is_private:
            if new_points <= 0:
                await db.reset_points(chat_id, user_id)
                await message.reply(
                    f"🚨 <b>{user_name}</b>, вы исчерпали все очки (0) за спам!\n"
                    f"В группе вы бы отправились в мут на <b>{config.zero_points_mute_hours} часа</b>. Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.reply(
                    f"⚠️ <b>{user_name}</b>, спам запрещён ({spam_reason})!\n"
                    f"Штраф: <b>-{config.spam_penalty} очко</b>. Осталось очков: <b>{new_points}</b>.",
                    parse_mode=ParseMode.HTML,
                )
            return

        # Отправляем скриншот и отчет администраторам до удаления сообщения
        await send_violation_report(bot, message, "спам", spam_reason, new_points)

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
                f"🚨 <b>{user_name}</b> исчерпал все очки (0) и отправлен в мут на <b>{config.zero_points_mute_hours} {zero_word}</b> за постоянный спам ({spam_reason})!{admin_note}\n"
                f"Очки восстановлены до {config.initial_points}.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                f"⚠️ <b>{user_name}</b>, спам запрещён ({spam_reason})!\n"
                f"Штраф: <b>-{config.spam_penalty} очко</b>. Осталось очков: <b>{new_points}</b>.",
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
        await db.reset_clean_messages(chat_id, user_id)

        if is_private:
            if new_points <= 0:
                await db.reset_points(chat_id, user_id)
                await message.reply(
                    f"🚨 <b>{user_name}</b>, вы исчерпали все очки (0)!\n"
                    f"В группе вы бы отправились в мут на <b>{config.zero_points_mute_hours} часа</b>. Очки восстановлены до {config.initial_points}.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.reply(
                    f"⚠️ <b>{user_name}</b>, за мат штраф <b>-{config.mat_penalty} очко</b>!\n"
                    f"Осталось очков: <b>{new_points}</b>.\n"
                    "💡 <i>(В личке мут не применяется. Добавьте бота в группу класса и дайте права Администратора)</i>",
                    parse_mode=ParseMode.HTML,
                )
            return

        # Отправляем скриншот и отчет администраторам до удаления сообщения
        await send_violation_report(bot, message, "мат", matched or "", new_points)

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
                f"🚨 <b>{user_name}</b> исчерпал все очки (0) и отправлен в мут на <b>{config.zero_points_mute_hours} {zero_word}</b> за нецензурную брань!{admin_note}\n"
                f"Очки восстановлены до {config.initial_points}.",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.answer(
                f"⚠️ <b>{user_name}</b>, не выражайся! В чате действует цензура.\n"
                f"Штраф: <b>-{config.mat_penalty} очко</b>. Осталось очков: <b>{new_points}</b>.",
                parse_mode=ParseMode.HTML,
            )
        return

    # 4. ЧИСТОЕ СООБЩЕНИЕ БЕЗ МАТА (НАЧИСЛЕНИЕ +1 БАЛЛА ЗА КАЖДЫЕ 25 СООБЩЕНИЙ)
    if not is_private:
        is_rewarded, new_points, clean_count = await db.record_clean_message(
            chat_id=chat_id,
            user_id=user_id,
            reward_step=config.clean_messages_reward_step,
            reward_points=config.clean_messages_reward_points,
        )
        if is_rewarded:
            await message.reply(
                f"🎉 <b>{user_name}</b>, за <b>{config.clean_messages_reward_step} вежливых сообщений без мата подряд</b> "
                f"вам начислен <b>+{config.clean_messages_reward_points} балл</b>!\n"
                f"📊 Текущий баланс: <b>{new_points} очков</b>. Так держать!",
                parse_mode=ParseMode.HTML,
            )

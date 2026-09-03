"""
Команды для обычных участников чата: просмотр правил, баланса очков и топа.
"""

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import config
from database import db

router = Router()


@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Приветственное сообщение."""
    if message.chat.type == "private":
        await message.answer(
            "👋 <b>Привет! Я бот-модератор для классного чата без учителя.</b>\n\n"
            "Добавь меня в группу класса и выдай права <b>Администратора</b> "
            "(с возможностью блокировать пользователей и удалять сообщения).\n\n"
            "📜 <b>Правила чата:</b>\n"
            f"• Каждому даётся <b>{config.initial_points} очков</b>.\n"
            f"• За мат: <b>-{config.mat_penalty} очко</b>.\n"
            f"• За спам и флуд: <b>-{config.spam_penalty} очко</b>.\n"
            f"• Если очки упадут до 0: мут на <b>{config.zero_points_mute_hours} часа</b>.\n"
            f"• За оскорбление участников: немедленный мут на <b>{config.insult_mute_hours} часа</b>!\n\n"
            "Команды в чате:\n"
            "/rules — правила чата\n"
            "/score — проверить свои очки\n"
            "/top — рейтинг участников",
            parse_mode=ParseMode.HTML,
        )
    else:
        # В группе
        await message.reply(
            "🤖 <b>Бот-модератор активен!</b>\n"
            f"Каждому участнику начислено по {config.initial_points} очков.\n"
            "Соблюдайте правила, чтобы не улететь в мут! Напишите /rules для подробностей.",
            parse_mode=ParseMode.HTML,
        )


@router.message(Command("rules", "правила"))
async def cmd_rules(message: types.Message):
    """Показать правила классного чата."""
    zero_word = "часа" if config.zero_points_mute_hours in (2, 3, 4) else "часов"
    text = (
        "📜 <b>ПРАВИЛА НАШЕГО КЛАССНОГО ЧАТА:</b>\n\n"
        f"1️⃣ Каждому участнику на старте даётся <b>{config.initial_points} очков</b>.\n"
        f"2️⃣ <b>Мат запрещён</b> — штраф <b>-{config.mat_penalty} очко</b> за каждое матное слово.\n"
        f"3️⃣ <b>Спам и флуд запрещены</b> — штраф <b>-{config.spam_penalty} очко</b>.\n"
        f"4️⃣ <b>Оскорбления участников</b> — немедленный <b>МУТ НА {config.insult_mute_hours} ЧАСА</b>!\n"
        f"5️⃣ Если баланс очков падает до <b>0</b> — автоматический <b>МУТ НА {config.zero_points_mute_hours} {zero_word.upper()}</b>, после чего баланс восстанавливается до {config.initial_points}.\n"
        f"6️⃣ 🎁 <b>Бонус вежливости:</b> за каждые <b>{config.clean_messages_reward_step} сообщений без мата</b> начисляется <b>+{config.clean_messages_reward_points} балл</b> к балансу!\n\n"
        "💡 <i>Проверить свои очки:</i> <code>/score</code>\n"
        "🏆 <i>Таблица очков участников:</i> <code>/top</code>"
    )
    await message.reply(text, parse_mode=ParseMode.HTML)


@router.message(Command("score", "points", "баллы", "очки"))
async def cmd_score(message: types.Message):
    """Узнать текущий баланс очков."""
    user = message.from_user
    if not user:
        return

    chat_id = message.chat.id
    user_data = await db.get_or_create_user(
        chat_id=chat_id,
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    points = user_data["points"]
    warnings = user_data["warnings_count"]
    mutes = user_data["mutes_count"]
    clean_count = user_data.get("clean_messages_count", 0) or 0

    status_icon = "🟢" if points >= 7 else ("🟡" if points >= 4 else "🔴")

    reply_text = (
        f"📊 <b>Статистика участника {user.first_name}:</b>\n\n"
        f"{status_icon} Текущие очки: <b>{points}</b>\n"
        f"📈 Сообщений без мата: <b>{clean_count}/{config.clean_messages_reward_step}</b> (до +{config.clean_messages_reward_points} балла)\n"
        f"⚠️ Нарушений зафиксировано: <b>{warnings}</b>\n"
        f"🤐 Количество мутов: <b>{mutes}</b>"
    )
    await message.reply(reply_text, parse_mode=ParseMode.HTML)


@router.message(Command("top", "leaderboard", "рейтинг"))
async def cmd_top(message: types.Message):
    """Таблица лидеров по очкам в чате."""
    chat_id = message.chat.id
    top_users = await db.get_chat_leaderboard(chat_id=chat_id, limit=10)

    if not top_users:
        await message.reply("В этом чате пока нет статистики очков.")
        return

    lines = ["🏆 <b>Рейтинг вежливости класса:</b>\n"]
    medals = ["🥇", "🥈", "🥉"]

    for idx, u in enumerate(top_users, 1):
        medal = medals[idx - 1] if idx <= 3 else f"{idx}."
        name = u["first_name"] or (f"@{u['username']}" if u["username"] else f"ID {u['user_id']}")
        # Экранируем HTML
        name_clean = name.replace("<", "&lt;").replace(">", "&gt;")
        lines.append(f"{medal} <b>{name_clean}</b> — <code>{u['points']}</code> очков (мутов: {u['mutes_count']})")

    await message.reply("\n".join(lines), parse_mode=ParseMode.HTML)

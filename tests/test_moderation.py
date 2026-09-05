"""
Тестирование логики модерации, фильтров текста, антиспама и базы данных.
"""

import sys
import time
import asyncio
import tempfile
from pathlib import Path

# Добавляем родительскую директорию в sys.path для импорта модулей
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from filters.text_filter import check_text_violation, ViolationType
from filters.spam_detector import SpamDetector
from database import Database


def test_clean_messages():
    """Проверка обычных сообщений — не должны распознаваться как нарушения."""
    safe_phrases = [
        "Привет всем, скиньте домашку по физике",
        "Когда у нас колебания маятника?",
        "Сколько стоит булочка с хлебом? Сто рублей",
        "Педагогика и психология на первом уроке",
        "Страхование ответственности для водителей",
        "Отличная погода сегодня",
    ]
    for phrase in safe_phrases:
        v_type, matched = check_text_violation(phrase)
        assert v_type == ViolationType.NONE, f"Ложное срабатывание на: '{phrase}' (matched: {matched})"
    print("✅ Тест чистых сообщений успешно пройден!")


def test_mat_detection():
    """Проверка обнаружения мата (-1 очко)."""
    mat_phrases = [
        "бля, опять контрольная",
        "какой же это пиздец",
        "сука, я забыл тетрадь",
        "все пошло по пизде",
        "х.у.й тебе",
        "да похyй вообще",  # латиница y
        "б л я т ь",
        "б.л.я.",
        "б            л               я.",
        "б / л / я",
        "б | л | я",
        "б + л + я",
        "б_л_я",
        "б-л-я",
        "b.l.y.a",
        "п*и*з*д*е*ц",
        "х   у   й",
        "н а х у й",
        "п о х у й",
        "х у й н я",
        "з а е б а л",
        "о х у е л",
    ]
    for phrase in mat_phrases:
        v_type, matched = check_text_violation(phrase)
        assert v_type in (ViolationType.MAT, ViolationType.INSULT), f"Мат не распознан: '{phrase}'"
    print("✅ Тест обнаружения мата успешно пройден!")


def test_insult_detection():
    """Проверка обнаружения оскорблений (мут на 2 часа)."""
    insult_phrases = [
        "ты дебил",
        "пошел нахуй отсюда",
        "рот закрой свой",
        "ну ты и урод",
        "завали ебало",
        "чмошник конченый",
        "соси хуй",
        "х у е с о с",
        "д е б и л",
        "п и д о р",
        "ш л ю х а",
        "м у д а к",
    ]
    for phrase in insult_phrases:
        v_type, matched = check_text_violation(phrase)
        assert v_type == ViolationType.INSULT, f"Оскорбление не распознано: '{phrase}' (получено: {v_type})"

    # Проверка ситуаций с самокритикой и невинными фразами (НЕ должно быть мута!)
    safe_phrases = [
        "если это не так не надо меня презирать я дебил",
        "я дебил",
        "ну я и дурак конечно",
        "какой я лох",
        "я даун походу",
        "я тупой",
        "не считай меня дебилом",
        "ты не дебил",
        "я не дурак",
    ]
    for phrase in safe_phrases:
        v_type, matched = check_text_violation(phrase)
        assert v_type == ViolationType.NONE, f"Ложный мут за высказывание о себе: '{phrase}' (получено: {v_type})"

    print("✅ Тест обнаружения оскорблений и защиты от ложных мутов успешно пройден!")


def test_spam_detection():
    """Проверка системы обнаружения спама и флуда."""
    detector = SpamDetector(max_messages_in_window=3, window_seconds=2.0, repeat_threshold=3)
    chat_id, user_id = 1001, 555

    # 1. Обычные редкие сообщения не являются спамом
    is_spam, _ = detector.is_spam(chat_id, user_id, "привет")
    assert not is_spam
    is_spam, _ = detector.is_spam(chat_id, user_id, "как дела")
    assert not is_spam

    # 2. Флуд: много быстрых сообщений
    detector.reset_user(chat_id, user_id)
    detector.is_spam(chat_id, user_id, "msg 1")
    detector.is_spam(chat_id, user_id, "msg 2")
    detector.is_spam(chat_id, user_id, "msg 3")
    is_spam, reason = detector.is_spam(chat_id, user_id, "msg 4")
    assert is_spam, "Флуд сообщениями не был обнаружен"
    assert "флуд" in reason

    # 3. Повторы сообщений
    detector.reset_user(chat_id, user_id)
    detector.is_spam(chat_id, user_id, "спамлю")
    detector.is_spam(chat_id, user_id, "спамлю")
    is_spam, reason = detector.is_spam(chat_id, user_id, "спамлю")
    assert is_spam, "Повтор одинаковых сообщений не был обнаружен"
    assert "повтор" in reason

    # 4. Ссылки на каналы / скам
    detector.reset_user(chat_id, user_id)
    is_spam, reason = detector.is_spam(chat_id, user_id, "Заходите в группу t.me/joinchat/AbcDef123")
    assert is_spam, "Спам ссылка не обнаружена"

    print("✅ Тест детектора спама успешно пройден!")


def test_database():
    """Проверка работы базы данных SQLite (очки, штрафы, лидерборд)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        test_db_path = Path(tmp_dir) / "test_chat.db"
        test_db = Database(test_db_path)

        async def run_db_tests():
            await test_db.init_db()

            chat_id = -100123456
            user_id = 42

            # Пользователь должен создаться с 10 стартовыми очками
            user = await test_db.get_or_create_user(chat_id, user_id, "ivan_test", "Иван")
            assert user["points"] == 10, f"Ожидалось 10 очков, получено: {user['points']}"

            # Списание -1 очка за мат
            points = await test_db.deduct_points(chat_id, user_id, amount=1)
            assert points == 9, f"Ожидалось 9 очков, получено: {points}"

            # Запись нарушения
            await test_db.record_violation(chat_id, user_id, "mat", "бля", 1)

            # Добавление очков с проверкой лимита 10
            points = await test_db.add_points(chat_id, user_id, 3)
            assert points == 10, f"Очки не должны превышать лимит 10, получено: {points}"

            # Лидерборд
            board = await test_db.get_chat_leaderboard(chat_id)
            assert len(board) == 1
            assert board[0]["points"] == 10

            # Сброс
            points = await test_db.reset_points(chat_id, user_id)
            assert points == 10

            # Проверка поиска по юзернейму
            found = await test_db.get_user_by_username("@ivan_test")
            assert found is not None and found["user_id"] == 42, "Поиск по @username не сработал"
            found_no_at = await test_db.get_user_by_username("ivan_test")
            assert found_no_at is not None and found_no_at["user_id"] == 42, "Поиск по username без @ не сработал"

            # Проверка виртуального мута (для админов и обычных участников)
            is_muted, rem = await test_db.is_user_muted(chat_id, user_id)
            assert not is_muted, "Пользователь не должен быть в муте изначально"

            await test_db.set_user_mute(chat_id, user_id, duration_hours=2)
            is_muted, rem = await test_db.is_user_muted(chat_id, user_id)
            assert is_muted, "Пользователь должен быть в виртуальном муте"
            assert rem > 0

            await test_db.remove_user_mute(chat_id, user_id)
            is_muted, _ = await test_db.is_user_muted(chat_id, user_id)
            assert not is_muted, "После размута статус мута должен быть снят"

            # Проверка списания очков
            await test_db.deduct_points(chat_id, user_id, 2)
            user_check = await test_db.get_or_create_user(chat_id, user_id, "ivan_test", "Иван")
            assert user_check["points"] == 8, "После списания 2 очков должно остаться 8"

            # Проверка серии чистых сообщений (25 сообщений -> +1 балл)
            for i in range(24):
                is_rewarded, pts, count = await test_db.record_clean_message(chat_id, user_id, reward_step=25)
                assert not is_rewarded, f"На шаге {i+1} награда еще не должна выдаваться"
                assert count == i + 1

            # 25-е чистое сообщение -> получаем +1 очко (было 8, стало 9)
            is_rewarded, pts, count = await test_db.record_clean_message(chat_id, user_id, reward_step=25)
            assert is_rewarded, "На 25-м сообщении должна быть выдана награда"
            assert pts == 9, f"Очки должны увеличиться до 9, получено: {pts}"
            assert count == 0, "Счетчик должен сброситься в 0"

            # Проверка лимита в максимум 10 очков (нельзя больше 10)
            pts = await test_db.add_points(chat_id, user_id, amount=5, max_points=10)
            assert pts == 10, f"Очки не должны превышать 10, получено: {pts}"

            # Проверка сохранения и получения доказательства нарушения
            v_id = await test_db.record_violation(
                chat_id=chat_id,
                user_id=user_id,
                violation_type="mat",
                details="бля",
                points_deducted=1,
                full_text="да бля ты достал уже",
                username="ivan_test",
                first_name="Иван",
                chat_title="8E класс",
                matched_word="бля",
            )
            v = await test_db.get_violation_by_id(v_id)
            assert v is not None, "Нарушение должно сохраняться в БД"
            assert v["matched_word"] == "бля"
            assert v["full_text"] == "да бля ты достал уже"

            # Проверка, что нарушение не сбрасывает счетчик чистых сообщений (не подряд)
            await test_db.record_clean_message(chat_id, user_id, reward_step=25)
            user_check = await test_db.get_or_create_user(chat_id, user_id, "ivan_test", "Иван")
            assert user_check["clean_messages_count"] == 1, "Счетчик чистых сообщений не должен сбрасываться"

        asyncio.run(run_db_tests())
    print("✅ Тест базы данных и лимита 10 очков успешно пройден!")


def test_screenshot():
    """Тест генерации скриншота отдельного сообщения."""
    from utils.screenshot import create_single_message_screenshot
    buf = create_single_message_screenshot(
        user_name="Иван Иванов",
        user_id=12345678,
        text="Привет, это тестовое доказательство нарушения!",
        time_str="23:30",
    )
    assert buf is not None, "Скриншот не должен быть None"
    data = buf.read()
    assert len(data) > 1000, "Файл скриншота слишком мал"
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "Файл должен быть валидным PNG"
    print("✅ Тест чистого скриншота сообщения успешно пройден!")


def test_sticker_detection():
    """Тест сканирования стикеров на нацистскую символику, свастику и пошлость/18+."""
    from filters.sticker_filter import check_sticker_metadata, check_sticker_image_colors
    from PIL import Image, ImageDraw
    import io

    # 1. Проверка метаданных
    assert check_sticker_metadata("nazi_reich_pack", "Стикеры Рейха", None)[0] == True
    assert check_sticker_metadata("hitler_pack", "Гитлер", None)[0] == True
    assert check_sticker_metadata("custom_pack", "Обычный пак", "卐")[0] == True
    assert check_sticker_metadata("hentai_18", "18+ Хентай", None)[0] == True
    assert check_sticker_metadata("cute_cats", "Котики для школы", "🐱")[0] == False

    # 2. Проверка цветовой сигнатуры нацистского флага/свастики
    img_nazi = Image.new("RGBA", (100, 100), (200, 20, 20, 255))
    draw = ImageDraw.Draw(img_nazi)
    draw.ellipse((25, 25, 75, 75), fill=(255, 255, 255, 255))
    draw.rectangle((45, 35, 55, 65), fill=(0, 0, 0, 255))
    buf = io.BytesIO()
    img_nazi.save(buf, format="PNG")
    is_viol, v_type, r = check_sticker_image_colors(buf.getvalue())
    assert is_viol == True and v_type == "фашизм/свастика"

    # 3. Проверка детекции пошлых стикеров с чрезмерным обнажением (>50% кожи)
    img_skin = Image.new("RGBA", (100, 100), (220, 160, 120, 255))
    buf_skin = io.BytesIO()
    img_skin.save(buf_skin, format="PNG")
    is_viol, v_type, r = check_sticker_image_colors(buf_skin.getvalue())
    assert is_viol == True and v_type == "пошлость/18+"

    # 4. Проверка безопасного стикера
    img_safe = Image.new("RGBA", (100, 100), (50, 120, 220, 255))
    buf_safe = io.BytesIO()
    img_safe.save(buf_safe, format="PNG")
    is_viol, v_type, r = check_sticker_image_colors(buf_safe.getvalue())
    assert is_viol == False

    print("✅ Тест сканирования стикеров (нацизм, свастика, пошлость) успешно пройден!")


if __name__ == "__main__":
    print("--- Запуск тестов школьного бота-модератора ---")
    test_clean_messages()
    test_mat_detection()
    test_insult_detection()
    test_spam_detection()
    test_database()
    test_screenshot()
    test_sticker_detection()
    print("\n🎉 ВСЕ ТЕСТЫ УСПЕШНО ПРОЙДЕНЫ!")

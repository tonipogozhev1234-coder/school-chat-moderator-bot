"""
Генерация графического скриншота-карточки нарушения для отправки администратору.
"""

import io
import textwrap
from datetime import datetime
from typing import Optional

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def create_message_screenshot(
    chat_title: str,
    user_name: str,
    user_id: int,
    text: str,
    matched_word: str,
    violation_type: str,
    points_left: int,
) -> Optional[io.BytesIO]:
    """
    Создает графический скриншот-карточку нарушения в стиле Telegram.
    Возвращает io.BytesIO с изображением PNG или None, если PIL недоступен.
    """
    if not HAS_PIL:
        return None

    try:
        width = 650
        # Обертка строк для текста сообщения
        wrapped_lines = textwrap.wrap(text, width=45) if text else ["(пустое сообщение)"]
        line_height = 24
        text_block_height = len(wrapped_lines) * line_height

        # Вычисляем общую высоту карточки
        card_height = 180 + text_block_height + 90
        img = Image.new("RGB", (width, card_height), color=(14, 22, 33))  # Фон Telegram Dark
        draw = ImageDraw.Draw(img)

        # Подбор шрифтов с безопасным fallback
        font_title = None
        font_body = None
        font_small = None

        font_candidates = [
            "arial.ttf",
            "DejaVuSans.ttf",
            "segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        for candidate in font_candidates:
            try:
                font_title = ImageFont.truetype(candidate, 18)
                font_body = ImageFont.truetype(candidate, 16)
                font_small = ImageFont.truetype(candidate, 13)
                break
            except Exception:
                continue

        if not font_body:
            font_title = ImageFont.load_default()
            font_body = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # 1. Шапка карточки
        # Красный бейдж нарушения
        draw.rounded_rectangle([(20, 18), (170, 48)], radius=6, fill=(231, 76, 60))
        draw.text((28, 24), f"🚨 {violation_type.upper()}", fill=(255, 255, 255), font=font_small)

        # Название чата и время
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        draw.text((185, 25), f"Чат: {chat_title[:30]}", fill=(170, 187, 204), font=font_small)
        draw.text((width - 150, 25), now_str, fill=(110, 130, 150), font=font_small)

        draw.line([(20, 60), (width - 20, 60)], fill=(30, 45, 62), width=1)

        # 2. Пузырь сообщения (Message bubble)
        bubble_top = 75
        bubble_bottom = bubble_top + 45 + text_block_height + 15
        draw.rounded_rectangle(
            [(20, bubble_top), (width - 20, bubble_bottom)],
            radius=10,
            fill=(24, 37, 51),  # Цвет входящего облачка Telegram
        )

        # Имя отправителя
        draw.text((35, bubble_top + 10), f"{user_name} (ID: {user_id})", fill=(82, 136, 193), font=font_title)

        # Текст сообщения
        curr_y = bubble_top + 40
        for line in wrapped_lines:
            draw.text((35, curr_y), line, fill=(245, 245, 245), font=font_body)
            curr_y += line_height

        # 3. Подвал нарушения
        footer_top = bubble_bottom + 15
        draw.rounded_rectangle(
            [(20, footer_top), (width - 20, footer_top + 55)],
            radius=8,
            fill=(40, 20, 25),
            outline=(200, 60, 60),
            width=1,
        )
        draw.text((35, footer_top + 10), f"Зафиксировано: «{matched_word}»", fill=(255, 100, 100), font=font_body)
        draw.text(
            (35, footer_top + 32),
            f"Штраф применен. Текущий баланс: {points_left}/10 очков",
            fill=(200, 200, 200),
            font=font_small,
        )

        # Сохранение в буфер байтов
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    except Exception as e:
        print(f"[ERROR] Ошибка генерации скриншота: {e}")
        return None

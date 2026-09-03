"""
Генерация реалистичного графического скриншота сообщения в стиле Telegram для отправки администратору.
"""

import io
import textwrap
from datetime import datetime
from typing import Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# Палитра аватаров Telegram
AVATAR_COLORS = [
    (231, 76, 60),    # Красный
    (230, 126, 34),   # Оранжевый
    (155, 89, 182),   # Фиолетовый
    (46, 204, 113),   # Зеленый
    (52, 152, 219),   # Синий
    (26, 188, 156),   # Бирюзовый
    (243, 104, 224),  # Розовый
]


def _get_avatar_color(user_id: int) -> Tuple[int, int, int]:
    return AVATAR_COLORS[abs(user_id) % len(AVATAR_COLORS)]


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
    Генерирует высококачественный, реалистичный скриншот сообщения в стиле тёмной темы Telegram.
    Использует supersampling (2x масштаб с последующим сглаживанием) для идеальной чёткости.
    """
    if not HAS_PIL:
        return None

    try:
        scale = 2  # 2x supersampling для чётких шрифтов и скруглений
        base_width = 620
        W = base_width * scale

        # Перенос строк сообщения
        wrap_width = 38
        lines = textwrap.wrap(text, width=wrap_width) if text else ["(пустое сообщение)"]
        if len(lines) > 20:
            lines = lines[:20] + ["... (сообщение обрезано)"]

        line_h = 24 * scale
        text_h = len(lines) * line_h

        # Расчет высоты элементов
        header_h = 64 * scale
        bubble_top = header_h + 20 * scale
        bubble_h = (45 * scale) + text_h + (25 * scale)
        footer_top = bubble_top + bubble_h + (20 * scale)
        footer_h = 80 * scale
        total_h = footer_top + footer_h + (20 * scale)

        img = Image.new("RGB", (W, total_h), color=(14, 22, 33))  # Фон Telegram Dark
        draw = ImageDraw.Draw(img)

        # Подбор шрифтов
        font_candidates = [
            "segoeui.ttf",
            "arial.ttf",
            "DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
        f_header = None
        f_user = None
        f_text = None
        f_small = None
        f_avatar = None

        for cand in font_candidates:
            try:
                f_header = ImageFont.truetype(cand, 16 * scale)
                f_user = ImageFont.truetype(cand, 16 * scale)
                f_text = ImageFont.truetype(cand, 15 * scale)
                f_small = ImageFont.truetype(cand, 12 * scale)
                f_avatar = ImageFont.truetype(cand, 18 * scale)
                break
            except Exception:
                continue

        if not f_text:
            f_header = ImageFont.load_default()
            f_user = ImageFont.load_default()
            f_text = ImageFont.load_default()
            f_small = ImageFont.load_default()
            f_avatar = ImageFont.load_default()

        # -------------------------------------------------------------
        # 1. ШАПКА ЧАТА (TELEGRAM HEADER)
        # -------------------------------------------------------------
        draw.rectangle([(0, 0), (W, header_h)], fill=(23, 33, 43))
        # Иконка чата (круглый аватар группы)
        chat_ava_size = 40 * scale
        ava_x = 20 * scale
        ava_y = 12 * scale
        draw.ellipse([(ava_x, ava_y), (ava_x + chat_ava_size, ava_y + chat_ava_size)], fill=(74, 144, 226))
        # Буква группы
        group_letter = chat_title[0].upper() if chat_title else "Ч"
        draw.text((ava_x + 13 * scale, ava_y + 8 * scale), group_letter, fill=(255, 255, 255), font=f_header)

        # Название чата и статус
        draw.text((ava_x + chat_ava_size + 14 * scale, 14 * scale), chat_title[:32], fill=(245, 245, 245), font=f_header)
        draw.text((ava_x + chat_ava_size + 14 * scale, 36 * scale), "Классный чат • фиксация нарушения", fill=(110, 130, 150), font=f_small)

        # Разделитель под шапкой
        draw.line([(0, header_h), (W, header_h)], fill=(15, 24, 34), width=2 * scale)

        # -------------------------------------------------------------
        # 2. АВАТАР ПОЛЬЗОВАТЕЛЯ И ПУЗЫРЬ СООБЩЕНИЯ
        # -------------------------------------------------------------
        user_ava_size = 42 * scale
        u_ava_x = 20 * scale
        u_ava_y = bubble_top + bubble_h - user_ava_size  # аватар снизу сообщения как в TG

        ava_color = _get_avatar_color(user_id)
        draw.ellipse([(u_ava_x, u_ava_y), (u_ava_x + user_ava_size, u_ava_y + user_ava_size)], fill=ava_color)
        first_letter = user_name[0].upper() if user_name else "U"
        draw.text((u_ava_x + 14 * scale, u_ava_y + 9 * scale), first_letter, fill=(255, 255, 255), font=f_avatar)

        # Пузырь сообщения (Message Bubble)
        b_x1 = u_ava_x + user_ava_size + 12 * scale
        # Ширина пузыря по длине текста
        longest_line = max(len(l) for l in lines)
        b_width = max(240 * scale, min(int(longest_line * 9.5 * scale) + 60 * scale, W - b_x1 - 30 * scale))
        b_x2 = b_x1 + b_width
        b_y1 = bubble_top
        b_y2 = bubble_top + bubble_h

        # Скруглённый прямоугольник облачка (цвет входящего в TG Desktop Dark: #182533)
        radius = 12 * scale
        draw.rounded_rectangle([(b_x1, b_y1), (b_x2, b_y2)], radius=radius, fill=(24, 37, 51))

        # Имя отправителя (в цвет аватара как в TG)
        draw.text((b_x1 + 16 * scale, b_y1 + 10 * scale), f"{user_name}", fill=ava_color, font=f_user)

        # Текст сообщения
        cur_y = b_y1 + 34 * scale
        for l in lines:
            draw.text((b_x1 + 16 * scale, cur_y), l, fill=(245, 245, 245), font=f_text)
            cur_y += line_h

        # Время отправки в правом нижнем углу пузыря
        time_str = datetime.now().strftime("%H:%M")
        draw.text((b_x2 - 50 * scale, b_y2 - 20 * scale), time_str, fill=(110, 130, 150), font=f_small)

        # -------------------------------------------------------------
        # 3. КАРТОЧКА НАРУШЕНИЯ (ДОКАЗАТЕЛЬСТВО)
        # -------------------------------------------------------------
        f_box_x1 = 20 * scale
        f_box_x2 = W - 20 * scale
        f_box_y1 = footer_top
        f_box_y2 = footer_top + footer_h

        # Фон плашки нарушения (темно-красный #2b171c с красной рамкой)
        draw.rounded_rectangle(
            [(f_box_x1, f_box_y1), (f_box_x2, f_box_y2)],
            radius=10 * scale,
            fill=(43, 23, 28),
            outline=(214, 48, 49),
            width=2 * scale,
        )

        # Красный бейдж типа нарушения
        badge_w = 160 * scale
        draw.rounded_rectangle(
            [(f_box_x1 + 14 * scale, f_box_y1 + 14 * scale), (f_box_x1 + 14 * scale + badge_w, f_box_y1 + 42 * scale)],
            radius=6 * scale,
            fill=(214, 48, 49),
        )
        draw.text((f_box_x1 + 24 * scale, f_box_y1 + 19 * scale), f"🚨 {violation_type.upper()}", fill=(255, 255, 255), font=f_small)

        # Строка с запрещенным словом
        draw.text(
            (f_box_x1 + 14 * scale + badge_w + 14 * scale, f_box_y1 + 20 * scale),
            f"Запрещено: «{matched_word}»",
            fill=(255, 120, 120),
            font=f_user,
        )

        # Строка информации о нарушителе и балансе очков
        draw.text(
            (f_box_x1 + 16 * scale, f_box_y1 + 50 * scale),
            f"ID: {user_id}  •  Штраф применен  •  Осталось очков: {points_left}",
            fill=(200, 205, 215),
            font=f_small,
        )

        # Уменьшаем изображение в scale раз со сглаживанием (LANCZOS) для ультра-чёткости
        final_w = base_width
        final_h = total_h // scale
        resampling_filter = getattr(Image, "Resampling", Image).LANCZOS
        img_smooth = img.resize((final_w, final_h), resample=resampling_filter)

        buf = io.BytesIO()
        img_smooth.save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf

    except Exception as e:
        print(f"[ERROR] Ошибка генерации скриншота: {e}")
        return None

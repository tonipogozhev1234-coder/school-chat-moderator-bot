"""
Генерация чистого, реалистичного скриншота отдельного сообщения в стиле Telegram Dark Mode.
"""

import io
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

BASE_DIR = Path(__file__).resolve().parent.parent
FONT_PATH = BASE_DIR / "assets" / "fonts" / "font.ttf"
FONT_BOLD_PATH = BASE_DIR / "assets" / "fonts" / "font_bold.ttf"

# Палитра цветов для авторов сообщений в Telegram (Telegram Dark)
NAME_COLORS = [
    (239, 107, 107),  # Красный
    (240, 169, 79),   # Оранжевый
    (178, 142, 237),  # Фиолетовый
    (100, 209, 137),  # Зеленый
    (83, 158, 234),   # Голубой
    (54, 187, 199),   # Бирюзовый
    (235, 114, 168),  # Розовый
]


def _get_name_color(user_id: int) -> Tuple[int, int, int]:
    return NAME_COLORS[abs(user_id) % len(NAME_COLORS)]


async def fetch_user_avatar_bytes(bot, user_id: int) -> Optional[bytes]:
    """Загружает байты аватара пользователя Telegram, если доступен."""
    try:
        photos = await bot.get_user_profile_photos(user_id=user_id, limit=1)
        if photos.total_count > 0 and photos.photos:
            file_id = photos.photos[0][0].file_id
            file_info = await bot.get_file(file_id)
            if file_info.file_path:
                stream = io.BytesIO()
                await bot.download_file(file_info.file_path, stream)
                return stream.getvalue()
    except Exception:
        pass
    return None


def _load_font(size: int, bold: bool = False):
    """Загрузка шрифта с гарантированной поддержкой кириллицы."""
    if not HAS_PIL:
        return None

    path = FONT_BOLD_PATH if bold else FONT_PATH
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            pass

    # Резервные системные шрифты
    fallback_fonts = [
        "arialbd.ttf" if bold else "arial.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for font_name in fallback_fonts:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            continue

    return ImageFont.load_default()


def create_single_message_screenshot(
    user_name: str,
    user_id: int,
    text: str,
    time_str: Optional[str] = None,
    avatar_bytes: Optional[bytes] = None,
    **kwargs,
) -> Optional[io.BytesIO]:
    """
    Генерирует чистый скриншот отдельного сообщения Telegram (пузырь сообщения с аватаркой,
    именем автора, текстом и временем отправки).
    Никаких лишних рамок, шапок или карточек — выглядит в точности как снимок экрана Telegram.
    """
    if not HAS_PIL:
        return None

    try:
        scale = 2  # 2x supersampling для чётких скруглений и шрифтов
        time_str = time_str or datetime.now().strftime("%H:%M")
        name_color = _get_name_color(user_id)

        # Шрифты
        f_name = _load_font(15 * scale, bold=True)
        f_text = _load_font(15 * scale, bold=False)
        f_time = _load_font(12 * scale, bold=False)
        f_avatar = _load_font(18 * scale, bold=True)

        # Подготовка текста (разбивка по строкам с учетом ширины)
        max_bubble_text_w = 420 * scale
        raw_paragraphs = text.split("\n") if text else ["(пустое сообщение)"]
        wrapped_lines = []

        dummy_img = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)

        for paragraph in raw_paragraphs:
            words = paragraph.split(" ")
            if not words or words == [""]:
                wrapped_lines.append("")
                continue

            current_line = ""
            for w in words:
                test_line = f"{current_line} {w}".strip() if current_line else w
                bbox = dummy_draw.textbbox((0, 0), test_line, font=f_text)
                w_line = bbox[2] - bbox[0]
                if w_line <= max_bubble_text_w:
                    current_line = test_line
                else:
                    if current_line:
                        wrapped_lines.append(current_line)
                    current_line = w
            if current_line:
                wrapped_lines.append(current_line)

        if len(wrapped_lines) > 25:
            wrapped_lines = wrapped_lines[:25] + ["..."]

        line_spacing = 6 * scale
        name_bbox = dummy_draw.textbbox((0, 0), user_name, font=f_name)
        name_w = name_bbox[2] - name_bbox[0]
        name_h = name_bbox[3] - name_bbox[1]

        time_bbox = dummy_draw.textbbox((0, 0), time_str, font=f_time)
        time_w = time_bbox[2] - time_bbox[0]
        time_h = time_bbox[3] - time_bbox[1]

        # Расчет ширины текста
        max_line_w = name_w
        for line in wrapped_lines:
            if line:
                b = dummy_draw.textbbox((0, 0), line, font=f_text)
                lw = b[2] - b[0]
                if lw > max_line_w:
                    max_line_w = lw

        # Расчет размеров пузыря (bubble)
        bubble_pad_x = 16 * scale
        bubble_pad_y = 12 * scale
        single_line_h = dummy_draw.textbbox((0, 0), "Аg", font=f_text)[3] - dummy_draw.textbbox((0, 0), "Аg", font=f_text)[1]
        
        text_block_h = len(wrapped_lines) * (single_line_h + line_spacing)
        
        bubble_w = max_line_w + (bubble_pad_x * 2) + (time_w + 14 * scale)
        bubble_w = max(bubble_w, 180 * scale)
        bubble_h = bubble_pad_y + name_h + (8 * scale) + text_block_h + bubble_pad_y

        # Параметры сцены (Telegram чат)
        avatar_size = 42 * scale
        pad_left = 18 * scale
        pad_top = 18 * scale
        pad_bottom = 18 * scale
        pad_right = 24 * scale
        gap_avatar_bubble = 12 * scale

        total_w = pad_left + avatar_size + gap_avatar_bubble + bubble_w + pad_right
        total_h = pad_top + max(avatar_size, bubble_h) + pad_bottom

        # Фон чата (Telegram Dark #0e1621)
        img = Image.new("RGBA", (total_w, total_h), color=(14, 22, 33, 255))
        draw = ImageDraw.Draw(img)

        # 1. РЕНДЕР АВАТАРКИ
        avatar_x = pad_left
        avatar_y = pad_top + bubble_h - avatar_size
        if avatar_y < pad_top:
            avatar_y = pad_top

        rendered_ava = False
        if avatar_bytes:
            try:
                ava_src = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
                ava_src = ava_src.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
                mask = Image.new("L", (avatar_size, avatar_size), 0)
                mask.paste(255, (0, 0, avatar_size, avatar_size))
                img.paste(ava_src, (avatar_x, avatar_y), mask)
                rendered_ava = True
            except Exception:
                rendered_ava = False

        if not rendered_ava:
            draw.ellipse(
                [(avatar_x, avatar_y), (avatar_x + avatar_size, avatar_y + avatar_size)],
                fill=name_color,
            )
            initial = user_name[0].upper() if user_name else "?"
            ibox = dummy_draw.textbbox((0, 0), initial, font=f_avatar)
            iw = ibox[2] - ibox[0]
            ih = ibox[3] - ibox[1]
            draw.text(
                (avatar_x + (avatar_size - iw) / 2, avatar_y + (avatar_size - ih) / 2 - 2 * scale),
                initial,
                fill=(255, 255, 255),
                font=f_avatar,
            )

        # 2. РЕНДЕР ПУЗЫРЯ СООБЩЕНИЯ (Bubble)
        bubble_x = pad_left + avatar_size + gap_avatar_bubble
        bubble_y = pad_top
        bubble_color = (24, 37, 51, 255)  # Telegram Desktop Dark bubble
        radius = 14 * scale

        draw.rounded_rectangle(
            [(bubble_x, bubble_y), (bubble_x + bubble_w, bubble_y + bubble_h)],
            radius=radius,
            fill=bubble_color,
        )

        # 3. ИМЯ АВТОРА
        cur_y = bubble_y + bubble_pad_y
        draw.text(
            (bubble_x + bubble_pad_x, cur_y),
            user_name,
            fill=name_color,
            font=f_name,
        )
        cur_y += name_h + (8 * scale)

        # 4. ТЕКСТ СООБЩЕНИЯ
        for line in wrapped_lines:
            if line:
                draw.text(
                    (bubble_x + bubble_pad_x, cur_y),
                    line,
                    fill=(245, 245, 245),
                    font=f_text,
                )
            cur_y += single_line_h + line_spacing

        # 5. ВРЕМЯ СООБЩЕНИЯ (В правом нижнем углу пузыря)
        time_x = bubble_x + bubble_w - bubble_pad_x - time_w
        time_y = bubble_y + bubble_h - bubble_pad_y - time_h + (4 * scale)
        draw.text(
            (time_x, time_y),
            time_str,
            fill=(110, 134, 156),
            font=f_time,
        )

        # Сглаживание (LANCZOS)
        final_w = total_w // scale
        final_h = total_h // scale
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        img_smooth = img.resize((final_w, final_h), resample=resampling)

        out_buf = io.BytesIO()
        img_smooth.convert("RGB").save(out_buf, format="PNG", quality=95)
        out_buf.seek(0)
        return out_buf
    except Exception as e:
        print(f"[ERROR] Ошибка генерации скриншота: {e}")
        return None


# Алиас для обратной совместимости
def create_message_screenshot(*args, **kwargs) -> Optional[io.BytesIO]:
    if "user_name" in kwargs:
        return create_single_message_screenshot(**kwargs)
    if len(args) >= 4:
        return create_single_message_screenshot(
            user_name=args[1],
            user_id=args[2],
            text=args[3],
        )
    return None

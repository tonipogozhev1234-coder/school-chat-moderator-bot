"""
Фильтрация и сканирование стикеров Telegram:
1. Защита от нацистской символики, свастики и отсылок на фашистскую Германию / Третий рейх.
2. Защита от пошлых, эротических и 18+ стикеров (хентай, обнажёнка, порнография).

Многоуровневый анализ:
- Анализ метаданных стикерпака (set_name, название стикерпака, эмодзи стикера).
- Локальный визуальный анализ изображения (Pillow: сигнатура флага/геральдики рейха, процент открытого тела/skin-tone).
- Опциональный AI Vision анализ через Gemini API при наличии ключа.
"""

import io
import re
from typing import Tuple, Optional, Dict
from PIL import Image
from aiogram import Bot, types

# Кэш названий стикерпаков (name -> title), чтобы не спамить API Telegram
_STICKER_PACK_CACHE: Dict[str, str] = {}

# Ключевые слова: Нацизм, фашистская Германия, Гитлер, Третий рейх, свастика
NAZI_KEYWORDS = [
    "hitler", "гитлер", "reich", "рейх", "nazi", "нацист", "нацизм", "swastika",
    "свастик", "фашист", "фашизм", "fascis", "wehrmacht", "вермахт", "1488",
    "nsdap", "нсдап", "fuhrer", "фюрер", "third_reich", "третий_рейх",
    "sieg_heil", "зиг_хайль", "зигхайль", "хайль_гитлер", "хайль", "aryan", "ариец",
    "ss_waffen", "schutzstaffel"
]

# Ключевые слова: Пошлость, 18+, хентай, эротика, обнаженка
NSFW_KEYWORDS = [
    "porn", "порно", "hentai", "хентай", "erotic", "эротик", "эро", "ero", "nsfw",
    "xxx", "18+", "секс", "sex", "boobs", "сиськи", "сисек", "nude", "нюдс",
    "голая", "голые", "член", "dick", "пизд", "pussy", "минет", "blowjob",
    "ахегао", "ahegao", "яой", "yaoi", "юри", "yuri", "интим", "orgasm", "вагина", "vagina",
    "bitch", "adult", "ecchi", "этти"
]

# Запрещенные символы свастики в эмодзи
NAZI_EMOJIS = {"卐", "卍"}


def check_sticker_metadata(
    set_name: Optional[str],
    set_title: Optional[str],
    emoji: Optional[str],
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Проверка метаданных стикера (название пака, заголовок пака, эмодзи).
    Возвращает: (is_violation, violation_category, reason)
    """
    # 1. Проверка эмодзи на свастику
    if emoji and any(sym in NAZI_EMOJIS for sym in emoji):
        return True, "фашизм/свастика", "символ свастики в эмодзи стикера"

    # Собираем текстовое описание пака для поиска
    combined_text = f"{set_name or ''} {set_title or ''}".lower().replace("-", " ").replace("_", " ")

    # 2. Проверка на фашистскую символику и Германию
    for kw in NAZI_KEYWORDS:
        if kw in combined_text:
            return True, "фашизм/свастика", f"отсылка на нацистскую Германию/свастику ({kw})"

    # Проверка на аббревиатуры SS / СС в контексте
    if re.search(r"\b(ss|сс)\b", combined_text, re.IGNORECASE):
        return True, "фашизм/свастика", "нацистская символика (SS)"

    # 3. Проверка на пошлость и 18+
    for kw in NSFW_KEYWORDS:
        if kw in combined_text:
            return True, "пошлость/18+", f"пошлый/эротический стикерпак ({kw})"

    return False, None, None


def check_sticker_image_colors(image_bytes: bytes) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Анализ изображения стикера через Pillow:
    1. Сигнатура нацистского флага/символики:
       доминирующий красный фон + белый круг + черная геометрия по центру.
    2. Анализ тона кожи (Skin-Tone Ratio):
       высокий процент обнаженного тела (> 48% видимой площади).
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = img.convert("RGBA")
        img.thumbnail((128, 128))
    except Exception:
        return False, None, None

    width, height = img.size
    total_pixels = width * height
    if total_pixels == 0:
        return False, None, None

    visible_pixels = 0
    red_count = 0
    white_count = 0
    black_count = 0
    skin_count = 0

    pixels = list(img.getdata())
    for r, g, b, a in pixels:
        # Игнорируем полностью прозрачные пиксели
        if a < 50:
            continue
        visible_pixels += 1

        # 1. Красно-бело-черная нацистская палитра
        # Насыщенный красный
        if r > 160 and g < 60 and b < 60:
            red_count += 1
        # Чистый белый
        elif r > 215 and g > 215 and b > 215:
            white_count += 1
        # Черный
        elif r < 45 and g < 45 and b < 45:
            black_count += 1

        # 2. Детекция оттенков человеческой кожи (RGB skin-tone heuristic)
        # Стандартное распределение цвета кожи в пространстве RGB
        if (
            r > 95 and g > 40 and b > 20
            and (max(r, g, b) - min(r, g, b) > 15)
            and abs(r - g) > 15
            and r > g and r > b
        ):
            skin_count += 1

    if visible_pixels < 50:
        return False, None, None

    red_ratio = red_count / visible_pixels
    white_ratio = white_count / visible_pixels
    black_ratio = black_count / visible_pixels
    skin_ratio = skin_count / visible_pixels

    # Проверка нацистской геральдической триады (красный фон + белый диск + черная свастика)
    if red_ratio >= 0.28 and white_ratio >= 0.08 and black_ratio >= 0.03:
        return True, "фашизм/свастика", "цветовая гамма нацистской символики/свастики"

    # Проверка на пошлость / чрезмерную обнажённость
    if skin_ratio >= 0.50:
        return True, "пошлость/18+", f"чрезмерно обнажённый контент ({int(skin_ratio * 100)}% кожи)"

    return False, None, None


async def get_sticker_pack_title(bot: Bot, set_name: Optional[str]) -> Optional[str]:
    """Получает и кэширует заголовок стикерпака из Telegram API."""
    if not set_name:
        return None
    if set_name in _STICKER_PACK_CACHE:
        return _STICKER_PACK_CACHE[set_name]

    try:
        sticker_set = await bot.get_sticker_set(name=set_name)
        if sticker_set and sticker_set.title:
            _STICKER_PACK_CACHE[set_name] = sticker_set.title
            return sticker_set.title
    except Exception:
        pass
    return None


def normalize_sticker_to_jpeg(raw_bytes: bytes) -> Optional[bytes]:
    """Конвертирует стикер любого формата (WebP/PNG/RGBA) в чистый JPEG на белом фоне."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            if img.mode == "P":
                img = img.convert("RGBA")
            if "A" in img.getbands():
                bg.paste(img, mask=img.split()[-1])
            else:
                bg.paste(img)
            img = bg
        else:
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception:
        return None


# Быстрые и стабильные Vision модели Gemini по приоритету
VISION_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-flash-latest",
]


async def scan_sticker_violation(
    bot: Bot,
    sticker: types.Sticker,
    gemini_api_key: str = "",
) -> Tuple[bool, Optional[str], Optional[str], Optional[bytes]]:
    """
    Комплексное сканирование стикера на пошлость и нацистскую/фашистскую символику.
    Возвращает: (is_violation: bool, violation_type: str, reason: str, sticker_bytes: Optional[bytes])
    """
    set_name = sticker.set_name
    emoji = sticker.emoji

    # 1. Получаем заголовок стикерпака
    set_title = await get_sticker_pack_title(bot, set_name)

    # 2. Сканируем метаданные пака
    viol, v_type, reason = check_sticker_metadata(set_name, set_title, emoji)

    # 3. Скачиваем байты стикера для визуального анализа (и для скриншота доказательств!)
    sticker_bytes: Optional[bytes] = None
    # Для анимированных (.tgs) и видео (.webm) стикеров берем статичный thumbnail!
    file_id_to_fetch = sticker.file_id
    if (sticker.is_animated or sticker.is_video) and sticker.thumbnail:
        file_id_to_fetch = sticker.thumbnail.file_id

    try:
        file_info = await bot.get_file(file_id_to_fetch)
        if file_info.file_path:
            # Если файл .tgs или .webm, а у стикера есть thumbnail — переключаемся на thumbnail
            if file_info.file_path.endswith((".tgs", ".webm")) and sticker.thumbnail:
                thumb_info = await bot.get_file(sticker.thumbnail.file_id)
                if thumb_info.file_path:
                    downloaded = await bot.download_file(thumb_info.file_path)
                    if downloaded:
                        sticker_bytes = downloaded.read()
            else:
                downloaded = await bot.download_file(file_info.file_path)
                if downloaded:
                    sticker_bytes = downloaded.read()
    except Exception as e:
        print(f"[WARN] Не удалось скачать стикер для анализа: {e}")

    print(f"[STICKER] Сканирование: pack={set_name}, emoji={emoji}, has_gemini={bool(gemini_api_key)}")

    # Если нарушение уже найдено по метаданным
    if viol:
        print(f"[STICKER] Обнаружено нарушение по метаданным: {reason}")
        return True, v_type, reason, sticker_bytes

    # 4. Визуальный анализ через Pillow (цветовая палитра рейха и skin-tone ratio)
    if sticker_bytes:
        img_viol, img_type, img_reason = check_sticker_image_colors(sticker_bytes)
        if img_viol:
            print(f"[STICKER] Обнаружено нарушение через Pillow: {img_reason}")
            return True, img_type, img_reason, sticker_bytes

    # 5. Опциональный AI Vision анализ через Gemini при наличии ключа
    if gemini_api_key and sticker_bytes:
        print("[STICKER] Запуск Gemini Vision...")
        ai_viol, ai_type, ai_reason = await _check_with_gemini_vision(sticker_bytes, gemini_api_key)
        if ai_viol:
            print(f"[STICKER] AI обнаружил нарушение: {ai_reason}")
            return True, ai_type, ai_reason, sticker_bytes
    elif not gemini_api_key:
        print("[STICKER] Пропуск AI Vision: GEMINI_API_KEY не установлен на хостинге!")

    return False, None, None, sticker_bytes


async def _check_with_gemini_vision(image_bytes: bytes, api_key: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Проверка стикера через Gemini Vision API.
    Использует нормализацию изображения (JPEG на белом фоне) и каскад моделей.
    """
    try:
        import base64
        import aiohttp

        # Нормализуем изображение к чистому JPEG на белом фоне
        jpeg_bytes = normalize_sticker_to_jpeg(image_bytes) or image_bytes
        b64_img = base64.b64encode(jpeg_bytes).decode("utf-8")

        prompt = (
            "School chat moderation: check if this sticker contains:\n"
            "1) Nazi/Fascist symbols (swastika, SS runes, Hitler, Third Reich eagle/flag).\n"
            "2) Vulgar/NSFW/18+ content (nudity, pornography, hentai, sexual acts).\n\n"
            "Respond ONLY in this exact format:\n"
            "VIOLATION: NAZI (<details>)\n"
            "or\n"
            "VIOLATION: NSFW (<details>)\n"
            "or\n"
            "SAFE"
        )

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": b64_img,
                        }
                    }
                ]
            }]
        }

        async with aiohttp.ClientSession() as session:
            for model_name in VISION_MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                try:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=12)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            candidates = data.get("candidates", [])
                            if not candidates:
                                continue

                            cand = candidates[0]
                            finish_reason = cand.get("finishReason", "")

                            # Если сработал фильтр безопасности самого Google на экстремизм/порнографию
                            if finish_reason == "SAFETY":
                                return True, "фашизм/свастика", "AI заблокировал изображение политикой безопасности (экстремизм/насилие)"

                            parts = cand.get("content", {}).get("parts", [])
                            if not parts:
                                continue

                            answer = parts[0].get("text", "").strip()
                            ans_upper = answer.upper()

                            if any(k in ans_upper for k in ["VIOLATION: NAZI", "NAZI", "SWASTIKA", "СВАСТИК", "ФАШИЗМ", "HITLER", "ГИТЛЕР", "REICH", "РЕЙХ"]):
                                return True, "фашизм/свастика", "нейросеть распознала нацистскую символику/свастику"
                            if any(k in ans_upper for k in ["VIOLATION: NSFW", "NSFW", "PORN", "ПОРНО", "HENTAI", "ХЕНТАЙ", "EROTIC", "ЭРОТИК", "NUDE", "SEX"]):
                                return True, "пошлость/18+", "нейросеть распознала 18+/пошлый контент"
                            if "SAFE" in ans_upper:
                                return False, None, None
                        else:
                            err_body = await resp.text()
                            print(f"[WARN] Gemini Vision {model_name} status {resp.status}: {err_body[:120]}")
                except Exception as ex:
                    print(f"[WARN] Gemini Vision {model_name} ошибка: {ex}")
                    continue

    except Exception as e:
        print(f"[WARN] Ошибка в модуле Gemini Vision: {e}")

    return False, None, None


"""
Фильтрация текста сообщений: обнаружение мата и оскорблений.
"""

import re
from enum import Enum
from typing import Tuple, Optional


class ViolationType(str, Enum):
    NONE = "none"
    MAT = "mat"
    INSULT = "insult"


# Таблица транслитерации и leetspeak (замена визуально похожих символов на кириллицу)
LEETSPEAK_MAP = {
    'a': 'а', 'b': 'б', 'c': 'с', 'e': 'е', 'k': 'к', 'm': 'м',
    'h': 'н', 'o': 'о', 'p': 'р', 't': 'т', 'y': 'у', 'x': 'х',
    '@': 'а', '0': 'о', '1': 'и', '3': 'з', '4': 'ч', '6': 'б',
    '$': 'с', 'u': 'и', 'v': 'в', 'w': 'в', 'i': 'и'
}

# Белый список частых слов, содержащих спорные подстроки, но не являющихся матом
WHITELIST_WORDS = {
    "колебания", "колебание", "колебаться", "колеблется", "колебаний",
    "употребление", "употреблять", "употреблять", "потребление", "злоупотребление",
    "рубль", "рубля", "рублей", "рубли", "рублям",
    "хлеб", "хлебом", "хлебороб",
    "стебель", "гребля", "грести",
    "ястреб", "ястребы",
    "скипидар", "педагог", "педагогика",
    "страхование", "страховка", "перестраховка",
    "ребенок", "ребёнок", "ребята",
    "оскорбление", "оскорблять", "оскорбил"
}

# Регулярные выражения для прямых оскорблений (наказывается мутом на 2 часа)
INSULT_PATTERNS = [
    # Личные грубые оскорбления
    r"\b(ты|вы|он|она|чел|чувак|этот)?\s*(дебил|даун|дура[кч]?|урод|шлюх[аеиу]|тварь|мразь|гной|биомусор|ничтожество)\b",
    r"\b(чмо|чмошник|петух|лошара|лошок|собака|сучара|гнида|шалава|паскуда)\b",
    # Матерные прямые оскорбления
    r"\b(пидор|пидар|педик|пидорас|гондон|гандон|хуесос|долбоеб|долбоёб|уебище|уёбище|мудила|мудак|еблан|ёблан)\b",
    r"\b(пошел|пошёл|иди|пшел|вали)\s+(на\s*хуй|в\s*пизду|в\s*жопу)\b",
    r"\b(рот\s*закрой|закрой\s*пасть|ебало\s*завали|завали\s*ебало)\b",
    r"\b(соси\s+хуй|соси|отсоси|отсоси\s+хуй)\b",
    r"\bмать\s+(твою|ебал|жива|в\s*канаве)\b",
]

# Регулярные выражения для нецензурной лексики (мата), наказывается -1 очком
MAT_PATTERNS = [
    # Корень хуй / хуе / хуя / хуи
    r"\b(ху[йиеёяю]|ху[её]в|ху[её]н|нах[уеё]|пох[уеё])\w*\b",
    r"\bхули\b",
    # Корень пизд
    r"\b(пизд|пизда|пиздец|пиздо|спизд|впизд|распизд|отпизд)\w*\b",
    # Корень еб / ёб
    r"\b([её]б[аеёиоуы]|выеб|заеб|перееб|подъеб|наеб|уеб|въеб|доеб|проеб|разъеб|с[ъеё]б|объеб)\w*\b",
    r"\bеб[латьуетны]\w*\b",
    # Корень бля / бляд
    r"\b(бл[яея]д|бля|бляха|блядство|блядина)\w*\b",
    # Корень сука
    r"\bсук[аеиоу]\b",
    r"\bсучка\b",
    # Корень манд
    r"\bманд[аеуоы]\w*\b",
    # Корень залуп
    r"\bзалуп\w*\b",
    # Дополнительно
    r"\bелд[аеу]\b",
]


def normalize_text(text: str) -> str:
    """
    Приведение текста к нижнему регистру, замена похожих символов
    и удаление попыток замаскировать слова точками, тире и пробелами.
    """
    if not text:
        return ""

    lowered = text.lower()

    # Замена латиницы и leetspeak символов на аналогичную кириллицу
    trans_chars = []
    for char in lowered:
        trans_chars.append(LEETSPEAK_MAP.get(char, char))
    converted = "".join(trans_chars)

    # Убираем повторяющиеся одинаковые символы подряд (например, "сууууука" -> "сука")
    compressed = re.sub(r'(.)\1{2,}', r'\1', converted)

    return compressed


def remove_spacing_tricks(text: str) -> str:
    """
    Убирает пробелы, точки, дефисы между буквами одного слова (например, "х.у.й" или "п и з д а").
    """
    # Если строка разбита пробелами/символами типа "п . и . з . д . а"
    pattern = r'(?<=[а-яёa-z])[\s\.\-_,\*]+(?=[а-яёa-z])'
    condensed = re.sub(pattern, '', text)
    return condensed


def check_text_violation(text: str) -> Tuple[ViolationType, Optional[str]]:
    """
    Проверяет текст на наличие нарушений.
    Возвращает (ViolationType, совпавший_фрагмент).

    Приоритет:
    1. Оскорбление (мут на 2 часа) - наивысший приоритет.
    2. Мат (-1 очко).
    3. Без нарушений.
    """
    if not text:
        return ViolationType.NONE, None

    normalized = normalize_text(text)
    condensed = remove_spacing_tricks(normalized)

    # 1. Проверка на оскорбления
    for pattern in INSULT_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            # Проверяем, не в белом ли списке
            word = match.group(0).strip()
            if word not in WHITELIST_WORDS:
                return ViolationType.INSULT, word

        # Проверяем также слитую версию
        match_cond = re.search(pattern, condensed, re.IGNORECASE)
        if match_cond:
            word = match_cond.group(0).strip()
            if word not in WHITELIST_WORDS:
                return ViolationType.INSULT, word

    # 2. Проверка на мат
    for pattern in MAT_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            word = match.group(0).strip()
            if word not in WHITELIST_WORDS:
                return ViolationType.MAT, word

        match_cond = re.search(pattern, condensed, re.IGNORECASE)
        if match_cond:
            word = match_cond.group(0).strip()
            if word not in WHITELIST_WORDS:
                return ViolationType.MAT, word

    return ViolationType.NONE, None

"""
Фильтрация текста сообщений: глубокое обнаружение мата и оскорблений.
Защита от любых попыток обхода (пробелы, точки, спецсимволы, leetspeak, транслит).
"""

import re
from enum import Enum
from typing import Tuple, Optional, List


class ViolationType(str, Enum):
    NONE = "none"
    MAT = "mat"
    INSULT = "insult"


# Таблица замен транслитерации двухбуквенных сочетаний
TRANSLIT_BIGRAMS = {
    'ya': 'я', 'yu': 'ю', 'sh': 'ш', 'ch': 'ч', 'zh': 'ж',
    'th': 'т', 'ph': 'ф', 'ck': 'к', 'yo': 'ё', 'ye': 'е',
}

# Таблица транслитерации и leetspeak одиночных символов
LEETSPEAK_MAP = {
    'a': 'а', 'b': 'б', 'c': 'с', 'd': 'д', 'e': 'е', 'f': 'ф',
    'g': 'г', 'h': 'х', 'i': 'и', 'j': 'й', 'k': 'к', 'l': 'л',
    'm': 'м', 'n': 'н', 'o': 'о', 'p': 'р', 'r': 'р', 's': 'с',
    't': 'т', 'u': 'у', 'v': 'в', 'w': 'в', 'x': 'х', 'y': 'у',
    'z': 'з',
    # Цифры и спецсимволы, визуально заменяющие буквы
    '@': 'а', '0': 'о', '1': 'и', '3': 'з', '4': 'ч', '6': 'б',
    '$': 'с', '!': 'и'
}

# Белый список невинных слов, содержащих похожие части корней
WHITELIST_WORDS = {
    "колебания", "колебание", "колебаться", "колеблется", "колебаний",
    "употребление", "употреблять", "потребление", "злоупотребление",
    "рубль", "рубля", "рублей", "рубли", "рублям",
    "хлеб", "хлебом", "хлебороб",
    "стебель", "гребля", "грести",
    "ястреб", "ястребы",
    "сабля", "сабли",
    "скипидар", "педагог", "педагогика",
    "страхование", "страховка", "перестраховка",
    "ребенок", "ребёнок", "ребята",
    "оскорбление", "оскорблять", "оскорбил",
    "влюблен", "влюбленный", "влюблена"
}

# Перечень корней и слов оскорблений
ALL_INSULT_WORDS = (
    r'(?:дебил\w*|даун\w*|дура[кч]?\w*|урод\w*|чмо\w*|чмошник\w*|чмоня|петух\w*|'
    r'лошара|лошок|лох\w*|тупо[йея]|идиот\w*|клоун\w*|ничтожеств\w*|дебилка|дура|придурок|тормоз|'
    r'сучар\w*|гнида\w*|шалав\w*|паскуд\w*|шлюх\w*|тварь\w*|мразь\w*|гной\w*|биомусор|'
    r'пид[ао]р\w*|педик\w*|пидорас\w*|пидарас\w*|г[ао]ндон\w*|хуесос\w*|долбо[её]б\w*|'
    r'у[её]бищ\w*|мудил\w*|мудак\w*|еблан\w*|ёблан\w*)'
)

# 1. Высказывания о себе / самоирония / самокритика (НЕ является оскорблением участников!)
SELF_DIRECTED_RE = re.compile(
    r'(?:'
    r'\b(?:я|мне|меня|мной|мною|себя|сам|сама)\s+(?:[\w\s]{0,25}\s+)?' + ALL_INSULT_WORDS + r'\b'
    r'|'
    r'\b' + ALL_INSULT_WORDS + r'\s+(?:[\w\s]{0,15}\s+)?(?:я|мне|меня|мной|мною)\b'
    r'|'
    r'\b(?:не\s+надо\s+меня|не\s+считай(?:те)?\s+меня|не\s+называй(?:те)?\s+меня|не\s+делай(?:те)?\s+из\s+меня|считаю\s+себя|чувствую\s+себя|не\s+презирай(?:те)?\s+меня)\b'
    r'|'
    r'\b(?:почему\s+я|потому\s+что\s+я|если\s+я|ну\s+я\s+и|вот\s+я|какой\s+я|какая\s+я|походу\s+я|наверно[е]?\s+я)\s+(?:[\w\s]{0,15}\s+)?' + ALL_INSULT_WORDS + r'\b'
    r')',
    re.IGNORECASE
)

# 2. Отрицание оскорбления (НЕ оскорбление)
NEGATION_RE = re.compile(
    r'\b(?:не|нет|ничуть\s+не|вовсе\s+не|ни\s+разу\s+не|никто\s+не|никого\s+не)\s+' + ALL_INSULT_WORDS + r'\b',
    re.IGNORECASE
)

# 3. Агрессивные повелительные атаки (всегда оскорбление)
IMPERATIVE_ATTACKS = [
    r'\b(?:пошел|пошёл|иди|пшел|вали)\s+(?:на\s*хуй|в\s*пизду|в\s*жопу)\b',
    r'\b(?:рот\s*закрой|закрой\s*пасть|ебало\s*завали|завали\s*ебало)\b',
    r'\b(?:соси\s+хуй|соси\s+член|отсоси|отсоси\s+хуй)\b',
    r'\bмать\s+(?:твою|ебал|жива|в\s*канаве)\b',
]

# 4. Адресованные оскорбления (обращенные к другому участнику)
DIRECTED_INSULT_RE = re.compile(
    r'(?:'
    r'\b(?:ты|вы|тебя|тебе|тобой|вас|вам|вами|он|она|чел|чувак|этот|тот|слышь|эй)\s+(?:[\w\s]{0,20}\s+)?' + ALL_INSULT_WORDS + r'\b'
    r'|'
    r'\b' + ALL_INSULT_WORDS + r'\s+(?:[\w\s]{0,10}\s+)?(?:ты|вы)\b'
    r'|'
    r'@\w+\s+(?:[\w\s]{0,10}\s+)?' + ALL_INSULT_WORDS + r'\b'
    r'|'
    r'\b' + ALL_INSULT_WORDS + r'\s+(?:[\w\s]{0,10}\s+)?@\w+'
    r')',
    re.IGNORECASE
)

# 5. Тяжелые ругательства (если не относятся к себе и не отрицаются)
HEAVY_SLURS_RE = re.compile(
    r'\b(?:шлюх\w*|шалав\w*|паскуд\w*|гнида\w*|мразь\w*|биомусор|пидорас\w*|пидарас\w*|хуесос\w*)\b',
    re.IGNORECASE
)


def check_insult(text: str) -> Tuple[bool, Optional[str]]:
    """
    Интеллектуальная контекстная проверка на оскорбления участников.
    Отличает оскорбление собеседника от высказываний о себе / самокритики (например, 'я дебил')
    и отрицаний ('ты не дебил').
    """
    if not text:
        return False, None

    # 1. Повелительные грубые атаки
    for pat in IMPERATIVE_ATTACKS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return True, m.group(0).strip()

    # 2. Прямые оскорбления, направленные на другого человека ('ты дебил', 'чел ты дурак')
    for m in DIRECTED_INSULT_RE.finditer(text):
        snippet = text[max(0, m.start() - 10):m.end()]
        if not NEGATION_RE.search(snippet):
            return True, m.group(0).strip()

    # 3. Тяжелые ругательства (если не относятся к себе и не отрицаются)
    for m in HEAVY_SLURS_RE.finditer(text):
        snippet = text[max(0, m.start() - 25):min(len(text), m.end() + 25)]
        if not SELF_DIRECTED_RE.search(snippet) and not NEGATION_RE.search(snippet):
            return True, m.group(0).strip()

    # 4. Общие слова обзывательств (дебил, даун, дурак, урод, чмо, лох)
    for m in re.finditer(r'\b' + ALL_INSULT_WORDS + r'\b', text, re.IGNORECASE):
        matched_str = m.group(0).strip()
        if matched_str.lower() in WHITELIST_WORDS:
            continue
        snippet = text[max(0, m.start() - 30):min(len(text), m.end() + 30)]
        # Если относится к себе ('я дебил', 'не надо меня презирать я дебил') -> пропускаем
        if SELF_DIRECTED_RE.search(snippet):
            continue
        # Если отрицание ('не дебил', 'не дурак') -> пропускаем
        if NEGATION_RE.search(snippet):
            continue
        return True, matched_str

    return False, None


# Полный перечень регулярных выражений для мата (-1 очко)
MAT_PATTERNS = [
    # Корень хуй (хуй, хуйня, хуевый, охуеть, нахуй, похуй, дохуя, хули и др.)
    r"\b(ху[йиеёяю]|ху[её]в|ху[её]н|ху[её]к|ху[её]п|ху[её]р|нах[уеё]|пох[уеё]|доху[яе]|ниху[яе]|хули|хуле|хуищ|хуйло|хуеплет|хуеплёт|отхуя|захуя|вхуя|прихуя|оху[ееёи]|аху[ееёи])\w*\b",
    
    # Корень пизд (пизда, пиздец, пиздос, пиздишь, спиздил, распиздяй и др.)
    r"\b(пизд|пизда|пиздец|пиздос|пизди|пиздел|спизд|впизд|распизд|отпизд|допизд|припизд|пиздюк|пиздеж|пиздёж)\w*\b",
    
    # Корень еб / ёб (ебать, ебет, ёбаный, заебал, въебал, доебал, наебал, проебал, ебучий и др.)
    r"\b([её]б[аеёиоуы]|въ[её]б|выеб|выёб|за[её]б|до[её]б|на[её]б|об[её]б|от[её]б|пере[её]б|подъ[её]б|при[её]б|про[её]б|разъ[её]б|с[ъеё]б|у[её]б|ебуч|ебл[оа]|ебальн|ебнут|ёбнут)\w*\b",
    
    # Корень бля (бля, блять, блядь, блядина, блядство, бляха)
    r"\b(бл[яея]д|бля|бляха|блядств|блядин|побляд|блять)\w*\b",
    
    # Корень сука
    r"\b(сук[аеиоу]|суч[аеиоу]р|сучь|сучк)\w*\b",
    
    # Дополнительные матерные и грубые корни
    r"\bманд[аеуоы]\w*\b",
    r"\bзалуп\w*\b",
    r"\bдроч\w*\b",
    r"\bподроч\w*\b",
    r"\bелд[аеу]\w*\b",
]


def transliterate_and_normalize(text: str) -> str:
    """
    Приведение текста к нижнему регистру, замена транслита (ya -> я),
    латиницы и leetspeak символов (@, 0, 1, 3, 4, 6) на русскую кириллицу.
    """
    if not text:
        return ""

    lowered = text.lower()

    # 1. Двухбуквенные сочетания транслита
    for bigram, cyr in TRANSLIT_BIGRAMS.items():
        lowered = lowered.replace(bigram, cyr)

    # 2. Одиночные символы
    chars = []
    for char in lowered:
        chars.append(LEETSPEAK_MAP.get(char, char))
    converted = "".join(chars)

    # 3. Схлопывание повторяющихся одинаковых букв (например: "сууууука" -> "сука", "блллля" -> "бля")
    compressed = re.sub(r'(.)\1{2,}', r'\1', converted)
    return compressed


def remove_spacing_and_symbols_tricks(text: str) -> str:
    """
    Удаляет знаки препинания внутри слов (б.л.я., б/л/я, п*и*з*д*а)
    и склеивает последовательности из одиночных букв (б            л               я.).
    Не склеивает обычные слова нормального предложения (например, 'хлеб я люблю').
    """
    if not text:
        return ""

    # 1. Удаляем любые знаки препинания и символы (включая _, ., -, *, /, |, + и т.д.)
    # находящиеся непосредственно между буквами/цифрами:
    # "б.л.я." -> "бля.", "б_л_я" -> "бля", "б/л/я" -> "бля", "п*и*з*д*а" -> "пизда"
    no_symbols = re.sub(r'(?<=[а-яёa-z0-9])(?:[^\w\s]|_)+(?=[а-яёa-z0-9])', '', text)

    # 2. Склеиваем слова, написанные через пробелы одиночными буквами:
    # "б            л               я." -> "бля."
    # "х   у   й" -> "хуй"
    # "п  и  з  д  е  ц" -> "пиздец"
    words = no_symbols.split()
    reconstructed: List[str] = []
    single_letters_buffer: List[str] = []

    for word in words:
        clean_word = re.sub(r'[^а-яёa-z0-9]', '', word)
        if len(clean_word) == 1:
            single_letters_buffer.append(clean_word)
        elif len(clean_word) == 0:
            # Токен состоит только из символов разделителей (например, "/", "|", "+", "*", "-")
            # Пропускаем его, он не должен разрывать цепочку одиночных букв
            continue
        else:
            if len(single_letters_buffer) >= 3:
                reconstructed.append("".join(single_letters_buffer))
            else:
                reconstructed.extend(single_letters_buffer)
            single_letters_buffer = []
            reconstructed.append(word)

    if len(single_letters_buffer) >= 3:
        reconstructed.append("".join(single_letters_buffer))
    elif single_letters_buffer:
        reconstructed.extend(single_letters_buffer)

    return " ".join(reconstructed)


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

    # Вариант 1: Текст после нормализации транслита и leetspeak
    norm = transliterate_and_normalize(text)

    # Вариант 2: Текст после раскрытия маскировочных знаков препинания и межбуквенных пробелов
    condensed = remove_spacing_and_symbols_tricks(norm)

    # Вариант 3: Снятие разделителей до транслитерации (например, b.l.y.a -> blya -> бля)
    trans_condensed = transliterate_and_normalize(remove_spacing_and_symbols_tricks(text))

    variants = [condensed, trans_condensed, norm]

    # 1. Проверка на оскорбления (с учетом контекста ситуации и самокритики)
    for variant in variants:
        is_insult, insult_word = check_insult(variant)
        if is_insult:
            return ViolationType.INSULT, insult_word

    # 2. Проверка на мат
    for variant in variants:
        for pattern in MAT_PATTERNS:
            match = re.search(pattern, variant, re.IGNORECASE)
            if match:
                word = match.group(0).strip()
                if word not in WHITELIST_WORDS:
                    return ViolationType.MAT, word

    return ViolationType.NONE, None

"""
Детектор спама и флуда сообщений в чате.
"""

import time
import re
from typing import Dict, Tuple, List
from collections import defaultdict


class SpamDetector:
    def __init__(
        self,
        max_messages_in_window: int = 4,
        window_seconds: float = 4.0,
        repeat_threshold: int = 3,
        repeat_window_seconds: float = 20.0,
    ):
        self.max_messages = max_messages_in_window
        self.window_seconds = window_seconds
        self.repeat_threshold = repeat_threshold
        self.repeat_window = repeat_window_seconds

        # История сообщений: (chat_id, user_id) -> список таймстемпов float
        self._message_times: Dict[Tuple[int, int], List[float]] = defaultdict(list)
        # Последние тексты сообщений: (chat_id, user_id) -> список кортежей (text, timestamp)
        self._recent_texts: Dict[Tuple[int, int], List[Tuple[str, float]]] = defaultdict(list)

    def is_spam(self, chat_id: int, user_id: int, text: str) -> Tuple[bool, str]:
        """
        Проверяет сообщение на спам/флуд:
        1. Слишком частая отправка сообщений (флуд)
        2. Повторяющиеся одинаковые сообщения
        3. Подозрительные ссылки на спам-каналы / скам
        4. Гигантские бессмысленные сообщения (засорение чата)
        """
        now = time.time()
        key = (chat_id, user_id)

        # 1. Проверка на подозрительные ссылки на сторонние каналы/скам
        if text:
            scam_invite_pattern = r"(https?://)?(t\.me/\+|t\.me/joinchat/|telegram\.me/)"
            if re.search(scam_invite_pattern, text, re.IGNORECASE):
                return True, "рекламная ссылка/приглашение"

            # 2. Проверка на намеренное засорение чата длинным бессмысленным текстом (более 1500 символов)
            if len(text) > 1500:
                return True, "слишком длинное сообщение (засорение чата)"

        # 3. Проверка на частоту сообщений (флуд)
        times = self._message_times[key]
        # Очищаем устаревшие записи
        cutoff = now - self.window_seconds
        self._message_times[key] = [t for t in times if t > cutoff]
        self._message_times[key].append(now)

        if len(self._message_times[key]) > self.max_messages:
            return True, f"флуд (более {self.max_messages} сообщений за {int(self.window_seconds)} сек)"

        # 4. Проверка на повторы одинаковых сообщений
        if text and len(text.strip()) > 1:
            clean_text = text.strip().lower()
            recent = self._recent_texts[key]
            # Очищаем устаревшие
            repeat_cutoff = now - self.repeat_window
            self._recent_texts[key] = [(txt, t) for (txt, t) in recent if t > repeat_cutoff]
            self._recent_texts[key].append((clean_text, now))

            # Считаем количество таких же сообщений за окно
            repeats = sum(1 for (txt, _) in self._recent_texts[key] if txt == clean_text)
            if repeats >= self.repeat_threshold:
                return True, f"повтор одного и того же сообщения {repeats} раза подряд"

        return False, ""

    def reset_user(self, chat_id: int, user_id: int) -> None:
        """Сброс истории для конкретного пользователя."""
        self._message_times.pop((chat_id, user_id), None)
        self._recent_texts.pop((chat_id, user_id), None)


spam_detector = SpamDetector()

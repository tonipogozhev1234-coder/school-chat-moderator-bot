"""
Модуль работы с базой данных SQLite для хранения очков участников и истории нарушений.
"""

import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from contextlib import contextmanager

from config import config


class Database:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.db_path

    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер соединения SQLite с гарантированным закрытием."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db_sync(self) -> None:
        """Синхронная инициализация схемы БД."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Таблица пользователей и очков
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    points INTEGER DEFAULT 10,
                    warnings_count INTEGER DEFAULT 0,
                    mutes_count INTEGER DEFAULT 0,
                    clean_messages_count INTEGER DEFAULT 0,
                    muted_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            # Миграция: добавляем muted_until если таблица уже существовала
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN muted_until TEXT")
            except sqlite3.OperationalError:
                pass  # Колонка уже существует

            # Миграция: добавляем clean_messages_count (счетчик сообщений без мата)
            try:
                cursor.execute("ALTER TABLE users ADD COLUMN clean_messages_count INTEGER DEFAULT 0")
            except sqlite3.OperationalError:
                pass
            # Таблица журнала нарушений
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS violations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    violation_type TEXT NOT NULL,
                    details TEXT,
                    points_deducted INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    async def init_db(self) -> None:
        """Асинхронный вызов инициализации БД."""
        await asyncio.to_thread(self._init_db_sync)

    def _get_or_create_user_sync(
        self, chat_id: int, user_id: int, username: Optional[str], first_name: Optional[str], default_points: int = 10
    ) -> Dict[str, Any]:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM users WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            row = cursor.fetchone()
            if row is not None:
                # Обновляем имя и юзернейм если они изменились
                cursor.execute(
                    """UPDATE users 
                       SET username = ?, first_name = ?, updated_at = ? 
                       WHERE chat_id = ? AND user_id = ?""",
                    (username, first_name, now_str, chat_id, user_id),
                )
                conn.commit()
                cursor.execute(
                    "SELECT * FROM users WHERE chat_id = ? AND user_id = ?",
                    (chat_id, user_id),
                )
                return dict(cursor.fetchone())

            # Создаем нового участника со стартовыми очками
            cursor.execute(
                """INSERT INTO users 
                   (chat_id, user_id, username, first_name, points, warnings_count, mutes_count, clean_messages_count, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 0, 0, 0, ?, ?)""",
                (chat_id, user_id, username, first_name, default_points, now_str, now_str),
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM users WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            return dict(cursor.fetchone())

    async def get_or_create_user(
        self, chat_id: int, user_id: int, username: Optional[str] = None, first_name: Optional[str] = None
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(
            self._get_or_create_user_sync,
            chat_id,
            user_id,
            username,
            first_name,
            config.initial_points,
        )

    def _get_user_by_username_sync(self, username_or_id: str) -> Optional[Dict[str, Any]]:
        clean_input = username_or_id.lstrip("@").strip().lower()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Пробуем найти по юзернейму или по числовому ID
            if clean_input.isdigit():
                cursor.execute(
                    """SELECT * FROM users 
                       WHERE user_id = ? OR LOWER(username) = ? 
                       ORDER BY updated_at DESC LIMIT 1""",
                    (int(clean_input), clean_input),
                )
            else:
                cursor.execute(
                    """SELECT * FROM users 
                       WHERE LOWER(username) = ? 
                       ORDER BY updated_at DESC LIMIT 1""",
                    (clean_input,),
                )
            row = cursor.fetchone()
            return dict(row) if row else None

    async def get_user_by_username(self, username_or_id: str) -> Optional[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_user_by_username_sync, username_or_id)

    def _deduct_points_sync(self, chat_id: int, user_id: int, amount: int) -> int:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users 
                   SET points = points - ?, warnings_count = warnings_count + 1, updated_at = ? 
                   WHERE chat_id = ? AND user_id = ?""",
                (amount, now_str, chat_id, user_id),
            )
            conn.commit()
            cursor.execute(
                "SELECT points FROM users WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            row = cursor.fetchone()
            return row["points"] if row else 0

    async def deduct_points(self, chat_id: int, user_id: int, amount: int = 1) -> int:
        return await asyncio.to_thread(self._deduct_points_sync, chat_id, user_id, amount)

    def _add_points_sync(self, chat_id: int, user_id: int, amount: int) -> int:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users 
                   SET points = points + ?, updated_at = ? 
                   WHERE chat_id = ? AND user_id = ?""",
                (amount, now_str, chat_id, user_id),
            )
            conn.commit()
            cursor.execute(
                "SELECT points FROM users WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            row = cursor.fetchone()
            return row["points"] if row else 0

    async def add_points(self, chat_id: int, user_id: int, amount: int) -> int:
        return await asyncio.to_thread(self._add_points_sync, chat_id, user_id, amount)

    def _set_points_sync(self, chat_id: int, user_id: int, points: int) -> int:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users 
                   SET points = ?, updated_at = ? 
                   WHERE chat_id = ? AND user_id = ?""",
                (points, now_str, chat_id, user_id),
            )
            conn.commit()
            return points

    async def set_points(self, chat_id: int, user_id: int, points: int) -> int:
        return await asyncio.to_thread(self._set_points_sync, chat_id, user_id, points)

    def _reset_points_sync(self, chat_id: int, user_id: int, default_points: int = 10) -> int:
        return self._set_points_sync(chat_id, user_id, default_points)

    async def reset_points(self, chat_id: int, user_id: int) -> int:
        return await asyncio.to_thread(self._reset_points_sync, chat_id, user_id, config.initial_points)

    def _record_clean_message_sync(
        self, chat_id: int, user_id: int, reward_step: int = 25, reward_points: int = 1
    ) -> Tuple[bool, int, int]:
        """
        Увеличивает счетчик чистых сообщений на 1.
        Если достигнуто reward_step (25), начисляет reward_points (+1 балл), сбрасывает счетчик.
        Возвращает: (is_rewarded: bool, new_points: int, current_clean_count: int)
        """
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users 
                   SET clean_messages_count = COALESCE(clean_messages_count, 0) + 1, updated_at = ? 
                   WHERE chat_id = ? AND user_id = ?""",
                (now_str, chat_id, user_id),
            )
            conn.commit()

            cursor.execute(
                "SELECT points, clean_messages_count FROM users WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            row = cursor.fetchone()
            if not row:
                return False, config.initial_points, 0

            clean_count = row["clean_messages_count"]
            current_points = row["points"]

            if clean_count >= reward_step:
                new_points = current_points + reward_points
                rem_clean = clean_count - reward_step
                cursor.execute(
                    """UPDATE users 
                       SET points = ?, clean_messages_count = ?, updated_at = ? 
                       WHERE chat_id = ? AND user_id = ?""",
                    (new_points, rem_clean, now_str, chat_id, user_id),
                )
                conn.commit()
                return True, new_points, rem_clean

            return False, current_points, clean_count

    async def record_clean_message(
        self, chat_id: int, user_id: int, reward_step: int = 25, reward_points: int = 1
    ) -> Tuple[bool, int, int]:
        return await asyncio.to_thread(
            self._record_clean_message_sync, chat_id, user_id, reward_step, reward_points
        )

    def _reset_clean_messages_sync(self, chat_id: int, user_id: int) -> None:
        """Сбрасывает серию чистых сообщений при нарушении."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET clean_messages_count = 0 WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            conn.commit()

    async def reset_clean_messages(self, chat_id: int, user_id: int) -> None:
        await asyncio.to_thread(self._reset_clean_messages_sync, chat_id, user_id)

    def _record_violation_sync(
        self, chat_id: int, user_id: int, violation_type: str, details: str, points_deducted: int
    ) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO violations 
                   (chat_id, user_id, violation_type, details, points_deducted, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chat_id, user_id, violation_type, details, points_deducted, now_str),
            )
            conn.commit()

    async def record_violation(
        self, chat_id: int, user_id: int, violation_type: str, details: str = "", points_deducted: int = 0
    ) -> None:
        await asyncio.to_thread(
            self._record_violation_sync, chat_id, user_id, violation_type, details, points_deducted
        )

    def _record_mute_sync(self, chat_id: int, user_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET mutes_count = mutes_count + 1 WHERE chat_id = ? AND user_id = ?",
                (chat_id, user_id),
            )
            conn.commit()

    async def record_mute(self, chat_id: int, user_id: int) -> None:
        await asyncio.to_thread(self._record_mute_sync, chat_id, user_id)

    def _set_user_mute_sync(self, chat_id: int, user_id: int, duration_hours: int) -> str:
        until_dt = datetime.now(timezone.utc) + timedelta(hours=duration_hours)
        until_str = until_dt.isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE users 
                   SET muted_until = ?, mutes_count = mutes_count + 1 
                   WHERE chat_id = ? AND user_id = ?""",
                (until_str, chat_id, user_id),
            )
            conn.commit()
        return until_str

    async def set_user_mute(self, chat_id: int, user_id: int, duration_hours: int) -> str:
        return await asyncio.to_thread(self._set_user_mute_sync, chat_id, user_id, duration_hours)

    def _is_user_muted_sync(self, chat_id: int, user_id: int) -> Tuple[bool, int]:
        """Возвращает (в_муте_ли, оставшиеся_секунды)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT muted_until FROM users WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            row = cursor.fetchone()
            if not row or not row["muted_until"]:
                return False, 0

            try:
                until_dt = datetime.fromisoformat(row["muted_until"])
                now_dt = datetime.now(timezone.utc)
                remaining = int((until_dt - now_dt).total_seconds())
                if remaining > 0:
                    return True, remaining
                else:
                    # Мут истёк — сбрасываем
                    cursor.execute("UPDATE users SET muted_until = NULL WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
                    conn.commit()
                    return False, 0
            except Exception:
                return False, 0

    async def is_user_muted(self, chat_id: int, user_id: int) -> Tuple[bool, int]:
        return await asyncio.to_thread(self._is_user_muted_sync, chat_id, user_id)

    def _remove_user_mute_sync(self, chat_id: int, user_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET muted_until = NULL WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            conn.commit()

    async def remove_user_mute(self, chat_id: int, user_id: int) -> None:
        await asyncio.to_thread(self._remove_user_mute_sync, chat_id, user_id)

    def _get_chat_leaderboard_sync(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT user_id, username, first_name, points, warnings_count, mutes_count
                   FROM users
                   WHERE chat_id = ?
                   ORDER BY points DESC, warnings_count ASC
                   LIMIT ?""",
                (chat_id, limit),
            )
            return [dict(r) for r in cursor.fetchall()]

    async def get_chat_leaderboard(self, chat_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self._get_chat_leaderboard_sync, chat_id, limit)


db = Database()


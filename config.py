"""
Конфигурация бота и загрузка переменных окружения.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

# Путь к директории проекта и файлу .env
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

def _load_env_file(filepath: Path) -> None:
    """Загрузка переменных из .env без внешних зависимостей (fallback)."""
    if not filepath.exists():
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip("'\"")
            if key not in os.environ:
                os.environ[key] = val

# Пытаемся загрузить dotenv, если доступен, иначе наш парсер
try:
    from dotenv import load_dotenv
    load_dotenv(ENV_PATH)
except ImportError:
    _load_env_file(ENV_PATH)


@dataclass
class Config:
    bot_token: str = field(
        default_factory=lambda: (
            os.getenv("BOT_TOKEN")
            or os.getenv("TOKEN")
            or os.getenv("TELEGRAM_BOT_TOKEN")
            or ""
        ).strip()
    )
    initial_points: int = field(
        default_factory=lambda: int(os.getenv("INITIAL_POINTS", "10"))
    )
    mat_penalty: int = field(
        default_factory=lambda: int(os.getenv("MAT_PENALTY", "1"))
    )
    spam_penalty: int = field(
        default_factory=lambda: int(os.getenv("SPAM_PENALTY", "1"))
    )
    insult_mute_hours: int = field(
        default_factory=lambda: int(os.getenv("INSULT_MUTE_HOURS", "2"))
    )
    zero_points_mute_hours: int = field(
        default_factory=lambda: int(os.getenv("ZERO_POINTS_MUTE_HOURS", "3"))
    )
    delete_violating_messages: bool = field(
        default_factory=lambda: os.getenv("DELETE_VIOLATING_MESSAGES", "True").lower() in ("true", "1", "yes")
    )
    admin_ids: List[int] = field(default_factory=list)
    db_path: Path = field(default_factory=lambda: BASE_DIR / "chat_bot.db")

    def __post_init__(self):
        raw_admins = os.getenv("ADMIN_IDS", "").strip()
        if raw_admins:
            self.admin_ids = [
                int(x.strip()) for x in raw_admins.split(",") if x.strip().isdigit()
            ]


config = Config()

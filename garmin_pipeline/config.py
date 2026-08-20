"""Конфигурация пайплайна: пути, учётные данные, параметры библиотеки.

Два источника настроек, в порядке приоритета:
1. `data/config.json` - пишется веб-формой настройки/Telegram-ботом
   (дистрибутив для конечного пользователя, см. webapp/bot.py).
2. `.env` в корне проекта - для CLI-разработки, остаётся полностью рабочим
   способом настройки, если config.json не создан.

Пути (library_root/cache_db_path/token_store) читаются только из `.env` -
они не предполагаются меняющимися через веб-форму на лету.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


def _detect_project_root() -> Path:
    """В собранном PyInstaller-`.exe` (`sys.frozen`) `__file__` этого модуля
    указывает внутрь `_internal` (там, где PyInstaller распаковывает пакеты),
    а не туда, где лежит сам `.exe`. Если резолвить пути от `__file__` как в
    режиме разработки, `data/config.json` пишется внутрь `_internal` и
    стирается при каждой пересборке `.exe` (`_internal` перегенерируется
    целиком). Поэтому во frozen-сборке берём папку `sys.executable` - она не
    трогается пересборкой и переживает обновления версии внутри той же папки.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


PROJECT_ROOT = _detect_project_root()
load_dotenv(PROJECT_ROOT / ".env")


def _resolve(path_str: str) -> Path:
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path


def config_json_path() -> Path:
    """Путь к data/config.json - как остальные пути, переопределим через env

    (CONFIG_JSON_PATH), чтобы тесты могли изолироваться от реального data/."""
    return _resolve(os.getenv("CONFIG_JSON_PATH", "./data/config.json"))


def _read_config_json() -> dict[str, Any]:
    path = config_json_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


@dataclass(frozen=True)
class Settings:
    email: str | None
    password: str | None
    token_store: Path
    library_root: Path
    cache_db_path: Path
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_user_id: str | None = None

    def is_llm_configured(self) -> bool:
        return bool(self.llm_api_key)

    def is_telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)

    @property
    def daily_dir(self) -> Path:
        return self.library_root / "daily"

    @property
    def weekly_dir(self) -> Path:
        return self.library_root / "weekly"

    @property
    def monthly_dir(self) -> Path:
        return self.library_root / "monthly"

    @property
    def activities_dir(self) -> Path:
        return self.library_root / "activities"

    @property
    def range_dir(self) -> Path:
        """Отчёты за произвольный период (см. collectors/range_report.py) -

        не привязаны к ISO-неделе, создаются по запросу с явными датами."""
        return self.library_root / "range"

    @property
    def index_path(self) -> Path:
        return self.library_root / "_index.md"

    @property
    def context_path(self) -> Path:
        """Единый агрегированный снапшот (см. collectors/context.py) - один

        файл, перезаписывается при каждом запуске (не история, а 'текущая
        картина сейчас')."""
        return self.library_root / "context.md"

    def ensure_dirs(self) -> None:
        for d in (self.daily_dir, self.weekly_dir, self.monthly_dir, self.activities_dir, self.range_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.token_store.mkdir(parents=True, exist_ok=True)
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    overlay = _read_config_json()

    def pick(env_key: str, json_key: str, default: str | None = None) -> str | None:
        value = overlay.get(json_key)
        if value:
            return value
        return os.getenv(env_key) or default

    return Settings(
        email=pick("GARMIN_EMAIL", "garmin_email"),
        password=pick("GARMIN_PASSWORD", "garmin_password"),
        token_store=_resolve(os.getenv("GARMIN_TOKENSTORE", "./data/tokens")),
        library_root=_resolve(os.getenv("LIBRARY_ROOT", "./data/library")),
        cache_db_path=_resolve(os.getenv("CACHE_DB_PATH", "./data/cache.sqlite3")),
        # Дефолт - Cloud.ru Evolution Foundation Models: OpenAI-совместимый
        # API, доступный из РФ без VPN (в отличие от ушедшего из РФ OpenRouter).
        # См. https://cloud.ru/docs/foundation-models/ug/topics/quickstart
        llm_base_url=pick("LLM_BASE_URL", "llm_base_url", "https://foundation-models.api.cloud.ru/v1"),
        llm_api_key=pick("LLM_API_KEY", "llm_api_key"),
        llm_model=pick("LLM_MODEL", "llm_model", "deepseek-ai/DeepSeek-V3.1"),
        telegram_bot_token=pick("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        telegram_allowed_user_id=pick("TELEGRAM_ALLOWED_USER_ID", "telegram_allowed_user_id"),
    )


def save_config_json(updates: dict[str, Any]) -> None:
    """Сливает `updates` в data/config.json (создаёт при отсутствии) и

    перезагружает синглтон `settings` в этом модуле. Модули, читающие LLM/
    Telegram-поля через `config.settings.xxx` (обращение к атрибуту в момент
    вызова, а не `from ... import settings` при импорте), увидят новые
    значения без перезапуска процесса - см. llm_client.py/bot.py.
    """
    path = config_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = _read_config_json()
    current.update({k: v for k, v in updates.items() if v not in (None, "")})
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    reload_settings()


def reload_settings() -> Settings:
    global settings
    settings = load_settings()
    return settings


settings = load_settings()

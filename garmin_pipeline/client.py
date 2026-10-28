"""Единая точка входа к данным Garmin Connect.

Два способа доступа (см. config.Settings.garmin_backend):

1. Официальный **Personal API** (`personal_api.PersonalApiClient`) - личный
   ключ из Garmin Connect, без пароля/MFA, только чтение. Используется, если
   задан GARMIN_PERSONAL_API_KEY (backend "auto"/"personal").
2. Неофициальный **python-garminconnect** - логин/пароль (+MFA) один раз, потом
   сохранённые токены в settings.token_store. Нужен для записи (создание
   тренировок, загрузка FIT), training readiness и подходов силовых - всего, чего
   нет в Personal API. В режиме "auto" с ключом он подключается лениво, только
   когда такая операция реально понадобилась.

Остальной код вызывает только get_client() и не знает, какой бэкенд за ним.
"""

from __future__ import annotations

import logging
import sys
from getpass import getpass
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_pipeline import config
from garmin_pipeline.personal_api import PersonalApiClient

logger = logging.getLogger(__name__)


class GarminLoginError(RuntimeError):
    """Не удалось авторизоваться в Garmin Connect."""


def _prompt_mfa() -> str:
    return input("Код двухфакторной аутентификации Garmin: ").strip()


def login_unofficial(interactive: bool = True) -> Garmin:
    """Логин через неофициальный python-garminconnect.

    Сначала пытается восстановить сохранённую сессию из settings.token_store.
    Если токенов нет/просрочены - логинится по email/паролю из .env или
    config.json (или, если interactive=True и их нет, спрашивает в консоли).
    """
    settings = config.settings
    settings.ensure_dirs()
    token_store = str(settings.token_store)

    try:
        client = Garmin()
        client.login(token_store)
        return client
    except (FileNotFoundError, GarminConnectAuthenticationError, GarminConnectConnectionError):
        pass  # нет валидных токенов - логинимся ниже
    except GarminConnectTooManyRequestsError as err:
        raise GarminLoginError(f"Garmin ограничил количество запросов: {err}") from err

    email = settings.email
    password = settings.password

    if not email or not password:
        if not interactive:
            raise GarminLoginError(
                "Нет сохранённой сессии и не заданы GARMIN_EMAIL/GARMIN_PASSWORD в .env. "
                "Запусти `python -m garmin_pipeline.cli login` вручную."
            )
        email = email or input("Garmin email: ").strip()
        password = password or getpass("Garmin password: ")

    try:
        client = Garmin(email=email, password=password, prompt_mfa=_prompt_mfa)
        client.login(token_store)
    except GarminConnectAuthenticationError as err:
        raise GarminLoginError(f"Неверные учётные данные Garmin: {err}") from err
    except GarminConnectTooManyRequestsError as err:
        raise GarminLoginError(f"Garmin ограничил количество запросов: {err}") from err
    except GarminConnectConnectionError as err:
        raise GarminLoginError(f"Не удалось соединиться с Garmin: {err}") from err

    return client


def get_client(interactive: bool = True) -> Any:
    """Возвращает клиент Garmin (Personal API или неофициальный - см. модуль).

    interactive=True разрешает спросить логин/пароль/MFA в консоли (только для
    `cli login` и разового запуска client.main); везде в сервисах - False.
    """
    settings = config.settings
    backend = settings.garmin_backend if settings.garmin_backend in ("auto", "personal", "unofficial") else "auto"
    key = settings.personal_api_key

    if backend == "personal" and not key:
        raise GarminLoginError(
            "GARMIN_BACKEND=personal, но не задан GARMIN_PERSONAL_API_KEY "
            "(создай ключ на странице Personal API Key в Garmin Connect)."
        )

    personal_error: str | None = None
    if backend != "unofficial" and key:
        client = PersonalApiClient(key, fallback_factory=lambda: login_unofficial(interactive=False))
        try:
            client.ensure_token()
            return client
        except GarminConnectAuthenticationError as err:
            personal_error = str(err)
        except GarminConnectTooManyRequestsError as err:
            raise GarminLoginError(f"Garmin ограничил количество запросов: {err}") from err
        except GarminConnectConnectionError as err:
            personal_error = str(err)
        if backend == "personal":
            raise GarminLoginError(personal_error or "Personal API недоступен")
        logger.warning("Personal API недоступен (%s) - пробую вход по логину/паролю", personal_error)

    try:
        return login_unofficial(interactive=interactive)
    except GarminLoginError as err:
        if personal_error:
            raise GarminLoginError(
                f"Personal API: {personal_error} Вход по логину/паролю тоже не удался: {err}"
            ) from err
        raise


def main() -> int:
    """CLI-обёртка: `python -m garmin_pipeline.client` - разовый интерактивный логин
    (логин/пароль, токены сохраняются) - нужен для записи тренировок и т.п."""
    try:
        login_unofficial(interactive=True)
    except GarminLoginError as err:
        print(f"Ошибка логина: {err}", file=sys.stderr)
        return 1
    print(f"Логин успешен. Токены сохранены в: {config.settings.token_store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

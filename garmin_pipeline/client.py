"""Обёртка над python-garminconnect: логин, кэш токенов, единая точка входа.

Первый логин требует email/пароль (и, возможно, код MFA) - после этого
токены сохраняются в settings.token_store и переиспользуются автоматически,
пока Garmin их не отозвал.
"""

from __future__ import annotations

import sys
from getpass import getpass

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from garmin_pipeline.config import settings


class GarminLoginError(RuntimeError):
    """Не удалось авторизоваться в Garmin Connect."""


def _prompt_mfa() -> str:
    return input("Код двухфакторной аутентификации Garmin: ").strip()


def get_client(interactive: bool = True) -> Garmin:
    """Возвращает авторизованный клиент Garmin.

    Сначала пытается восстановить сохранённую сессию из settings.token_store.
    Если токенов нет/просрочены - логинится по email/паролю из .env
    (или, если interactive=True и их нет в .env, спрашивает в консоли).
    """
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


def main() -> int:
    """CLI-обёртка: `python -m garmin_pipeline.client` - разовый интерактивный логин."""
    try:
        get_client(interactive=True)
    except GarminLoginError as err:
        print(f"Ошибка логина: {err}", file=sys.stderr)
        return 1
    print(f"Логин успешен. Токены сохранены в: {settings.token_store}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

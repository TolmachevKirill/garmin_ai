"""Единая точка входа для дистрибутива (Фаза 10 плана).

Поднимает веб-интерфейс (/setup, /dashboard) и, если задан telegram_bot_token
в data/config.json/.env, Telegram-бота - в фоновых потоках одного процесса.
Открывает браузер на нужной странице сразу после старта. Собирается в один
Windows .exe через PyInstaller (см. desktop_app.spec, `pyinstaller desktop_app.spec`).

Ограничение: Telegram-бот стартует один раз при запуске приложения. Если
telegram_bot_token добавлен/изменён через веб-форму настройки уже во время
работы приложения - для подключения бота нужен перезапуск (см. подсказку в
дашборде). Веб-интерфейс и учётные данные Garmin/LLM подхватываются на лету
без перезапуска (см. config.reload_settings, вызывается из save_config_json).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser

import uvicorn

from garmin_pipeline import config
from garmin_pipeline.webapp.app import create_app

HOST = "127.0.0.1"
PORT = int(os.getenv("GARMIN_PIPELINE_PORT", "8765"))
_STARTUP_DELAY_S = 1.5  # даём uvicorn поднять сокет перед открытием браузера
_SYNC_INTERVAL_S = 6 * 3600  # раз в 6 часов, пока приложение открыто


def _fix_windows_console_encoding() -> None:
    """Консоль Windows по умолчанию использует OEM-кодировку (cp866/cp1251),
    из-за чего кириллица в логах превращается в кракозябры. Переключаем
    codepage консоли и потоки stdout/stderr на UTF-8, если это возможно."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _run_web_server() -> None:
    uvicorn.run(create_app(), host=HOST, port=PORT, log_level="info")


def _run_bot_if_configured() -> None:
    if not config.settings.is_telegram_configured():
        logging.info("TELEGRAM_BOT_TOKEN не задан - Telegram-бот не запускается (можно настроить в /setup)")
        return
    from garmin_pipeline.bot import run_bot

    try:
        run_bot(install_signal_handlers=False)
    except Exception:
        logging.exception("Telegram-бот завершился с ошибкой")


def _run_background_sync() -> None:
    """Держит локальный кэш "тёплым", пока открыт GUI-дистрибутив - без этого

    отчёт за произвольный период (/range) при первом заходе за новый день
    придётся собирать вживую из Garmin API вместо мгновенного чтения из
    кэша (см. collectors/sync.py и обоснование в collectors/range_report.py).
    В CLI-дистрибутиве та же роль у Task Scheduler-задачи
    scripts/register_daily_sync_task.ps1 - здесь она не нужна, т.к. exe не
    гарантированно запущен по расписанию, зато обычно долго открыт.
    """
    from garmin_pipeline.client import get_client
    from garmin_pipeline.collectors.sync import sync_recent_days

    while True:
        if config.settings.email:
            try:
                sync_recent_days(get_client(interactive=False), days=3)
            except Exception:
                logging.exception("Фоновая синхронизация кэша завершилась с ошибкой")
        time.sleep(_SYNC_INTERVAL_S)


def main() -> None:
    _fix_windows_console_encoding()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    threading.Thread(target=_run_web_server, name="webapp", daemon=True).start()
    threading.Thread(target=_run_bot_if_configured, name="telegram-bot", daemon=True).start()
    threading.Thread(target=_run_background_sync, name="cache-sync", daemon=True).start()

    time.sleep(_STARTUP_DELAY_S)
    target_path = "/dashboard" if config.settings.email else "/setup"
    url = f"http://{HOST}:{PORT}{target_path}"
    logging.info("Открываю браузер: %s", url)
    try:
        webbrowser.open(url)
    except Exception:
        logging.exception("Не удалось автоматически открыть браузер - открой %s вручную", url)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logging.info("Остановка по Ctrl+C")


if __name__ == "__main__":
    main()

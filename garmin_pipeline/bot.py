"""Telegram-бот - мобильный доступ к пайплайну без веб-интерфейса.

Работает в polling-режиме (без webhook - не нужен публичный IP/домен, что
удобно для сценария "запустил exe на своём ПК дома, пишешь боту с телефона").
Команды транслируются в вызовы существующих коллекторов (collect_daily,
build_weekly_report, search_activities); свободный текст уходит в
llm_client.ask(...) вместе со свежим context-снапшотом - бот может отвечать
на произвольные вопросы про здоровье/тренировки, а не только на команды.

Требует BYOK Telegram-токен (создаётся через @BotFather в самом Telegram) -
задаётся через веб-форму настройки (data/config.json) или .env
(TELEGRAM_BOT_TOKEN). Без токена run_bot()/build_application() бросают
RuntimeError - это ожидаемо для пользователя, который ещё не прошёл setup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as date_cls

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from garmin_pipeline import config, llm_client
from garmin_pipeline.client import get_client
from garmin_pipeline.collectors.activity import search_activities
from garmin_pipeline.collectors.context import build_context
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.weekly import build_weekly_report
from garmin_pipeline.formatting import render_activity_md, render_context_md, render_daily_md, render_weekly_md

logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 3500  # лимит Telegram - 4096 символов, оставляем запас


def _is_authorized(update: Update) -> bool:
    allowed = config.settings.telegram_allowed_user_id
    if not allowed or not update.effective_user:
        return not allowed
    return str(update.effective_user.id) == str(allowed)


async def _guard(update: Update) -> bool:
    if not _is_authorized(update):
        await update.message.reply_text(
            "Доступ ограничен - этот бот настроен для одного пользователя (telegram_allowed_user_id)."
        )
        return False
    return True


def _chunks(text: str, size: int = MAX_MESSAGE_LEN) -> list[str]:
    if not text:
        return [""]
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _reply_long(update: Update, text: str) -> None:
    for chunk in _chunks(text):
        await update.message.reply_text(chunk)


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.message.reply_text(
        "Привет! Я читаю твои данные из Garmin Connect. Команды:\n"
        "/today - дайджест за сегодня\n"
        "/week - недельный отчёт\n"
        "/activity <запрос> - тренировка по описанию (например: /activity бег), "
        "без запроса - последняя тренировка\n\n"
        "Можно просто написать вопрос про своё здоровье/тренировки - отвечу с "
        "помощью LLM (если он настроен в /setup)."
    )


async def cmd_today(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.message.reply_text("Собираю дневной дайджест...")
    client = get_client(interactive=False)
    bundle = await asyncio.to_thread(collect_daily, client, date_cls.today().isoformat())
    await _reply_long(update, render_daily_md(bundle.as_render_dict()))


async def cmd_week(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    await update.message.reply_text("Собираю недельный отчёт...")
    client = get_client(interactive=False)
    week = await asyncio.to_thread(build_weekly_report, client)
    await _reply_long(update, render_weekly_md(week))


async def cmd_activity(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    query = " ".join(ctx.args) if ctx.args else None
    await update.message.reply_text("Ищу тренировку...")
    client = get_client(interactive=False)
    candidates = await asyncio.to_thread(
        search_activities, client, name_contains=query, latest=not query, limit=5
    )
    if not candidates:
        await update.message.reply_text("Ничего не нашёл по этому запросу.")
        return
    if len(candidates) > 1:
        lines = [f"- {c['date']}: {c.get('name') or c.get('type')}" for c in candidates[:5]]
        await update.message.reply_text(
            "Нашлось несколько тренировок, уточни запрос:\n" + "\n".join(lines)
        )
        return
    await _reply_long(update, render_activity_md(candidates[0]))


async def handle_free_text(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not config.settings.is_llm_configured():
        await update.message.reply_text(
            "LLM не настроен - задай llm_api_key через веб-форму настройки (/setup) или .env, "
            "либо используй команды /today, /week, /activity."
        )
        return

    await update.message.reply_text("Думаю...")
    client = get_client(interactive=False)
    context_data = await asyncio.to_thread(build_context, client, days=14)
    context_md = render_context_md(context_data)
    try:
        answer = await asyncio.to_thread(
            llm_client.ask, llm_client.DEFAULT_SYSTEM_PROMPT, context_md, update.message.text
        )
    except Exception as exc:  # noqa: BLE001 - хотим показать пользователю любую ошибку LLM как есть
        await update.message.reply_text(f"Ошибка при обращении к LLM: {exc}")
        return
    await _reply_long(update, answer)


def build_application() -> Application:
    token = config.settings.telegram_bot_token
    if not token:
        raise RuntimeError(
            "Telegram-бот не настроен - задай telegram_bot_token через data/config.json "
            "(веб-форма /setup) или переменную окружения TELEGRAM_BOT_TOKEN "
            "(токен создаётся в Telegram через @BotFather)."
        )
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("activity", cmd_activity))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_free_text))
    return app


def run_bot(*, install_signal_handlers: bool = True) -> None:
    """Запускает бота в polling-режиме - блокирует текущий поток/процесс.

    `install_signal_handlers=False` - для запуска в фоновом (не главном)
    потоке, как в desktop_app.py: signal.signal() работает только в главном
    потоке процесса, а python-telegram-bot по умолчанию пытается сам
    установить обработчики SIGINT/SIGTERM - на фоновом потоке это упадёт.
    """
    logging.basicConfig(level=logging.INFO)
    app = build_application()
    logger.info("Telegram-бот запущен (polling)")
    if install_signal_handlers:
        app.run_polling(drop_pending_updates=True)
    else:
        app.run_polling(drop_pending_updates=True, stop_signals=None)


if __name__ == "__main__":
    run_bot()

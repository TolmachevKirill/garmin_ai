"""Telegram-бот - мобильный доступ к пайплайну без веб-интерфейса.

Работает в polling-режиме (без webhook - не нужен публичный IP/домен, что
удобно для сценария "запустил exe на своём ПК дома, пишешь боту с телефона").
Детерминированные команды (/today, /week, /activity) транслируются напрямую в
существующие коллекторы; свободный текст и присланные файлы (.fit/.tcx/.gpx)
идут в агентный tool-calling цикл (llm_client.run_agentic, инструменты из
agent_tools.py/actions.py) - бот не просто отвечает "сухой аналитикой", а
может САМ сходить за нужными данными и выполнить действие (создать/удалить
тренировку в Garmin, залить файл) - см. README, раздел "Агентный Telegram-бот".
Write-действия перед выполнением требуют явного подтверждения кнопками
Confirm/Cancel - human-in-the-loop, а не "бот молча меняет твой Garmin".

Требует BYOK Telegram-токен (создаётся через @BotFather в самом Telegram) -
задаётся через веб-форму настройки (data/config.json) или .env
(TELEGRAM_BOT_TOKEN). Без токена run_bot()/build_application() бросают
RuntimeError - это ожидаемо для пользователя, который ещё не прошёл setup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date as date_cls
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from garmin_pipeline import agent_tools, config, llm_client
from garmin_pipeline.client import get_client
from garmin_pipeline.collectors.activity import get_exercise_sets, is_set_based_activity, search_activities
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.weekly import build_weekly_report
from garmin_pipeline.formatting import render_activity_md, render_daily_md, render_weekly_md

logger = logging.getLogger(__name__)

MAX_MESSAGE_LEN = 3500  # лимит Telegram - 4096 символов, оставляем запас
_MAX_HISTORY_MESSAGES = 24  # держим диалог не бесконечным - особенно важно для маленьких локальных моделей

# Память диалогов - однопользовательский локальный процесс, простой dict в
# памяти вполне достаточен (переживает только до перезапуска бота, что ОК:
# /reset и так сбрасывает контекст руками при желании).
_CONVERSATIONS: dict[int, list[dict]] = {}
_PENDING: dict[int, llm_client.PendingConfirmation] = {}


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
        "без запроса - последняя тренировка\n"
        "/reset - сбросить контекст диалога\n\n"
        "Или просто напиши вопрос/задачу свободным текстом - я сам решу, какие данные "
        "запросить у Garmin (сон, тренировки, конкретная активность), а могу и выполнить "
        "действие: создать/удалить тренировку, залить присланный файл (.fit/.tcx/.gpx) - "
        "перед этим спрошу подтверждение. Нужен настроенный LLM (см. /setup)."
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
    act = candidates[0]
    if is_set_based_activity(act.get("type")):
        act["exercise_sets"] = await asyncio.to_thread(get_exercise_sets, client, act["activity_id"])
    await _reply_long(update, render_activity_md(act))


def _uploads_dir() -> Path:
    d = config.settings.cache_db_path.parent / "tmp_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _trim_history(messages: list[dict], keep: int = _MAX_HISTORY_MESSAGES) -> list[dict]:
    """Обрезает историю диалога, не разрывая пары tool_call/tool-response -

    вызывать только когда диалог в "чистой" точке (kind == "final"), иначе
    можно случайно оторвать tool-ответ от вызвавшего его assistant-сообщения."""
    has_system = bool(messages) and messages[0].get("role") == "system"
    system = messages[:1] if has_system else []
    rest = messages[len(system) :]
    if len(rest) <= keep:
        return messages
    cut = len(rest) - keep
    while cut < len(rest) and rest[cut].get("role") != "user":
        cut += 1
    return system + rest[cut:]


def _new_history() -> list[dict]:
    return [{"role": "system", "content": llm_client.AGENTIC_SYSTEM_PROMPT}]


async def _run_agentic(history: list[dict]) -> llm_client.AgenticReply:
    return await asyncio.to_thread(
        llm_client.run_agentic,
        history,
        tools=agent_tools.TOOLS_SCHEMA,
        write_tool_names=agent_tools.WRITE_TOOL_NAMES,
        execute_tool=agent_tools.execute_tool,
        stringify=agent_tools.stringify_tool_result,
    )


async def _deliver_agentic_reply(reply_target, chat_id: int, reply: llm_client.AgenticReply) -> None:
    """reply_target - любой объект с async reply_text(text, ...) - подходят

    и Update.message, и CallbackQuery.message (см. handle_callback)."""
    if reply.kind == "final":
        _CONVERSATIONS[chat_id] = _trim_history(reply.messages)
        for chunk in _chunks(reply.text or "(пустой ответ)"):
            await reply_target.reply_text(chunk)
        return

    # kind == "confirm" - середина tool-calling цикла, историю не обрезаем.
    _CONVERSATIONS[chat_id] = reply.messages
    assert reply.pending is not None
    _PENDING[chat_id] = reply.pending
    preview = agent_tools.describe_call(reply.pending.name, reply.pending.arguments)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✅ Подтвердить", callback_data="confirm"),
          InlineKeyboardButton("❌ Отменить", callback_data="cancel")]]
    )
    await reply_target.reply_text(f"⚠️ {preview}", reply_markup=keyboard)


async def handle_free_text(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    if not config.settings.is_llm_configured():
        await update.message.reply_text(
            "LLM не настроен - задай llm_api_key через веб-форму настройки (/setup) или .env, "
            "либо используй команды /today, /week, /activity."
        )
        return

    chat_id = update.effective_chat.id
    history = _CONVERSATIONS.get(chat_id) or _new_history()
    history.append({"role": "user", "content": update.message.text})

    await update.message.reply_text("Думаю...")
    try:
        reply = await _run_agentic(history)
    except Exception as exc:  # noqa: BLE001 - хотим показать пользователю любую ошибку LLM как есть
        await update.message.reply_text(f"Ошибка при обращении к LLM: {exc}")
        return
    await _deliver_agentic_reply(update.message, chat_id, reply)


async def handle_document(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Пользователь прислал файл тренировки (.fit/.tcx/.gpx) - скачиваем его

    локально и отдаём модели решить, что делать (обычно - предложить
    upload_activity_file, что потребует подтверждения, как любой write-инструмент)."""
    if not await _guard(update):
        return
    if not config.settings.is_llm_configured():
        await update.message.reply_text(
            "Файл получен, но LLM не настроен - не могу решить, что с ним делать. "
            "Настрой LLM в /setup, либо загрузи файл через CLI (`cli.py`) или веб-интерфейс."
        )
        return

    doc = update.message.document
    local_path = _uploads_dir() / f"{update.effective_chat.id}_{doc.file_unique_id}_{doc.file_name}"
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(str(local_path))

    chat_id = update.effective_chat.id
    history = _CONVERSATIONS.get(chat_id) or _new_history()
    history.append(
        {
            "role": "user",
            "content": (
                f"Я прислал файл тренировки: {doc.file_name}. Он сохранён локально по пути: "
                f"{local_path}. Реши, что с ним сделать (обычно - предложить загрузить в Garmin "
                "Connect через upload_activity_file с этим путём)."
            ),
        }
    )
    await update.message.reply_text("Файл получен, разбираюсь...")
    try:
        reply = await _run_agentic(history)
    except Exception as exc:  # noqa: BLE001
        await update.message.reply_text(f"Ошибка при обращении к LLM: {exc}")
        return
    await _deliver_agentic_reply(update.message, chat_id, reply)


async def handle_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработка кнопок Подтвердить/Отменить под запросом на write-действие."""
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    pending = _PENDING.pop(chat_id, None)
    await query.edit_message_reply_markup(reply_markup=None)
    if pending is None:
        await query.message.reply_text("Это действие уже неактуально (возможно, диалог был сброшен).")
        return

    confirmed = query.data == "confirm"
    await query.message.reply_text("Выполняю..." if confirmed else "Отменяю...")
    try:
        reply = await asyncio.to_thread(
            llm_client.resume_after_confirmation,
            pending,
            confirmed=confirmed,
            tools=agent_tools.TOOLS_SCHEMA,
            write_tool_names=agent_tools.WRITE_TOOL_NAMES,
            execute_tool=agent_tools.execute_tool,
            stringify=agent_tools.stringify_tool_result,
        )
    except Exception as exc:  # noqa: BLE001
        await query.message.reply_text(f"Ошибка: {exc}")
        return
    await _deliver_agentic_reply(query.message, chat_id, reply)


async def cmd_reset(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update):
        return
    chat_id = update.effective_chat.id
    _CONVERSATIONS.pop(chat_id, None)
    _PENDING.pop(chat_id, None)
    await update.message.reply_text("Контекст диалога сброшен.")


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
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(
        MessageHandler(
            filters.Document.FileExtension("fit")
            | filters.Document.FileExtension("tcx")
            | filters.Document.FileExtension("gpx"),
            handle_document,
        )
    )
    app.add_handler(CallbackQueryHandler(handle_callback))
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

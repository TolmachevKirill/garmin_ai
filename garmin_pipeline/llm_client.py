"""Тонкая обёртка над OpenAI-совместимым API (BYOK/BYOM - "принеси свой ключ/модель").

Один и тот же код бьёт в OpenAI, Cloud.ru Evolution Foundation Models
(рекомендуется для РФ - OpenRouter больше недоступен без VPN), DeepSeek и в
локальный Ollama/LM Studio - у всех OpenAI-совместимый протокол /chat/completions,
отличается только base_url/api_key/model. Настройки читаются из
`config.settings` в момент вызова (не при импорте) - так изменения через
веб-форму/бот-setup (см. config.save_config_json) подхватываются без
перезапуска процесса.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from garmin_pipeline import config

ChatFn = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


class LlmNotConfiguredError(RuntimeError):
    """LLM не настроен - нет llm_api_key ни в data/config.json, ни в .env."""


def ask(system_prompt: str, context_md: str, user_message: str, *, temperature: float = 0.4) -> str:
    """Единый вызов LLM: системный промпт + агрегированный markdown-контекст

    (например, из collectors/context.py или render_weekly_md) + вопрос
    пользователя -> текстовый ответ.
    """
    settings = config.settings
    if not settings.is_llm_configured():
        raise LlmNotConfiguredError(
            "LLM не настроен - укажи llm_api_key (и, если нужно, llm_base_url/llm_model) "
            "в data/config.json (веб-форма /setup) или переменных окружения "
            "LLM_API_KEY/LLM_BASE_URL/LLM_MODEL."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Нужен пакет openai: pip install openai") from exc

    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    response = client.chat.completions.create(
        model=settings.llm_model,
        temperature=temperature,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{context_md}\n\n---\n\nВопрос пользователя: {user_message}"},
        ],
    )
    return response.choices[0].message.content or ""


DEFAULT_SYSTEM_PROMPT = (
    "Ты - персональный тренер и аналитик здоровья. Тебе дан агрегированный "
    "отчёт из Garmin Connect (сон, HRV, стресс, Body Battery, тренировки). "
    "Отвечай кратко и по-русски, опираясь только на предоставленные данные. "
    "Если данных для ответа не хватает - прямо скажи об этом."
)


AGENTIC_SYSTEM_PROMPT = (
    "Ты - персональный тренер и аналитик здоровья с прямым доступом к Garmin Connect "
    "пользователя через инструменты (function calling), а не через заранее подготовленный "
    "отчёт. Если вопрос требует конкретных цифр (сон, HRV, шаги, тренировки и т.п.) - "
    "вызови подходящий инструмент за нужный период, не выдумывай значения. Ты также можешь "
    "выполнять действия: создавать/удалять тренировки в Garmin и загружать файлы активностей. "
    "Когда пользователь просит такое действие - СРАЗУ вызывай соответствующий инструмент "
    "(function call), не спрашивай подтверждение сам текстом ('подтвердите?', 'вы уверены?', "
    "'да/нет?' и т.п.) и не описывай, что собираешься сделать, вместо вызова - внешняя "
    "система автоматически покажет пользователю кнопки Подтвердить/Отменить перед реальным "
    "выполнением изменяющего действия, это уже сделано за тебя, повторно спрашивать не нужно. "
    "Отвечай кратко, по-русски, по делу. Ответ читается в Telegram, а не в markdown-рендерере: "
    "не используй заголовки (###, ##), таблицы и нумерованные списки с жирным заголовком пункта - "
    "пиши обычным текстом и списками через '- ', для выделения используй одиночные звёздочки "
    "*вот так*, не двойные."
)


def build_agentic_system_prompt() -> str:
    """AGENTIC_SYSTEM_PROMPT + сегодняшняя дата.

    Без этого модель не может корректно посчитать date_from/date_to для
    относительных формулировок ("вчера", "на этой неделе", "последние 3 дня")
    - у неё нет доступа к системным часам, только к тому, что написано в
    промпте. Раньше эта дата нигде не подставлялась (см. bot.py::_new_history),
    из-за чего модель подставляла случайную дату из своих обучающих данных -
    баг был обнаружен при живом тестировании локальной qwen3:4b (см. чат):
    на вопрос "сколько шагов у меня было вчера?" модель вызвала get_daily_metrics
    с датой из 2023 года. Вызывать при СОЗДАНИИ истории диалога (а не один раз
    при импорте модуля), чтобы дата не "протухала" в долгоживущем процессе бота."""
    return f"{AGENTIC_SYSTEM_PROMPT}\n\nСегодняшняя дата: {date.today().isoformat()}."


# ---------------------------------------------------------------------------
# Агентный (tool-calling) цикл - для Telegram-бота (см. bot.py) и потенциально
# других интерфейсов, где ответ модели может требовать вызова инструментов
# из agent_tools.py, а не только текста.
# ---------------------------------------------------------------------------


@dataclass
class PendingConfirmation:
    """Write-инструмент, который модель хочет вызвать, но который требует

    подтверждения пользователя перед реальным выполнением (см. bot.py -
    кнопки Confirm/Cancel). messages - история диалога на момент запроса,
    включая сообщение ассистента с этим tool_call - нужна, чтобы продолжить
    диалог после подтверждения/отказа (см. resume_after_confirmation)."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]
    remaining_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgenticReply:
    """Результат одного прогона run_agentic()/resume_after_confirmation().

    kind="final" - готов текстовый ответ (text), диалог можно продолжать
    обычным образом на следующем сообщении пользователя.
    kind="confirm" - модель хочет вызвать write-инструмент (pending) -
    нужно показать пользователю подтверждение, прежде чем продолжать.
    messages - обновлённая история диалога, которую вызывающий код должен
    сохранить как новое состояние (см. bot.py, per-chat память)."""

    kind: str
    messages: list[dict[str, Any]]
    text: str | None = None
    pending: PendingConfirmation | None = None


def _parse_tool_args(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _default_chat_fn() -> ChatFn:
    settings = config.settings
    if not settings.is_llm_configured():
        raise LlmNotConfiguredError(
            "LLM не настроен - укажи llm_api_key (и, если нужно, llm_base_url/llm_model) "
            "в data/config.json (веб-форма /setup) или переменных окружения "
            "LLM_API_KEY/LLM_BASE_URL/LLM_MODEL."
        )
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Нужен пакет openai: pip install openai") from exc

    client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
    model = settings.llm_model

    def _call(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        response = client.chat.completions.create(
            model=model, temperature=0.3, messages=messages, tools=tools or None,
        )
        msg = response.choices[0].message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in msg.tool_calls
            ]
        return {"role": "assistant", "content": msg.content, "tool_calls": tool_calls}

    return _call


def run_agentic(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]],
    write_tool_names: set[str],
    execute_tool: Callable[[str, dict[str, Any]], Any],
    stringify: Callable[[Any], str] = str,
    max_iterations: int = 6,
    chat_fn: ChatFn | None = None,
) -> AgenticReply:
    """Цикл tool-calling: спрашивает модель, выполняет read-инструменты сама

    и продолжает цикл, а на первом write-инструменте (см. write_tool_names)
    останавливается и возвращает kind="confirm" - вызывающий код должен
    показать пользователю подтверждение и вызвать resume_after_confirmation().

    chat_fn - инъекция для тестов (сигнатура (messages, tools) -> assistant
    message dict вида {"role": "assistant", "content": str|None,
    "tool_calls": [...] | None}); по умолчанию - реальный вызов через openai SDK
    с настройками из config.settings.
    """
    if chat_fn is None:
        chat_fn = _default_chat_fn()

    messages = list(messages)
    for _ in range(max_iterations):
        assistant_msg = chat_fn(messages, tools)
        messages.append({k: v for k, v in assistant_msg.items() if v is not None})
        tool_calls = assistant_msg.get("tool_calls") or []
        if not tool_calls:
            return AgenticReply(kind="final", text=assistant_msg.get("content") or "", messages=messages)

        for i, tc in enumerate(tool_calls):
            fn_name = tc["function"]["name"]
            fn_args = _parse_tool_args(tc["function"].get("arguments"))
            if fn_name in write_tool_names:
                pending = PendingConfirmation(
                    tool_call_id=tc["id"],
                    name=fn_name,
                    arguments=fn_args,
                    remaining_tool_calls=tool_calls[i + 1 :],
                    messages=messages,
                )
                return AgenticReply(kind="confirm", messages=messages, pending=pending)
            result = execute_tool(fn_name, fn_args)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": stringify(result)})
        # Все tool_calls на этом шаге были read - продолжаем цикл автоматически,
        # модель увидит их результаты и либо ответит текстом, либо позовёт ещё инструмент.

    return AgenticReply(
        kind="final",
        text="Не получилось завершить рассуждение за отведённое число шагов - попробуй переформулировать запрос.",
        messages=messages,
    )


def resume_after_confirmation(
    pending: PendingConfirmation,
    *,
    confirmed: bool,
    tools: list[dict[str, Any]],
    write_tool_names: set[str],
    execute_tool: Callable[[str, dict[str, Any]], Any],
    stringify: Callable[[Any], str] = str,
    max_iterations: int = 6,
    chat_fn: ChatFn | None = None,
) -> AgenticReply:
    """Продолжает диалог после того, как пользователь подтвердил/отклонил

    write-инструмент из pending (см. run_agentic). Если в исходном ответе
    модели была не одна пачка tool_calls, а несколько (pending.remaining_tool_calls),
    выполняет оставшиеся read-инструменты и, если среди них встретится ещё
    один write - снова остановится на нём (новый AgenticReply(kind="confirm"))."""
    messages = list(pending.messages)
    content = stringify(execute_tool(pending.name, pending.arguments)) if confirmed else (
        "Пользователь отклонил выполнение этого действия."
    )
    messages.append({"role": "tool", "tool_call_id": pending.tool_call_id, "content": content})

    for i, tc in enumerate(pending.remaining_tool_calls):
        fn_name = tc["function"]["name"]
        fn_args = _parse_tool_args(tc["function"].get("arguments"))
        if fn_name in write_tool_names:
            new_pending = PendingConfirmation(
                tool_call_id=tc["id"],
                name=fn_name,
                arguments=fn_args,
                remaining_tool_calls=pending.remaining_tool_calls[i + 1 :],
                messages=messages,
            )
            return AgenticReply(kind="confirm", messages=messages, pending=new_pending)
        result = execute_tool(fn_name, fn_args)
        messages.append({"role": "tool", "tool_call_id": tc["id"], "content": stringify(result)})

    return run_agentic(
        messages,
        tools=tools,
        write_tool_names=write_tool_names,
        execute_tool=execute_tool,
        stringify=stringify,
        max_iterations=max_iterations,
        chat_fn=chat_fn,
    )

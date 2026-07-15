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

from garmin_pipeline import config


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

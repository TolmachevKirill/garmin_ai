"""HTML-шаблоны веб-интерфейса - обычные f-строки, без Jinja2.

Инструмент локальный и однопользовательский (не смотрит в интернет) - лишняя
зависимость на шаблонизатор не оправдана. html.escape используется везде, где
в шаблон попадают значения из config.json/файлов библиотеки.
"""

from __future__ import annotations

import html
from typing import Any

_STYLE = """
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    background: #0f1115; color: #e6e6e6; margin: 0; padding: 0 0 40px;
  }
  header {
    background: #161923; padding: 18px 28px; border-bottom: 1px solid #262a36;
    display: flex; align-items: center; justify-content: space-between;
  }
  header h1 { font-size: 18px; margin: 0; color: #7fd1ae; }
  header nav a { color: #9aa4b2; text-decoration: none; margin-left: 18px; font-size: 14px; }
  header nav a:hover { color: #e6e6e6; }
  main { max-width: 820px; margin: 0 auto; padding: 28px; }
  .card {
    background: #161923; border: 1px solid #262a36; border-radius: 10px;
    padding: 20px 24px; margin-bottom: 20px;
  }
  .card h2 { font-size: 15px; color: #9aa4b2; text-transform: uppercase; letter-spacing: .05em; margin: 0 0 14px; }
  label { display: block; font-size: 13px; color: #9aa4b2; margin: 14px 0 4px; }
  input, select {
    width: 100%; padding: 9px 12px; border-radius: 6px; border: 1px solid #2c3140;
    background: #0f1115; color: #e6e6e6; font-size: 14px;
  }
  input:focus, select:focus { outline: none; border-color: #7fd1ae; }
  .row { display: flex; gap: 14px; }
  .row > div { flex: 1; }
  button {
    background: #7fd1ae; color: #0f1115; border: none; border-radius: 6px;
    padding: 10px 18px; font-size: 14px; font-weight: 600; cursor: pointer; margin-top: 16px;
  }
  button:hover { background: #6cc09c; }
  button.secondary { background: #262a36; color: #e6e6e6; }
  button.secondary:hover { background: #323744; }
  .actions { display: flex; gap: 10px; flex-wrap: wrap; }
  .actions form { margin: 0; }
  ul.files { list-style: none; padding: 0; margin: 0; }
  ul.files li { padding: 6px 0; border-bottom: 1px solid #1e2129; font-size: 14px; }
  ul.files li:last-child { border-bottom: none; }
  ul.files a { color: #7fd1ae; text-decoration: none; }
  ul.files a:hover { text-decoration: underline; }
  .empty { color: #6b7280; font-size: 13px; }
  .badge { display: inline-block; background: #262a36; color: #9aa4b2; border-radius: 999px; padding: 2px 10px; font-size: 12px; margin-left: 8px; }
  .flash { background: #1d3a2c; border: 1px solid #2f6e4c; color: #a7e6c4; padding: 10px 14px; border-radius: 6px; margin-bottom: 20px; font-size: 14px; }
  .hint { color: #6b7280; font-size: 12px; margin-top: 4px; }
  pre { background: #0b0d11; border: 1px solid #262a36; border-radius: 8px; padding: 16px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  a.back { color: #9aa4b2; text-decoration: none; font-size: 13px; }
</style>
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  {_STYLE}
</head>
<body>
  <header>
    <h1>🏃 Garmin Health Pipeline</h1>
    <nav>
      <a href="/dashboard">Дашборд</a>
      <a href="/setup">Настройки</a>
    </nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


def setup_page(settings: Any, flash: str | None = None) -> str:
    flash_html = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    email = html.escape(settings.email or "")
    llm_base_url = html.escape(settings.llm_base_url or "")
    llm_model = html.escape(settings.llm_model or "")
    telegram_allowed = html.escape(settings.telegram_allowed_user_id or "")
    has_llm_key = "•" * 8 if settings.llm_api_key else ""
    has_telegram_token = "•" * 8 if settings.telegram_bot_token else ""
    has_password = "•" * 8 if settings.password else ""

    body = f"""
    {flash_html}
    <form method="post" action="/setup">
      <div class="card">
        <h2>Garmin Connect</h2>
        <label>Email</label>
        <input name="garmin_email" value="{email}" placeholder="you@example.com">
        <label>Пароль</label>
        <input type="password" name="garmin_password" value="" placeholder="{has_password or 'пароль'}">
        <div class="hint">Пароль хранится в data/config.json на этом компьютере - не передаётся никуда, кроме Garmin.</div>
      </div>

      <div class="card">
        <h2>LLM (BYOK/BYOM - свой ключ/модель)</h2>
        <label>Провайдер (подставит Base URL и модель, можно поправить руками)</label>
        <select id="llm_preset" onchange="applyLlmPreset(this)">
          <option value="">— выбери или впиши свои значения ниже —</option>
          <option value="https://foundation-models.api.cloud.ru/v1|deepseek-ai/DeepSeek-V3.1">Cloud.ru Evolution Foundation Models (рекомендуется в РФ)</option>
          <option value="https://api.openai.com/v1|gpt-4o-mini">OpenAI</option>
          <option value="https://api.deepseek.com/v1|deepseek-chat">DeepSeek (напрямую)</option>
          <option value="http://localhost:11434/v1|qwen2.5">Ollama (локально, без ключа)</option>
        </select>
        <div class="row">
          <div>
            <label>Base URL</label>
            <input name="llm_base_url" id="llm_base_url" value="{llm_base_url}" placeholder="https://api.openai.com/v1">
          </div>
          <div>
            <label>Модель</label>
            <input name="llm_model" id="llm_model" value="{llm_model}" placeholder="gpt-4o-mini">
          </div>
        </div>
        <label>API-ключ</label>
        <input type="password" name="llm_api_key" value="" placeholder="{has_llm_key or 'sk-...'}">
        <div class="hint">
          Подходит любой OpenAI-совместимый провайдер. OpenRouter ушёл из РФ и
          для российских пользователей больше не работает - рекомендуем
          <a href="https://cloud.ru/docs/foundation-models/ug/topics/quickstart" target="_blank" rel="noopener">Cloud.ru Evolution Foundation Models</a>
          (доступ из РФ без VPN, каталог из 20+ моделей включая DeepSeek/Qwen/GigaChat,
          ключ выпускается в личном кабинете за пару минут) или полностью локальный
          Ollama/LM&nbsp;Studio, если не хочется отправлять данные куда-либо вовне.
        </div>
      </div>

      <div class="card">
        <h2>Telegram-бот (необязательно)</h2>
        <label>Bot token</label>
        <input type="password" name="telegram_bot_token" value="" placeholder="{has_telegram_token or 'создать через @BotFather'}">
        <label>Разрешённый Telegram user id</label>
        <input name="telegram_allowed_user_id" value="{telegram_allowed}" placeholder="оставь пустым, если бот только для тебя одного и это не важно">
      </div>

      <button type="submit">Сохранить</button>
    </form>
    <script>
      function applyLlmPreset(select) {{
        if (!select.value) return;
        var parts = select.value.split("|");
        document.getElementById("llm_base_url").value = parts[0];
        document.getElementById("llm_model").value = parts[1];
      }}
    </script>
    """
    return _page("Настройка - Garmin Health Pipeline", body)


def dashboard_page(summary: dict[str, Any], settings: Any, flash: str | None = None) -> str:
    flash_html = f'<div class="flash">{html.escape(flash)}</div>' if flash else ""

    def file_list(files: list[str], category: str) -> str:
        if not files:
            return '<div class="empty">Пока нет файлов.</div>'
        items = "".join(
            f'<li><a href="/view?category={category}&name={html.escape(f)}">{html.escape(f)}</a></li>'
            for f in reversed(files[-15:])
        )
        return f'<ul class="files">{items}</ul>'

    llm_badge = "настроен" if settings.is_llm_configured() else "не настроен"
    telegram_badge = "настроен" if settings.is_telegram_configured() else "не настроен"
    garmin_badge = "настроен" if settings.email else "не настроен"

    context_link = (
        '<a href="/view?category=context&name=context.md">context.md</a>'
        if summary["context_exists"]
        else '<span class="empty">не сформирован</span>'
    )

    body = f"""
    {flash_html}
    <div class="card">
      <h2>Статус</h2>
      Garmin <span class="badge">{garmin_badge}</span>
      LLM <span class="badge">{llm_badge}</span>
      Telegram <span class="badge">{telegram_badge}</span>
      &nbsp;&nbsp;<a class="back" href="/setup">изменить →</a>
      <div class="hint">После изменения Telegram-токена нужно перезапустить приложение, чтобы бот подключился.</div>
    </div>

    <div class="card">
      <h2>Быстрые действия</h2>
      <div class="actions">
        <form method="post" action="/dashboard/run/context"><button>Собрать снапшот (context)</button></form>
        <form method="post" action="/dashboard/run/daily"><button class="secondary">Собрать сегодняшний день</button></form>
        <form method="post" action="/dashboard/run/weekly"><button class="secondary">Собрать текущую неделю</button></form>
      </div>
    </div>

    <div class="card">
      <h2>Снапшот (context.md)</h2>
      {context_link}
    </div>

    <div class="card">
      <h2>Weekly <span class="badge">{len(summary['weekly'])}</span></h2>
      {file_list(summary['weekly'], 'weekly')}
    </div>

    <div class="card">
      <h2>Daily <span class="badge">{len(summary['daily'])}</span></h2>
      {file_list(summary['daily'], 'daily')}
    </div>

    <div class="card">
      <h2>Activities <span class="badge">{len(summary['activities'])}</span></h2>
      {file_list(summary['activities'], 'activities')}
    </div>

    <div class="card">
      <h2>Monthly <span class="badge">{len(summary['monthly'])}</span></h2>
      {file_list(summary['monthly'], 'monthly')}
    </div>
    """
    return _page("Дашборд - Garmin Health Pipeline", body)


def view_page(title: str, content: str) -> str:
    body = f"""
    <a class="back" href="/dashboard">← Назад к дашборду</a>
    <div class="card">
      <h2>{html.escape(title)}</h2>
      <pre>{html.escape(content)}</pre>
    </div>
    """
    return _page(title, body)

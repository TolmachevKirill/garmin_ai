"""HTML-шаблоны веб-интерфейса - обычные f-строки, без Jinja2.

Инструмент локальный и однопользовательский (не смотрит в интернет) - лишняя
зависимость на шаблонизатор не оправдана. html.escape используется везде, где
в шаблон попадают значения из config.json/файлов библиотеки. Дизайн - светлая
тема в духе Notion/Apple: системные шрифты (никаких внешних CDN), мягкие тени,
скругления, спокойная типографика.
"""

from __future__ import annotations

import html
from datetime import date as date_cls
from datetime import timedelta
from typing import Any

from garmin_pipeline.formatting import (
    activity_icon,
    activity_label_ru,
    fmt_duration,
    fmt_km,
    fmt_num,
    fmt_tempo,
    uses_speed_not_pace,
)

_FAVICON = (
    "data:image/svg+xml,"
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>"
    "<text y='.9em' font-size='90'>🏃</text></svg>"
)

_STYLE = """
<style>
  :root {
    color-scheme: light;
    --bg: #ffffff;
    --bg-soft: #f7f7f5;
    --border: #e9e9e7;
    --border-strong: #dcdcda;
    --text: #26251f;
    --text-soft: #787774;
    --accent: #2383e2;
    --accent-soft: rgba(35, 131, 226, .14);
    --black: #1a1a1a;
    --black-hover: #333333;
    --green-bg: #e9f5ee;
    --green-text: #1f7a4d;
    --red-bg: #fdecea;
    --red-text: #c0392b;
    --shadow-sm: 0 1px 2px rgba(15, 15, 15, .04), 0 1px 1px rgba(15, 15, 15, .03);
    --shadow-md: 0 4px 16px rgba(15, 15, 15, .07);
    --radius: 14px;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable",
      "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg-soft); color: var(--text);
    font-size: 15px; line-height: 1.55; -webkit-font-smoothing: antialiased;
  }
  header {
    position: sticky; top: 0; z-index: 10;
    background: rgba(255, 255, 255, .85); backdrop-filter: saturate(180%) blur(12px);
    padding: 14px 32px; border-bottom: 1px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  .brand { display: flex; align-items: center; gap: 10px; }
  .brand-mark {
    width: 30px; height: 30px; border-radius: 9px; display: flex; align-items: center;
    justify-content: center; font-size: 16px;
    background: linear-gradient(135deg, #2383e2, #6fd6a8);
  }
  header h1 { font-size: 15px; font-weight: 600; margin: 0; color: var(--text); }
  header nav { display: flex; gap: 4px; background: var(--bg-soft); border-radius: 10px; padding: 3px; }
  header nav a {
    color: var(--text-soft); text-decoration: none; font-size: 13px; font-weight: 500;
    padding: 7px 14px; border-radius: 8px; transition: color .15s, background .15s;
  }
  header nav a:hover { color: var(--text); background: rgba(0, 0, 0, .04); }
  header nav a.active { color: var(--text); background: #fff; box-shadow: var(--shadow-sm); }
  main { max-width: 760px; margin: 0 auto; padding: 40px 28px 64px; }

  .eyebrow { color: var(--accent); font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; margin: 0 0 8px; }
  .page-title { font-size: 28px; font-weight: 650; margin: 0 0 8px; letter-spacing: -.01em; }
  .page-subtitle { color: var(--text-soft); font-size: 15px; margin: 0 0 32px; max-width: 560px; }

  .card {
    background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
    box-shadow: var(--shadow-sm); padding: 26px 28px; margin-bottom: 20px;
    transition: box-shadow .2s ease;
  }
  .card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
  .card-icon {
    width: 30px; height: 30px; border-radius: 9px; background: var(--bg-soft);
    display: flex; align-items: center; justify-content: center; font-size: 15px; flex: none;
  }
  .card h2 { font-size: 16px; font-weight: 600; margin: 0; color: var(--text); }
  .card-sub { color: var(--text-soft); font-size: 13px; margin: 2px 0 18px 40px; }

  label { display: block; font-size: 13px; font-weight: 500; color: var(--text-soft); margin: 16px 0 6px; }
  label:first-of-type { margin-top: 0; }
  input, select {
    width: 100%; padding: 10px 13px; border-radius: 10px; border: 1px solid var(--border-strong);
    background: var(--bg); color: var(--text); font-size: 14px; font-family: inherit;
    transition: border-color .15s, box-shadow .15s;
  }
  input::placeholder { color: #b0aea6; }
  input:focus, select:focus {
    outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-soft);
  }
  select {
    appearance: none;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%23787774'/%3E%3C/svg%3E");
    background-repeat: no-repeat; background-position: right 14px center; padding-right: 32px;
  }
  .row { display: flex; gap: 14px; }
  .row > div { flex: 1; }
  .field-wrap { position: relative; }
  .field-wrap input { padding-right: 40px; }
  .eye-toggle {
    position: absolute; right: 4px; top: 4px; bottom: 4px; width: 34px; border: none;
    background: transparent; cursor: pointer; color: var(--text-soft); font-size: 15px;
    border-radius: 8px; display: flex; align-items: center; justify-content: center;
  }
  .eye-toggle:hover { background: var(--bg-soft); color: var(--text); }
  .hint { color: var(--text-soft); font-size: 12.5px; margin-top: 10px; line-height: 1.6; }
  .hint a { color: var(--accent); text-decoration: none; }
  .hint a:hover { text-decoration: underline; }

  .save-bar { display: flex; flex-direction: column; align-items: center; gap: 8px; margin-top: 28px; }
  button {
    border: none; border-radius: 980px; padding: 11px 22px; font-size: 14px; font-weight: 600;
    cursor: pointer; font-family: inherit; transition: transform .12s ease, box-shadow .12s ease, background .12s ease;
  }
  button.primary { background: var(--black); color: #fff; }
  button.primary:hover { background: var(--black-hover); box-shadow: var(--shadow-md); transform: translateY(-1px); }
  button.primary:active { transform: translateY(0); }
  button.secondary { background: var(--bg); color: var(--text); border: 1px solid var(--border-strong); }
  button.secondary:hover { background: var(--bg-soft); }

  .flash {
    background: var(--green-bg); border: 1px solid #bfe3cd; color: var(--green-text);
    padding: 12px 16px; border-radius: 12px; margin-bottom: 24px; font-size: 13.5px; font-weight: 500;
    display: flex; align-items: center; gap: 8px;
  }

  .status-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 20px; }
  .status-item {
    background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 16px 16px; box-shadow: var(--shadow-sm);
  }
  .status-item .s-icon { font-size: 18px; margin-bottom: 8px; }
  .status-item .s-label { font-size: 12.5px; color: var(--text-soft); font-weight: 500; margin-bottom: 8px; }
  .chip {
    display: inline-flex; align-items: center; gap: 5px; font-size: 12px; font-weight: 600;
    padding: 3px 10px; border-radius: 999px;
  }
  .chip::before { content: ""; width: 6px; height: 6px; border-radius: 50%; }
  .chip-on { background: var(--green-bg); color: var(--green-text); }
  .chip-on::before { background: #2fa866; }
  .chip-off { background: var(--bg-soft); color: var(--text-soft); }
  .chip-off::before { background: #b0aea6; }
  .status-footer { text-align: center; margin: -8px 0 20px; }
  .status-footer a { color: var(--accent); font-size: 13px; text-decoration: none; font-weight: 500; }
  .status-footer a:hover { text-decoration: underline; }

  .action-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .action-grid form { margin: 0; }
  .action-card {
    width: 100%; text-align: left; background: var(--bg); border: 1px solid var(--border);
    border-radius: var(--radius); padding: 16px; box-shadow: var(--shadow-sm);
    display: flex; flex-direction: column; gap: 6px; font-family: inherit;
  }
  .action-card:hover { background: var(--bg-soft); transform: translateY(-1px); box-shadow: var(--shadow-md); }
  .action-card .a-icon { font-size: 18px; }
  .action-card .a-title { font-size: 13.5px; font-weight: 600; color: var(--text); }
  .action-card .a-sub { font-size: 12px; color: var(--text-soft); font-weight: 400; line-height: 1.4; }

  .section-title { display: flex; align-items: center; gap: 8px; margin: 0 0 2px; }
  .section-title h2 { font-size: 15px; font-weight: 600; margin: 0; }
  .count-badge {
    background: var(--bg-soft); color: var(--text-soft); font-size: 11.5px; font-weight: 600;
    padding: 2px 8px; border-radius: 999px;
  }

  ul.files { list-style: none; padding: 0; margin: 12px 0 0; }
  ul.files li { border-radius: 10px; }
  ul.files a {
    display: flex; align-items: center; justify-content: space-between; gap: 10px;
    color: var(--text); text-decoration: none; font-size: 13.5px; padding: 9px 10px;
    border-radius: 10px; transition: background .12s;
  }
  ul.files a:hover { background: var(--bg-soft); }
  ul.files a::after { content: "→"; color: var(--text-soft); opacity: 0; transition: opacity .12s; }
  ul.files a:hover::after { opacity: 1; }
  .empty { color: var(--text-soft); font-size: 13px; padding: 4px 0; }

  pre {
    background: var(--bg-soft); border: 1px solid var(--border); border-radius: 12px;
    padding: 18px 20px; overflow-x: auto; white-space: pre-wrap; word-break: break-word;
    font-family: "SF Mono", "Cascadia Code", Consolas, monospace; font-size: 13px; line-height: 1.6;
    color: var(--text);
  }
  a.back {
    color: var(--text-soft); text-decoration: none; font-size: 13px; font-weight: 500;
    display: inline-flex; align-items: center; gap: 6px; margin-bottom: 16px;
  }
  a.back:hover { color: var(--text); }

  .range-form { display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap; }
  .range-form .row { flex: 1 1 260px; margin: 0; }
  .range-form label { margin: 0 0 6px; }
  .range-form button { flex: none; height: 42px; }

  .hero-banner {
    background: linear-gradient(135deg, #2383e2 0%, #1a6fc4 55%, #123f73 100%);
    border-radius: 20px; padding: 32px 30px; color: #fff; margin-bottom: 20px;
    box-shadow: var(--shadow-md);
  }
  .hero-banner .eyebrow { color: rgba(255,255,255,.75); }
  .hero-banner .page-title { color: #fff; margin-bottom: 4px; }
  .hero-banner .page-subtitle { color: rgba(255,255,255,.82); margin-bottom: 0; }

  .hero-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 22px; }
  .hero-stat {
    background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 20px 18px; box-shadow: var(--shadow-sm); text-align: center;
  }
  .hero-stat .h-value { font-size: 26px; font-weight: 700; letter-spacing: -.01em; color: var(--text); }
  .hero-stat .h-label { font-size: 12.5px; color: var(--text-soft); font-weight: 500; margin-top: 4px; }

  .type-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
  .type-card {
    background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
    padding: 18px 20px; box-shadow: var(--shadow-sm);
  }
  .type-card .t-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
  .type-card .t-icon {
    width: 34px; height: 34px; border-radius: 10px; background: var(--bg-soft);
    display: flex; align-items: center; justify-content: center; font-size: 17px; flex: none;
  }
  .type-card .t-title { font-size: 14.5px; font-weight: 650; color: var(--text); }
  .type-card .t-count { font-size: 12px; color: var(--text-soft); font-weight: 500; }
  .type-card .t-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; }
  .type-card .t-stat-value { font-size: 15px; font-weight: 650; color: var(--text); }
  .type-card .t-stat-label { font-size: 11.5px; color: var(--text-soft); margin-top: 1px; }

  @media (max-width: 600px) {
    .status-grid, .action-grid, .hero-stats, .type-grid { grid-template-columns: 1fr; }
    header { padding: 12px 18px; }
    main { padding: 28px 16px 48px; }
    .range-form { flex-direction: column; align-items: stretch; }
  }
  @media print {
    header, .range-form, a.back, .print-hide { display: none !important; }
    body { background: #fff; }
    .hero-banner { box-shadow: none; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
"""

_SCRIPT_TOGGLE_PASSWORD = """
<script>
  function togglePw(btn, inputId) {
    var el = document.getElementById(inputId);
    var show = el.type === "password";
    el.type = show ? "text" : "password";
    btn.textContent = show ? "🙈" : "👁";
  }
</script>
"""

_SCRIPT_LLM_PRESET = """
<script>
  function applyLlmPreset(select) {
    if (!select.value) return;
    var parts = select.value.split("|");
    document.getElementById("llm_base_url").value = parts[0];
    document.getElementById("llm_model").value = parts[1];
  }
</script>
"""


def _password_field(name: str, *, placeholder: str) -> str:
    """Поле пароля/ключа со кнопкой-глазом показать/скрыть значение."""
    input_id = f"pw-{name}"
    return f"""
    <div class="field-wrap">
      <input type="password" id="{input_id}" name="{name}" value="" placeholder="{html.escape(placeholder)}">
      <button type="button" class="eye-toggle" onclick="togglePw(this, '{input_id}')" tabindex="-1">👁</button>
    </div>
    """


def _page(title: str, body: str, *, active: str = "") -> str:
    def nav_class(path: str) -> str:
        return "active" if path == active else ""

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <link rel="icon" href="{_FAVICON}">
  {_STYLE}
</head>
<body>
  <header>
    <div class="brand">
      <div class="brand-mark">🏃</div>
      <h1>Garmin Health Pipeline</h1>
    </div>
    <nav>
      <a class="{nav_class('dashboard')}" href="/dashboard">Дашборд</a>
      <a class="{nav_class('setup')}" href="/setup">Настройки</a>
    </nav>
  </header>
  <main>{body}</main>
</body>
</html>"""


def setup_page(settings: Any, flash: str | None = None) -> str:
    flash_html = f'<div class="flash">✅ {html.escape(flash)}</div>' if flash else ""
    email = html.escape(settings.email or "")
    llm_base_url = html.escape(settings.llm_base_url or "")
    llm_model = html.escape(settings.llm_model or "")
    telegram_allowed = html.escape(settings.telegram_allowed_user_id or "")
    has_llm_key = "API-ключ сохранён" if settings.llm_api_key else "sk-..."
    has_telegram_token = "токен сохранён" if settings.telegram_bot_token else "создать через @BotFather"
    has_password = "пароль сохранён" if settings.password else "пароль"

    body = f"""
    <div class="eyebrow">Настройка</div>
    <h1 class="page-title">Подключим твои данные</h1>
    <p class="page-subtitle">
      Garmin — для сбора метрик и тренировок. LLM и Telegram — опционально,
      если хочешь общаться с данными напрямую, а не только заливать файлы в ChatGPT.
    </p>
    {flash_html}
    <form method="post" action="/setup">
      <div class="card">
        <div class="card-head">
          <div class="card-icon">🔗</div>
          <h2>Garmin Connect</h2>
        </div>
        <div class="card-sub">Нужны только для первого логина — дальше используется сохранённый токен.</div>
        <label>Email</label>
        <input name="garmin_email" value="{email}" placeholder="you@example.com">
        <label>Пароль</label>
        {_password_field("garmin_password", placeholder=has_password)}
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-icon">🧠</div>
          <h2>LLM (BYOK/BYOM — свой ключ или модель)</h2>
        </div>
        <div class="card-sub">Один и тот же протокол подходит любому OpenAI-совместимому провайдеру.</div>
        <label>Провайдер</label>
        <select id="llm_preset" onchange="applyLlmPreset(this)">
          <option value="">— выбери пресет или впиши значения ниже —</option>
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
        {_password_field("llm_api_key", placeholder=has_llm_key)}
        <div class="hint">
          OpenRouter больше не работает для пользователей из РФ без VPN — рекомендуем
          <a href="https://cloud.ru/docs/foundation-models/ug/topics/quickstart" target="_blank" rel="noopener">Cloud.ru Evolution Foundation Models</a>
          (доступ из РФ без VPN, 20+ моделей: DeepSeek/Qwen/GigaChat) или полностью локальный
          Ollama/LM&nbsp;Studio, если данные не должны уходить с компьютера.
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-icon">📱</div>
          <h2>Telegram-бот</h2>
        </div>
        <div class="card-sub">Необязательно — позволяет писать боту с телефона вместо консоли.</div>
        <label>Bot token</label>
        {_password_field("telegram_bot_token", placeholder=has_telegram_token)}
        <label>Разрешённый Telegram user id</label>
        <input name="telegram_allowed_user_id" value="{telegram_allowed}" placeholder="оставь пустым, если бот только для тебя">
      </div>

      <div class="save-bar">
        <button type="submit" class="primary">Сохранить настройки</button>
      </div>
    </form>
    {_SCRIPT_TOGGLE_PASSWORD}
    {_SCRIPT_LLM_PRESET}
    """
    return _page("Настройка - Garmin Health Pipeline", body, active="setup")


def dashboard_page(summary: dict[str, Any], settings: Any, flash: str | None = None) -> str:
    flash_html = f'<div class="flash">✅ {html.escape(flash)}</div>' if flash else ""

    def file_list(files: list[str], category: str) -> str:
        if not files:
            return '<div class="empty">Пока нет файлов.</div>'
        items = "".join(
            f'<li><a href="/view?category={category}&name={html.escape(f)}"><span>{html.escape(f)}</span></a></li>'
            for f in reversed(files[-15:])
        )
        return f'<ul class="files">{items}</ul>'

    def chip(configured: bool) -> str:
        return f'<span class="chip {"chip-on" if configured else "chip-off"}">{"настроен" if configured else "не настроен"}</span>'

    context_link = (
        '<a href="/view?category=context&name=context.md">Открыть context.md →</a>'
        if summary["context_exists"]
        else '<span class="empty">Ещё не сформирован — собери снапшот кнопкой выше.</span>'
    )

    today = date_cls.today()
    default_from = (today - timedelta(days=13)).isoformat()
    default_to = today.isoformat()
    range_files = summary.get("range") or []
    range_links = "".join(
        f'<li><a href="/range?from={f.removesuffix(".md").split("_")[0]}&to={f.removesuffix(".md").split("_")[1]}">'
        f'<span>{html.escape(f.removesuffix(".md").replace("_", " – "))}</span></a></li>'
        for f in reversed(range_files[-10:])
    )

    body = f"""
    <div class="eyebrow">Дашборд</div>
    <h1 class="page-title">Твоя библиотека данных</h1>
    <p class="page-subtitle">Собери свежий отчёт одной кнопкой и залей его в ChatGPT Project — или подключи LLM/бота ниже, чтобы общаться с данными напрямую.</p>
    {flash_html}

    <div class="status-grid">
      <div class="status-item">
        <div class="s-icon">🔗</div>
        <div class="s-label">Garmin</div>
        {chip(bool(settings.email))}
      </div>
      <div class="status-item">
        <div class="s-icon">🧠</div>
        <div class="s-label">LLM</div>
        {chip(settings.is_llm_configured())}
      </div>
      <div class="status-item">
        <div class="s-icon">📱</div>
        <div class="s-label">Telegram</div>
        {chip(settings.is_telegram_configured())}
      </div>
    </div>
    <div class="status-footer">
      <a href="/setup">Изменить настройки →</a>
    </div>

    <div class="card">
      <div class="section-title"><h2>Быстрые действия</h2></div>
      <div class="action-grid">
        <form method="post" action="/dashboard/run/context">
          <button type="submit" class="action-card">
            <span class="a-icon">📊</span>
            <span class="a-title">Снапшот</span>
            <span class="a-sub">Агрегат последних 14 дней для LLM</span>
          </button>
        </form>
        <form method="post" action="/dashboard/run/daily">
          <button type="submit" class="action-card">
            <span class="a-icon">☀️</span>
            <span class="a-title">Сегодня</span>
            <span class="a-sub">Дневной отчёт за текущий день</span>
          </button>
        </form>
        <form method="post" action="/dashboard/run/weekly">
          <button type="submit" class="action-card">
            <span class="a-icon">📅</span>
            <span class="a-title">Неделя</span>
            <span class="a-sub">Собрать отчёт за текущую неделю</span>
          </button>
        </form>
      </div>
    </div>

    <div class="card">
      <div class="section-title"><h2>Отчёт за период</h2></div>
      <div class="card-sub" style="margin-left:0">
        Красивая сводка для публикации: шаги, дистанция и тренировки по типам за выбранные даты.
      </div>
      <form method="post" action="/dashboard/run/range" class="range-form">
        <div class="row">
          <div>
            <label>С</label>
            <input type="date" name="date_from" value="{default_from}" required>
          </div>
        </div>
        <div class="row">
          <div>
            <label>По</label>
            <input type="date" name="date_to" value="{default_to}" required>
          </div>
        </div>
        <button type="submit" class="primary">Собрать отчёт</button>
      </form>
      {f'<ul class="files" style="margin-top:16px">{range_links}</ul>' if range_links else ""}
    </div>

    <div class="card">
      <div class="section-title"><h2>Снапшот (context.md)</h2></div>
      <div class="card-sub" style="margin-left:0">{context_link}</div>
    </div>

    <div class="card">
      <div class="section-title"><h2>Weekly</h2><span class="count-badge">{len(summary['weekly'])}</span></div>
      {file_list(summary['weekly'], 'weekly')}
    </div>

    <div class="card">
      <div class="section-title"><h2>Daily</h2><span class="count-badge">{len(summary['daily'])}</span></div>
      {file_list(summary['daily'], 'daily')}
    </div>

    <div class="card">
      <div class="section-title"><h2>Activities</h2><span class="count-badge">{len(summary['activities'])}</span></div>
      {file_list(summary['activities'], 'activities')}
    </div>

    <div class="card">
      <div class="section-title"><h2>Monthly</h2><span class="count-badge">{len(summary['monthly'])}</span></div>
      {file_list(summary['monthly'], 'monthly')}
    </div>
    """
    return _page("Дашборд - Garmin Health Pipeline", body, active="dashboard")


_MONTHS_RU_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _format_range_title(date_from: str, date_to: str) -> str:
    d1, d2 = date_cls.fromisoformat(date_from), date_cls.fromisoformat(date_to)
    if d1.year == d2.year and d1.month == d2.month:
        return f"{d1.day} – {d2.day} {_MONTHS_RU_GEN[d2.month]} {d2.year}"
    if d1.year == d2.year:
        return f"{d1.day} {_MONTHS_RU_GEN[d1.month]} – {d2.day} {_MONTHS_RU_GEN[d2.month]} {d2.year}"
    return f"{d1.day} {_MONTHS_RU_GEN[d1.month]} {d1.year} – {d2.day} {_MONTHS_RU_GEN[d2.month]} {d2.year}"


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    n_abs = abs(n) % 100
    n1 = n_abs % 10
    if 11 <= n_abs <= 14:
        return many
    if n1 == 1:
        return one
    if 2 <= n1 <= 4:
        return few
    return many


def range_report_page(report: dict[str, Any]) -> str:
    """'Красивая' страница-сводка за произвольный период (шаги/дистанция +

    тренировки по типам, см. collectors/range_report.py) - рассчитана на то,
    чтобы её можно было расшарить/скриншотнуть/распечатать (см. @media print
    в _STYLE и кнопку печати ниже)."""
    days_total = report.get("days_total") or 0
    activities_count = report.get("activities_count") or 0

    hero = f"""
    <div class="hero-banner">
      <div class="eyebrow">Отчёт за период</div>
      <h1 class="page-title">{html.escape(_format_range_title(report['date_from'], report['date_to']))}</h1>
      <p class="page-subtitle">
        {days_total} {_ru_plural(days_total, 'день', 'дня', 'дней')} ·
        {activities_count} {_ru_plural(activities_count, 'тренировка', 'тренировки', 'тренировок')}
      </p>
    </div>
    <div class="print-hide" style="text-align:right; margin: -8px 0 20px;">
      <button type="button" class="secondary" onclick="window.print()">🖨 Сохранить как PDF / распечатать</button>
    </div>
    """

    hero_stats = f"""
    <div class="hero-stats">
      <div class="hero-stat">
        <div class="h-value">{fmt_num(report.get('steps_total'))}</div>
        <div class="h-label">Шагов всего</div>
      </div>
      <div class="hero-stat">
        <div class="h-value">{fmt_num(report.get('steps_avg_per_day'))}</div>
        <div class="h-label">Шагов в среднем / день</div>
      </div>
      <div class="hero-stat">
        <div class="h-value">{fmt_km(report.get('distance_total_m'))}</div>
        <div class="h-label">Пройдено всего (по шагам)</div>
      </div>
    </div>
    """

    by_type = report.get("by_type") or {}
    cards: list[str] = []
    for activity_type, agg in sorted(by_type.items(), key=lambda kv: -kv[1]["count"]):
        icon = activity_icon(activity_type)
        label = activity_label_ru(activity_type)
        count = agg["count"]

        stats: list[tuple[str, str]] = []
        has_distance = agg.get("total_distance_m") is not None
        if has_distance:
            stats.append((fmt_km(agg.get("total_distance_m")), "Дистанция всего"))
        stats.append((fmt_duration(agg.get("total_duration_s")), "Время всего"))
        if has_distance:
            stats.append((fmt_km(agg.get("avg_distance_m")), "Дистанция в среднем"))
        stats.append((fmt_duration(agg.get("avg_duration_s")), "Время в среднем"))
        if agg.get("avg_pace_s_per_km") is not None:
            tempo_label = "Скорость" if uses_speed_not_pace(activity_type) else "Темп"
            stats.append((fmt_tempo(agg.get("avg_pace_s_per_km"), activity_type), f"{tempo_label} в среднем"))
        if agg.get("avg_hr") is not None:
            stats.append((fmt_num(agg.get("avg_hr")), "Пульс в среднем"))

        stats_html = "".join(
            f'<div><div class="t-stat-value">{html.escape(value)}</div><div class="t-stat-label">{label_}</div></div>'
            for value, label_ in stats
        )
        cards.append(f"""
          <div class="type-card">
            <div class="t-head">
              <div class="t-icon">{icon}</div>
              <div>
                <div class="t-title">{html.escape(label)}</div>
                <div class="t-count">{count} {_ru_plural(count, 'раз', 'раза', 'раз')}</div>
              </div>
            </div>
            <div class="t-stats">{stats_html}</div>
          </div>
        """)

    type_section = ""
    if cards:
        type_section = f"""
        <div class="section-title print-hide" style="margin: 4px 0 14px;"><h2>По типам активности</h2></div>
        <div class="type-grid">{''.join(cards)}</div>
        """
    else:
        type_section = '<div class="empty">Тренировок за этот период не найдено.</div>'

    body = f"""
    <a class="back print-hide" href="/dashboard">← Назад к дашборду</a>
    {hero}
    {hero_stats}
    {type_section}
    """
    return _page(f"Отчёт {report['date_from']} – {report['date_to']}", body)


def view_page(title: str, content: str) -> str:
    body = f"""
    <a class="back" href="/dashboard">← Назад к дашборду</a>
    <div class="card">
      <div class="section-title"><h2>{html.escape(title)}</h2></div>
      <pre>{html.escape(content)}</pre>
    </div>
    """
    return _page(title, body)

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

from garmin_pipeline import ollama_setup
from garmin_pipeline.formatting import (
    activity_icon,
    activity_label,
    fmt_duration,
    fmt_km,
    fmt_num,
    fmt_tempo,
    uses_speed_not_pace,
)

# ---------------------------------------------------------------------------
# i18n - лёгкий словарь ru/en без внешних зависимостей (gettext/Babel были бы
# избыточны для десятка страниц однопользовательского локального инструмента).
# Язык хранится в cookie "lang" (см. webapp/app.py:_lang_from_request) и
# переключается ссылкой в хедере - без JS, обычный query-параметр ?lang=.
# ---------------------------------------------------------------------------

DEFAULT_LANG = "ru"

STRINGS: dict[str, dict[str, str]] = {
    "nav_dashboard": {"ru": "Дашборд", "en": "Dashboard"},
    "nav_setup": {"ru": "Настройки", "en": "Setup"},
    "title_setup": {"ru": "Настройка - Garmin Health Pipeline", "en": "Setup - Garmin Health Pipeline"},
    "title_dashboard": {"ru": "Дашборд - Garmin Health Pipeline", "en": "Dashboard - Garmin Health Pipeline"},
    "eyebrow_setup": {"ru": "Настройка", "en": "Setup"},
    "setup_title": {"ru": "Подключим твои данные", "en": "Connect your data"},
    "setup_subtitle": {
        "ru": "Garmin — для сбора метрик и тренировок. LLM и Telegram — опционально, "
        "если хочешь общаться с данными напрямую, а не только заливать файлы в ChatGPT.",
        "en": "Garmin — to collect metrics and workouts. LLM and Telegram are optional, "
        "for talking to your data directly instead of just uploading files to a ChatGPT Project.",
    },
    "status_configured": {"ru": "настроен", "en": "configured"},
    "status_not_configured": {"ru": "не настроен", "en": "not configured"},
    "status_ollama_ready": {"ru": "готова", "en": "ready"},
    "status_ollama_optional": {"ru": "опционально", "en": "optional"},
    "card_garmin_title": {"ru": "Garmin Connect", "en": "Garmin Connect"},
    "card_garmin_sub": {
        "ru": "Нужны только для первого логина — дальше используется сохранённый токен.",
        "en": "Only needed for the first login — a saved token is reused after that.",
    },
    "label_email": {"ru": "Email", "en": "Email"},
    "label_password": {"ru": "Пароль", "en": "Password"},
    "password_saved": {"ru": "пароль сохранён", "en": "password saved"},
    "password_placeholder": {"ru": "пароль", "en": "password"},
    "card_llm_title": {"ru": "LLM (BYOK/BYOM — свой ключ или модель)", "en": "LLM (BYOK/BYOM — your own key or model)"},
    "card_llm_sub": {
        "ru": "Один и тот же протокол подходит любому OpenAI-совместимому провайдеру.",
        "en": "The same protocol works with any OpenAI-compatible provider.",
    },
    "label_provider": {"ru": "Провайдер", "en": "Provider"},
    "provider_placeholder": {"ru": "— выбери пресет или впиши значения ниже —", "en": "— pick a preset or fill the fields below —"},
    "provider_cloudru": {"ru": "Cloud.ru Evolution Foundation Models (рекомендуется в РФ)", "en": "Cloud.ru Evolution Foundation Models (recommended in Russia)"},
    "provider_deepseek": {"ru": "DeepSeek (напрямую)", "en": "DeepSeek (direct)"},
    "provider_ollama": {"ru": "Ollama (локально, без ключа)", "en": "Ollama (local, no key needed)"},
    "label_base_url": {"ru": "Base URL", "en": "Base URL"},
    "label_model": {"ru": "Модель", "en": "Model"},
    "label_api_key": {"ru": "API-ключ", "en": "API key"},
    "api_key_saved": {"ru": "API-ключ сохранён", "en": "API key saved"},
    "llm_hint": {
        "ru": "OpenRouter больше не работает для пользователей из РФ без VPN — рекомендуем "
        "<a href=\"https://cloud.ru/docs/foundation-models/ug/topics/quickstart\" target=\"_blank\" rel=\"noopener\">Cloud.ru Evolution Foundation Models</a> "
        "(доступ из РФ без VPN, 20+ моделей: DeepSeek/Qwen/GigaChat) или полностью локальный "
        "Ollama/LM&nbsp;Studio, если данные не должны уходить с компьютера.",
        "en": "OpenRouter no longer works for users in Russia without a VPN — we recommend "
        "<a href=\"https://cloud.ru/docs/foundation-models/ug/topics/quickstart\" target=\"_blank\" rel=\"noopener\">Cloud.ru Evolution Foundation Models</a> "
        "(accessible from Russia without a VPN, 20+ models: DeepSeek/Qwen/GigaChat), or a fully local "
        "Ollama/LM&nbsp;Studio setup if your data shouldn't leave the machine.",
    },
    "card_ollama_title": {"ru": "Локальная модель (Ollama) — опционально", "en": "Local model (Ollama) — optional"},
    "card_ollama_sub": {
        "ru": "Данные не покидают компьютер. Ставится один раз: сама Ollama (~700 МБ) + модель (~2.5 ГБ) — ни то, ни другое не входит в этот репозиторий.",
        "en": "Data never leaves your computer. One-time install: Ollama itself (~700 MB) + a model (~2.5 GB) — neither ships with this repo.",
    },
    "ollama_checking": {"ru": "Проверяю статус...", "en": "Checking status..."},
    "btn_ollama_install": {"ru": "Установить Ollama", "en": "Install Ollama"},
    "btn_ollama_pull": {"ru": "Скачать qwen3:4b", "en": "Download qwen3:4b"},
    "ollama_after_hint": {
        "ru": "После скачивания выбери пресет «Ollama (локально)» в поле LLM выше и сохрани настройки.",
        "en": "After downloading, pick the \"Ollama (local)\" preset in the LLM field above and save settings.",
    },
    "card_telegram_title": {"ru": "Telegram-бот", "en": "Telegram bot"},
    "card_telegram_sub": {
        "ru": "Необязательно — позволяет писать боту с телефона вместо консоли.",
        "en": "Optional — lets you message the bot from your phone instead of a terminal.",
    },
    "label_bot_token": {"ru": "Bot token", "en": "Bot token"},
    "token_saved": {"ru": "токен сохранён", "en": "token saved"},
    "token_placeholder": {"ru": "создать через @BotFather", "en": "create via @BotFather"},
    "label_telegram_allowed": {"ru": "Разрешённый Telegram user id", "en": "Allowed Telegram user id"},
    "telegram_allowed_placeholder": {"ru": "оставь пустым, если бот только для тебя", "en": "leave empty if the bot is just for you"},
    "btn_save_settings": {"ru": "Сохранить настройки", "en": "Save settings"},
    "flash_settings_saved": {"ru": "Настройки сохранены", "en": "Settings saved"},
    "eyebrow_dashboard": {"ru": "Дашборд", "en": "Dashboard"},
    "dashboard_title": {"ru": "Твоя библиотека данных", "en": "Your data library"},
    "dashboard_subtitle": {
        "ru": "Собери свежий отчёт одной кнопкой и залей его в ChatGPT Project — или подключи LLM/бота ниже, чтобы общаться с данными напрямую.",
        "en": "Generate a fresh report with one click and upload it to a ChatGPT Project — or connect an LLM/bot below to talk to your data directly.",
    },
    "status_footer_link": {"ru": "Изменить настройки →", "en": "Change settings →"},
    "quick_actions_title": {"ru": "Быстрые действия", "en": "Quick actions"},
    "action_context_title": {"ru": "Снапшот", "en": "Snapshot"},
    "action_context_sub": {"ru": "Агрегат последних 14 дней для LLM", "en": "Aggregate of the last 14 days for an LLM"},
    "action_daily_title": {"ru": "Сегодня", "en": "Today"},
    "action_daily_sub": {"ru": "Дневной отчёт за текущий день", "en": "Daily report for today"},
    "action_weekly_title": {"ru": "Неделя", "en": "Week"},
    "action_weekly_sub": {"ru": "Собрать отчёт за текущую неделю", "en": "Build a report for the current week"},
    "flash_context_updated": {"ru": "Снапшот обновлён", "en": "Snapshot updated"},
    "flash_daily_ready": {"ru": "Дневной отчёт собран", "en": "Daily report ready"},
    "flash_weekly_ready": {"ru": "Недельный отчёт собран", "en": "Weekly report ready"},
    "range_report_title": {"ru": "Отчёт за период", "en": "Report for a date range"},
    "range_report_sub": {
        "ru": "Красивая сводка для публикации: шаги, дистанция и тренировки по типам за выбранные даты.",
        "en": "A shareable summary: steps, distance and workouts by type for the selected dates.",
    },
    "label_from": {"ru": "С", "en": "From"},
    "label_to": {"ru": "По", "en": "To"},
    "btn_build_report": {"ru": "Собрать отчёт", "en": "Build report"},
    "context_section_title": {"ru": "Снапшот (context.md)", "en": "Snapshot (context.md)"},
    "context_open_link": {"ru": "Открыть context.md →", "en": "Open context.md →"},
    "context_not_built": {"ru": "Ещё не сформирован — собери снапшот кнопкой выше.", "en": "Not built yet — generate a snapshot with the button above."},
    "section_weekly": {"ru": "Weekly", "en": "Weekly"},
    "section_daily": {"ru": "Daily", "en": "Daily"},
    "section_activities": {"ru": "Activities", "en": "Activities"},
    "section_monthly": {"ru": "Monthly", "en": "Monthly"},
    "no_files_yet": {"ru": "Пока нет файлов.", "en": "No files yet."},
    "back_to_dashboard": {"ru": "← Назад к дашборду", "en": "← Back to dashboard"},
    "print_pdf": {"ru": "🖨 Сохранить как PDF / распечатать", "en": "🖨 Save as PDF / print"},
    "steps_total": {"ru": "Шагов всего", "en": "Total steps"},
    "steps_avg": {"ru": "Шагов в среднем / день", "en": "Avg steps / day"},
    "distance_total_steps": {"ru": "Пройдено всего (по шагам)", "en": "Total distance (from steps)"},
    "by_type_title": {"ru": "По типам активности", "en": "By activity type"},
    "no_activities_period": {"ru": "Тренировок за этот период не найдено.", "en": "No workouts found for this period."},
    "distance_total": {"ru": "Дистанция всего", "en": "Total distance"},
    "duration_total": {"ru": "Время всего", "en": "Total time"},
    "distance_avg": {"ru": "Дистанция в среднем", "en": "Avg distance"},
    "duration_avg": {"ru": "Время в среднем", "en": "Avg time"},
    "tempo_label": {"ru": "Темп", "en": "Pace"},
    "speed_label": {"ru": "Скорость", "en": "Speed"},
    "tempo_avg_suffix": {"ru": "в среднем", "en": "avg"},
    "hr_avg": {"ru": "Пульс в среднем", "en": "Avg heart rate"},
    "error_title": {"ru": "Ошибка", "en": "Error"},
    "error_no_range": {"ru": "Не указан период (from/to).", "en": "Date range not specified (from/to)."},
    "error_bad_path": {"ru": "Некорректный путь.", "en": "Invalid path."},
    "error_file_not_found": {"ru": "Файл не найден.", "en": "File not found."},
}


def tr(key: str, lang: str) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry.get(DEFAULT_LANG) or key


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
  .lang-switch { display: flex; gap: 2px; font-size: 12px; font-weight: 600; margin-left: 6px; }
  .lang-switch a {
    color: var(--text-soft); text-decoration: none; padding: 5px 8px; border-radius: 7px;
    transition: color .15s, background .15s;
  }
  .lang-switch a:hover { color: var(--text); background: rgba(0, 0, 0, .04); }
  .lang-switch a.active { color: var(--text); background: var(--bg-soft); }
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

_OLLAMA_JS_STRINGS: dict[str, dict[str, str]] = {
    "not_responding": {"ru": "⚪ Ollama не отвечает", "en": "⚪ Ollama is not responding"},
    "binary_found_suffix": {"ru": " (бинарник найден, но сервис не запущен)", "en": " (binary found, but the service isn't running)"},
    "not_installed_suffix": {"ru": " — пока не установлена", "en": " — not installed yet"},
    "running_prefix": {"ru": "🟢 Ollama работает · моделей скачано: ", "en": "🟢 Ollama is running · models downloaded: "},
    "ready_suffix": {"ru": " готова ✅", "en": " ready ✅"},
    "not_pulled_suffix": {"ru": " пока не скачана", "en": " not downloaded yet"},
    "status_check_failed": {"ru": "Не удалось проверить статус (это нормально, если Ollama не установлена).", "en": "Couldn't check status (normal if Ollama isn't installed)."},
    "installing": {"ru": "Устанавливаю через системный пакетный менеджер (может занять пару минут)...", "en": "Installing via the system package manager (may take a couple of minutes)..."},
    "install_failed": {"ru": "Не получилось запустить установку.", "en": "Failed to start the installation."},
    "error_prefix": {"ru": "Ошибка: ", "en": "Error: "},
    "download_done": {"ru": "Готово: модель скачана ✅", "en": "Done: model downloaded ✅"},
}


def _ollama_script(lang: str) -> str:
    s = {key: entry.get(lang) or entry.get(DEFAULT_LANG) for key, entry in _OLLAMA_JS_STRINGS.items()}
    return f"""
<script>
  async function ollamaRefreshStatus() {{
    var el = document.getElementById('ollama-status');
    try {{
      var r = await fetch('/api/ollama/status');
      var s = await r.json();
      if (!s.running) {{
        el.innerHTML = {s['not_responding']!r} + (s.binary_found ? {s['binary_found_suffix']!r} : {s['not_installed_suffix']!r});
      }} else {{
        el.innerHTML = {s['running_prefix']!r} + s.models.length +
          (s.recommended_pulled ? ' · ' + s.recommended_model + {s['ready_suffix']!r} : ' · ' + s.recommended_model + {s['not_pulled_suffix']!r});
      }}
    }} catch (e) {{
      el.textContent = {s['status_check_failed']!r};
    }}
  }}
  async function ollamaInstall() {{
    var el = document.getElementById('ollama-status');
    el.textContent = {s['installing']!r};
    try {{
      var r = await fetch('/api/ollama/install', {{method: 'POST'}});
      var j = await r.json();
      el.textContent = j.message;
    }} catch (e) {{
      el.textContent = {s['install_failed']!r};
    }}
    ollamaRefreshStatus();
  }}
  async function ollamaPull() {{
    document.getElementById('ollama-progress').style.display = 'block';
    await fetch('/api/ollama/pull', {{method: 'POST'}});
    ollamaPollProgress();
  }}
  async function ollamaPollProgress() {{
    var r = await fetch('/api/ollama/pull-progress');
    var p = await r.json();
    var bar = document.getElementById('ollama-progress-bar');
    var text = document.getElementById('ollama-progress-text');
    if (p.error) {{
      text.textContent = {s['error_prefix']!r} + p.error;
      return;
    }}
    var pctKnown = (p.pct !== null && p.pct !== undefined);
    if (pctKnown) {{ bar.style.width = p.pct + '%'; }}
    text.textContent = (p.status || '') + (pctKnown ? ' · ' + p.pct + '%' : '');
    if (p.active) {{
      setTimeout(ollamaPollProgress, 1200);
    }} else if (p.done) {{
      text.textContent = {s['download_done']!r};
      bar.style.width = '100%';
      ollamaRefreshStatus();
    }}
  }}
  ollamaRefreshStatus();
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


def _lang_switch(lang: str, active_path: str) -> str:
    def cls(code: str) -> str:
        return "active" if code == lang else ""

    return (
        '<div class="lang-switch">'
        f'<a class="{cls("ru")}" href="/{active_path}?lang=ru">RU</a>'
        f'<a class="{cls("en")}" href="/{active_path}?lang=en">EN</a>'
        "</div>"
    )


def _page(title: str, body: str, *, active: str = "", lang: str = DEFAULT_LANG) -> str:
    def nav_class(path: str) -> str:
        return "active" if path == active else ""

    return f"""<!doctype html>
<html lang="{lang}">
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
      <a class="{nav_class('dashboard')}" href="/dashboard">{tr('nav_dashboard', lang)}</a>
      <a class="{nav_class('setup')}" href="/setup">{tr('nav_setup', lang)}</a>
    </nav>
    {_lang_switch(lang, active or 'dashboard')}
  </header>
  <main>{body}</main>
</body>
</html>"""


def _chip(configured: bool, lang: str, *, on_key: str = "status_configured", off_key: str = "status_not_configured") -> str:
    label = tr(on_key, lang) if configured else tr(off_key, lang)
    return f'<span class="chip {"chip-on" if configured else "chip-off"}">{label}</span>'


def _setup_status_grid(settings: Any, lang: str) -> str:
    """Сводка статуса всех интеграций сверху /setup - тот же визуальный

    язык, что на дашборде (см. dashboard_page._chip), плюс Ollama, которой
    на дашборде нет. Полезно и как честный обзор перед формой, и как
    "всё зелёное" скриншот, когда всё реально настроено."""
    ollama = ollama_setup.status()
    ollama_ready = ollama.get("running") and ollama.get("recommended_pulled")
    return f"""
    <div class="status-grid">
      <div class="status-item">
        <div class="s-icon">🔗</div>
        <div class="s-label">Garmin</div>
        {_chip(bool(settings.email), lang)}
      </div>
      <div class="status-item">
        <div class="s-icon">🧠</div>
        <div class="s-label">LLM</div>
        {_chip(settings.is_llm_configured(), lang)}
      </div>
      <div class="status-item">
        <div class="s-icon">📱</div>
        <div class="s-label">Telegram</div>
        {_chip(settings.is_telegram_configured(), lang)}
      </div>
      <div class="status-item">
        <div class="s-icon">🖥️</div>
        <div class="s-label">Ollama</div>
        {_chip(bool(ollama_ready), lang, on_key="status_ollama_ready", off_key="status_ollama_optional")}
      </div>
    </div>
    """


def setup_page(settings: Any, flash: str | None = None, lang: str = DEFAULT_LANG) -> str:
    flash_html = f'<div class="flash">✅ {html.escape(flash)}</div>' if flash else ""
    email = html.escape(settings.email or "")
    llm_base_url = html.escape(settings.llm_base_url or "")
    llm_model = html.escape(settings.llm_model or "")
    telegram_allowed = html.escape(settings.telegram_allowed_user_id or "")
    has_llm_key = tr("api_key_saved", lang) if settings.llm_api_key else "sk-..."
    has_telegram_token = tr("token_saved", lang) if settings.telegram_bot_token else tr("token_placeholder", lang)
    has_password = tr("password_saved", lang) if settings.password else tr("password_placeholder", lang)

    body = f"""
    <div class="eyebrow">{tr('eyebrow_setup', lang)}</div>
    <h1 class="page-title">{tr('setup_title', lang)}</h1>
    <p class="page-subtitle">{tr('setup_subtitle', lang)}</p>
    {_setup_status_grid(settings, lang)}
    {flash_html}
    <form method="post" action="/setup?lang={lang}">
      <div class="card">
        <div class="card-head">
          <div class="card-icon">🔗</div>
          <h2>{tr('card_garmin_title', lang)}</h2>
        </div>
        <div class="card-sub">{tr('card_garmin_sub', lang)}</div>
        <label>{tr('label_email', lang)}</label>
        <input name="garmin_email" value="{email}" placeholder="you@example.com">
        <label>{tr('label_password', lang)}</label>
        {_password_field("garmin_password", placeholder=has_password)}
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-icon">🧠</div>
          <h2>LLM (BYOK/BYOM — свой ключ или модель)</h2>
        </div>
        <div class="card-sub">Один и тот же протокол подходит любому OpenAI-совместимому провайдеру.</div>
        <label>{tr('label_provider', lang)}</label>
        <select id="llm_preset" onchange="applyLlmPreset(this)">
          <option value="">{tr('provider_placeholder', lang)}</option>
          <option value="https://foundation-models.api.cloud.ru/v1|deepseek-ai/DeepSeek-V3.1">{tr('provider_cloudru', lang)}</option>
          <option value="https://api.openai.com/v1|gpt-4o-mini">OpenAI</option>
          <option value="https://api.deepseek.com/v1|deepseek-chat">{tr('provider_deepseek', lang)}</option>
          <option value="http://localhost:11434/v1|qwen3:4b">{tr('provider_ollama', lang)}</option>
        </select>
        <div class="row">
          <div>
            <label>{tr('label_base_url', lang)}</label>
            <input name="llm_base_url" id="llm_base_url" value="{llm_base_url}" placeholder="https://api.openai.com/v1">
          </div>
          <div>
            <label>{tr('label_model', lang)}</label>
            <input name="llm_model" id="llm_model" value="{llm_model}" placeholder="gpt-4o-mini">
          </div>
        </div>
        <label>{tr('label_api_key', lang)}</label>
        {_password_field("llm_api_key", placeholder=has_llm_key)}
        <div class="hint">{tr('llm_hint', lang)}</div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-icon">🖥️</div>
          <h2>{tr('card_ollama_title', lang)}</h2>
        </div>
        <div class="card-sub">{tr('card_ollama_sub', lang)}</div>
        <div id="ollama-status" class="hint" style="margin:0 0 14px;">{tr('ollama_checking', lang)}</div>
        <div style="display:flex; gap:10px; flex-wrap:wrap;">
          <button type="button" class="secondary" onclick="ollamaInstall()">{tr('btn_ollama_install', lang)}</button>
          <button type="button" class="secondary" onclick="ollamaPull()">{tr('btn_ollama_pull', lang)}</button>
        </div>
        <div id="ollama-progress" style="display:none; margin-top:16px;">
          <div style="background: var(--bg-soft); border-radius: 999px; height: 8px; overflow: hidden;">
            <div id="ollama-progress-bar" style="background: var(--accent); height: 100%; width: 0%; transition: width .3s;"></div>
          </div>
          <div id="ollama-progress-text" class="hint" style="margin-top: 8px;"></div>
        </div>
        <div class="hint">{tr('ollama_after_hint', lang)}</div>
      </div>

      <div class="card">
        <div class="card-head">
          <div class="card-icon">📱</div>
          <h2>{tr('card_telegram_title', lang)}</h2>
        </div>
        <div class="card-sub">{tr('card_telegram_sub', lang)}</div>
        <label>{tr('label_bot_token', lang)}</label>
        {_password_field("telegram_bot_token", placeholder=has_telegram_token)}
        <label>{tr('label_telegram_allowed', lang)}</label>
        <input name="telegram_allowed_user_id" value="{telegram_allowed}" placeholder="{html.escape(tr('telegram_allowed_placeholder', lang))}">
      </div>

      <div class="save-bar">
        <button type="submit" class="primary">{tr('btn_save_settings', lang)}</button>
      </div>
    </form>
    {_SCRIPT_TOGGLE_PASSWORD}
    {_SCRIPT_LLM_PRESET}
    {_ollama_script(lang)}
    """
    return _page(tr("title_setup", lang), body, active="setup", lang=lang)


def dashboard_page(summary: dict[str, Any], settings: Any, flash: str | None = None, lang: str = DEFAULT_LANG) -> str:
    flash_html = f'<div class="flash">✅ {html.escape(flash)}</div>' if flash else ""

    def file_list(files: list[str], category: str) -> str:
        if not files:
            return f'<div class="empty">{tr("no_files_yet", lang)}</div>'
        items = "".join(
            f'<li><a href="/view?category={category}&name={html.escape(f)}"><span>{html.escape(f)}</span></a></li>'
            for f in reversed(files[-15:])
        )
        return f'<ul class="files">{items}</ul>'

    context_link = (
        f'<a href="/view?category=context&name=context.md">{tr("context_open_link", lang)}</a>'
        if summary["context_exists"]
        else f'<span class="empty">{tr("context_not_built", lang)}</span>'
    )

    today = date_cls.today()
    default_from = (today - timedelta(days=13)).isoformat()
    default_to = today.isoformat()
    range_files = summary.get("range") or []
    range_links = "".join(
        f'<li><a href="/range?from={f.removesuffix(".md").split("_")[0]}&to={f.removesuffix(".md").split("_")[1]}&lang={lang}">'
        f'<span>{html.escape(f.removesuffix(".md").replace("_", " – "))}</span></a></li>'
        for f in reversed(range_files[-10:])
    )

    body = f"""
    <div class="eyebrow">{tr('eyebrow_dashboard', lang)}</div>
    <h1 class="page-title">{tr('dashboard_title', lang)}</h1>
    <p class="page-subtitle">{tr('dashboard_subtitle', lang)}</p>
    {flash_html}

    <div class="status-grid">
      <div class="status-item">
        <div class="s-icon">🔗</div>
        <div class="s-label">Garmin</div>
        {_chip(bool(settings.email), lang)}
      </div>
      <div class="status-item">
        <div class="s-icon">🧠</div>
        <div class="s-label">LLM</div>
        {_chip(settings.is_llm_configured(), lang)}
      </div>
      <div class="status-item">
        <div class="s-icon">📱</div>
        <div class="s-label">Telegram</div>
        {_chip(settings.is_telegram_configured(), lang)}
      </div>
    </div>
    <div class="status-footer">
      <a href="/setup?lang={lang}">{tr('status_footer_link', lang)}</a>
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('quick_actions_title', lang)}</h2></div>
      <div class="action-grid">
        <form method="post" action="/dashboard/run/context?lang={lang}">
          <button type="submit" class="action-card">
            <span class="a-icon">📊</span>
            <span class="a-title">{tr('action_context_title', lang)}</span>
            <span class="a-sub">{tr('action_context_sub', lang)}</span>
          </button>
        </form>
        <form method="post" action="/dashboard/run/daily?lang={lang}">
          <button type="submit" class="action-card">
            <span class="a-icon">☀️</span>
            <span class="a-title">{tr('action_daily_title', lang)}</span>
            <span class="a-sub">{tr('action_daily_sub', lang)}</span>
          </button>
        </form>
        <form method="post" action="/dashboard/run/weekly?lang={lang}">
          <button type="submit" class="action-card">
            <span class="a-icon">📅</span>
            <span class="a-title">{tr('action_weekly_title', lang)}</span>
            <span class="a-sub">{tr('action_weekly_sub', lang)}</span>
          </button>
        </form>
      </div>
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('range_report_title', lang)}</h2></div>
      <div class="card-sub" style="margin-left:0">{tr('range_report_sub', lang)}</div>
      <form method="post" action="/dashboard/run/range?lang={lang}" class="range-form">
        <div class="row">
          <div>
            <label>{tr('label_from', lang)}</label>
            <input type="date" name="date_from" value="{default_from}" required>
          </div>
        </div>
        <div class="row">
          <div>
            <label>{tr('label_to', lang)}</label>
            <input type="date" name="date_to" value="{default_to}" required>
          </div>
        </div>
        <button type="submit" class="primary">{tr('btn_build_report', lang)}</button>
      </form>
      {f'<ul class="files" style="margin-top:16px">{range_links}</ul>' if range_links else ""}
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('context_section_title', lang)}</h2></div>
      <div class="card-sub" style="margin-left:0">{context_link}</div>
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('section_weekly', lang)}</h2><span class="count-badge">{len(summary['weekly'])}</span></div>
      {file_list(summary['weekly'], 'weekly')}
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('section_daily', lang)}</h2><span class="count-badge">{len(summary['daily'])}</span></div>
      {file_list(summary['daily'], 'daily')}
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('section_activities', lang)}</h2><span class="count-badge">{len(summary['activities'])}</span></div>
      {file_list(summary['activities'], 'activities')}
    </div>

    <div class="card">
      <div class="section-title"><h2>{tr('section_monthly', lang)}</h2><span class="count-badge">{len(summary['monthly'])}</span></div>
      {file_list(summary['monthly'], 'monthly')}
    </div>
    """
    return _page(tr("title_dashboard", lang), body, active="dashboard", lang=lang)


_MONTHS_RU_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}
_MONTHS_EN = {
    1: "January", 2: "February", 3: "March", 4: "April", 5: "May", 6: "June",
    7: "July", 8: "August", 9: "September", 10: "October", 11: "November", 12: "December",
}


def _format_range_title(date_from: str, date_to: str, lang: str) -> str:
    d1, d2 = date_cls.fromisoformat(date_from), date_cls.fromisoformat(date_to)
    if lang == "en":
        if d1.year == d2.year and d1.month == d2.month:
            return f"{_MONTHS_EN[d2.month]} {d1.day} – {d2.day}, {d2.year}"
        if d1.year == d2.year:
            return f"{_MONTHS_EN[d1.month]} {d1.day} – {_MONTHS_EN[d2.month]} {d2.day}, {d2.year}"
        return f"{_MONTHS_EN[d1.month]} {d1.day}, {d1.year} – {_MONTHS_EN[d2.month]} {d2.day}, {d2.year}"
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


def _plural(n: int, lang: str, *, ru: tuple[str, str, str], en: tuple[str, str]) -> str:
    """ru = (one, few, many) - см. _ru_plural; en = (singular, plural)."""
    if lang == "en":
        return en[0] if n == 1 else en[1]
    return _ru_plural(n, *ru)


def range_report_page(report: dict[str, Any], lang: str = DEFAULT_LANG) -> str:
    """'Красивая' страница-сводка за произвольный период (шаги/дистанция +

    тренировки по типам, см. collectors/range_report.py) - рассчитана на то,
    чтобы её можно было расшарить/скриншотнуть/распечатать (см. @media print
    в _STYLE и кнопку печати ниже)."""
    days_total = report.get("days_total") or 0
    activities_count = report.get("activities_count") or 0
    days_word = _plural(days_total, lang, ru=("день", "дня", "дней"), en=("day", "days"))
    workouts_word = _plural(activities_count, lang, ru=("тренировка", "тренировки", "тренировок"), en=("workout", "workouts"))

    hero = f"""
    <div class="hero-banner">
      <div class="eyebrow">{tr('range_report_title', lang)}</div>
      <h1 class="page-title">{html.escape(_format_range_title(report['date_from'], report['date_to'], lang))}</h1>
      <p class="page-subtitle">
        {days_total} {days_word} ·
        {activities_count} {workouts_word}
      </p>
    </div>
    <div class="print-hide" style="text-align:right; margin: -8px 0 20px;">
      <button type="button" class="secondary" onclick="window.print()">{tr('print_pdf', lang)}</button>
    </div>
    """

    hero_stats = f"""
    <div class="hero-stats">
      <div class="hero-stat">
        <div class="h-value">{fmt_num(report.get('steps_total'))}</div>
        <div class="h-label">{tr('steps_total', lang)}</div>
      </div>
      <div class="hero-stat">
        <div class="h-value">{fmt_num(report.get('steps_avg_per_day'))}</div>
        <div class="h-label">{tr('steps_avg', lang)}</div>
      </div>
      <div class="hero-stat">
        <div class="h-value">{fmt_km(report.get('distance_total_m'))}</div>
        <div class="h-label">{tr('distance_total_steps', lang)}</div>
      </div>
    </div>
    """

    by_type = report.get("by_type") or {}
    cards: list[str] = []
    for activity_type, agg in sorted(by_type.items(), key=lambda kv: -kv[1]["count"]):
        icon = activity_icon(activity_type)
        label = activity_label(activity_type, lang)
        count = agg["count"]

        stats: list[tuple[str, str]] = []
        has_distance = agg.get("total_distance_m") is not None
        if has_distance:
            stats.append((fmt_km(agg.get("total_distance_m")), tr('distance_total', lang)))
        stats.append((fmt_duration(agg.get("total_duration_s")), tr('duration_total', lang)))
        if has_distance:
            stats.append((fmt_km(agg.get("avg_distance_m")), tr('distance_avg', lang)))
        stats.append((fmt_duration(agg.get("avg_duration_s")), tr('duration_avg', lang)))
        if agg.get("avg_pace_s_per_km") is not None:
            tempo_label = tr('speed_label', lang) if uses_speed_not_pace(activity_type) else tr('tempo_label', lang)
            stats.append((fmt_tempo(agg.get("avg_pace_s_per_km"), activity_type), f"{tempo_label} {tr('tempo_avg_suffix', lang)}"))
        if agg.get("avg_hr") is not None:
            stats.append((fmt_num(agg.get("avg_hr")), tr('hr_avg', lang)))

        stats_html = "".join(
            f'<div><div class="t-stat-value">{html.escape(value)}</div><div class="t-stat-label">{label_}</div></div>'
            for value, label_ in stats
        )
        count_word = _plural(count, lang, ru=("раз", "раза", "раз"), en=("time", "times"))
        cards.append(f"""
          <div class="type-card">
            <div class="t-head">
              <div class="t-icon">{icon}</div>
              <div>
                <div class="t-title">{html.escape(label)}</div>
                <div class="t-count">{count} {count_word}</div>
              </div>
            </div>
            <div class="t-stats">{stats_html}</div>
          </div>
        """)

    type_section = ""
    if cards:
        type_section = f"""
        <div class="section-title print-hide" style="margin: 4px 0 14px;"><h2>{tr('by_type_title', lang)}</h2></div>
        <div class="type-grid">{''.join(cards)}</div>
        """
    else:
        type_section = f'<div class="empty">{tr("no_activities_period", lang)}</div>'

    body = f"""
    <a class="back print-hide" href="/dashboard?lang={lang}">{tr('back_to_dashboard', lang)}</a>
    {hero}
    {hero_stats}
    {type_section}
    """
    return _page(f"Отчёт {report['date_from']} – {report['date_to']}", body, lang=lang)


def view_page(title: str, content: str, lang: str = DEFAULT_LANG) -> str:
    body = f"""
    <a class="back" href="/dashboard?lang={lang}">{tr('back_to_dashboard', lang)}</a>
    <div class="card">
      <div class="section-title"><h2>{html.escape(title)}</h2></div>
      <pre>{html.escape(content)}</pre>
    </div>
    """
    return _page(title, body, lang=lang)

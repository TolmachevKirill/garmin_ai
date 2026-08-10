# Garmin Health Pipeline

Забирает данные из Garmin Connect, кэширует их локально и превращает в:

1. **файловую "библиотеку"** (markdown + CSV) для ручной заливки в ChatGPT
   Project — там уже есть контекст твоего образа жизни, и ChatGPT анализирует
   новые файлы на его фоне;
2. **готовый дистрибутив** (веб-интерфейс + Telegram-бот + свой LLM-ключ или
   локальная модель) — если не хочется руками таскать файлы, а хочется просто
   написать боту "как прошла неделя?" и получить ответ.

Это open-source, self-hosted проект: ни один байт твоих данных не уходит
куда-то кроме Garmin Connect и того LLM-провайдера, который ты сам укажешь
(включая полностью локальные Ollama/LM Studio — тогда не уходит вообще никуда).

## Два способа использования

| Способ | Для кого | Что делать |
|---|---|---|
| **CLI + ручная заливка в ChatGPT** | Уже пользуешься ChatGPT Projects, хочешь максимальный контроль | См. [Установка](#установка) + [Команды](#команды) |
| **Skill в Cursor/Claude Code** | Работаешь в Cursor и хочешь попросить агента словами | См. [Skill для Cursor/Claude Code](#skill-для-cursorclaude-code) |
| **Windows-дистрибутив (exe)** | Хочешь веб-дашборд и Telegram-бота без установки Python | См. [Windows-дистрибутив](#windows-дистрибутив-exe) |

## Архитектура

```
garmin_pipeline/
├── config.py             настройки: .env + data/config.json (приоритет у json)
├── client.py              логин Garmin + кэш токенов
├── cache.py               SQLite: daily_metrics, activities, raw_payloads
├── analyze.py             pandas-поверхность над кэшем + cache coverage
├── formatting.py          markdown-шаблоны (daily/weekly/context/activity)
├── library.py             запись файлов + _index.md + чтение для веб-дашборда
├── rollup.py              месячный rollup из кэша
├── llm_client.py          BYOK/BYOM обёртка над OpenAI-совместимым API
├── bot.py                 Telegram-бот (polling)
├── webapp/                FastAPI: /setup, /dashboard, /view
├── collectors/
│   ├── daily.py            биометрия + тренировки за день
│   ├── weekly.py            агрегация недели + сравнение с прошлой
│   ├── activity.py          поиск/экспорт конкретных тренировок, HR-зоны, силовые сеты (упражнения/повторы/вес)
│   ├── context.py           агрегированный снапшот N дней для LLM
│   ├── fit.py                скачивание/парсинг оригинального FIT-файла
│   └── workouts.py           запись структурированных тренировок в Garmin
└── cli.py                 точка входа (см. примеры ниже)

desktop_app.py            точка входа для Windows-дистрибутива (веб + бот)
desktop_app.spec           PyInstaller-сборка

data/                     создаётся автоматически, в git не попадает
├── config.json             настройки из веб-формы /setup (приоритет над .env)
├── tokens/                 сессия Garmin
├── cache.sqlite3           история метрик + сырые ответы Garmin API
└── library/                <- эту папку заливаешь в ChatGPT Project
    ├── daily/2026-07-12.md
    ├── weekly/2026-W28.md
    ├── monthly/2026-06.md
    ├── context/2026-07-15.md
    ├── activities/2026-07-05_trail_run.md (+.csv)
    └── _index.md
```

Ключевые решения:

- **Weekly** — по расписанию (Windows Task Scheduler), не зависит от
  daily-файлов.
- **Daily / тренировки / context** — по запросу: библиотека не забивается
  данными за каждый день, файл создаётся только когда хочется что-то
  обсудить.
- **Тренировку можно попросить выгрузить словами** — `activity
  search`/`export` ищет кандидатов по дате/типу/названию; при неоднозначности
  выводит список для уточнения вместо угадывания.
- **Raw-first кэш**: сырые ответы Garmin API сохраняются в
  `raw_payloads` до нормализации — если позже понадобится новое производное
  поле по старым датам, не нужно повторно ходить в Garmin.
- **FIT-парсинг**: для сплитов по километру пайплайн сначала пытается
  скачать и разобрать оригинальный FIT-файл активности (точнее, чем
  прореженные time-series точки из API), и только при неудаче переходит на
  синтетические сплиты по time-series.
- **BYOK/BYOM LLM**: `llm_client.py` бьёт в любой OpenAI-совместимый
  `/chat/completions` — OpenAI, [Cloud.ru Evolution Foundation
  Models](https://cloud.ru/docs/foundation-models/ug/topics/quickstart)
  (рекомендуется для РФ — OpenRouter больше недоступен без VPN), DeepSeek,
  локальный Ollama/LM Studio — один и тот же код без веток под провайдера.

## Установка

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Открой `.env` и, при желании, впиши `GARMIN_EMAIL`/`GARMIN_PASSWORD` (нужны
только для первого логина — дальше используется сохранённый токен, и их
можно удалить из `.env`). Там же — необязательные поля для LLM и
Telegram-бота (см. [BYOK/BYOM LLM и Telegram-бот](#byokbyom-llm-и-telegram-бот)),
их проще один раз настроить через веб-форму `/setup` (см. ниже), она пишет в
`data/config.json`, который имеет приоритет над `.env`.

Первый логин (может спросить код MFA):

```powershell
python -m garmin_pipeline.cli login
```

## Команды

```powershell
# Недельный отчёт (обычно запускается по расписанию, но можно и руками)
python -m garmin_pipeline.cli weekly

# Дневной отчёт по запросу
python -m garmin_pipeline.cli daily --today
python -m garmin_pipeline.cli daily --date 2026-07-12

# Агрегированный снапшот последних N дней одним файлом - удобно для LLM/бота
python -m garmin_pipeline.cli context --days 14

# "Сырой" JSON за период (дневные метрики + тренировки, без агрегации) -
# для произвольных вопросов, на которые нет готовой команды: ответ считает
# сама модель (в чате с агентом или через MCP-сервер, см. ниже), а не Python
python -m garmin_pipeline.cli export --from 2026-07-18 --to 2026-07-31

# Отчёт за произвольный период для публикации (шаги/дистанция + тренировки
# по типам с count/суммарно/в среднем) - см. также красивую страницу /range
# в веб-дашборде. Уже засинканные прошедшие дни повторно не тянутся из
# Garmin API (см. sync ниже) - только недостающие + сегодняшний день.
python -m garmin_pipeline.cli range --from 2026-07-18 --to 2026-07-31

# Фоновая синхронизация кэша за последние N дней, без записи файлов -
# держит range/weekly/context "тёплыми" (см. автоматизацию ниже)
python -m garmin_pipeline.cli sync --days 3

# Найти тренировку словами (без экспорта - только посмотреть кандидатов)
python -m garmin_pipeline.cli activity search --latest
python -m garmin_pipeline.cli activity search --from 2026-07-05 --to 2026-07-11 --type running

# Экспортировать тренировку (md + CSV точек трека, сплиты по FIT с фолбэком)
python -m garmin_pipeline.cli activity export --latest
python -m garmin_pipeline.cli activity export --date 2026-07-05 --type running
# если найдено несколько - команда выведет список и попросит уточнить --id:
python -m garmin_pipeline.cli activity export --date 2026-07-05 --id 123456789

# Свернуть старый месяц в monthly-отчёт (для чистки daily из библиотеки)
python -m garmin_pipeline.cli rollup --month 2026-06

# Пересобрать _index.md вручную
python -m garmin_pipeline.cli index

# Диагностика локального кэша: какие дни без данных за последние N дней
python -m garmin_pipeline.cli cache coverage --days 30

# Создать и запланировать структурированную тренировку в Garmin Connect
python -m garmin_pipeline.cli workout create --sport running --name "Лёгкий бег" `
    --steps-json '[{"kind":"warmup","duration_s":300},{"kind":"interval","duration_s":1200},{"kind":"cooldown","duration_s":300}]' `
    --date 2026-07-20

# "hr_zone": 1-5 на любом шаге - часы дадут оповещение (вибро/сигнал), если пульс
# выйдет за пределы этой зоны во время шага (границы зоны - из профиля пользователя
# в Garmin Connect, не задаются здесь)
python -m garmin_pipeline.cli workout create --sport running --name "Бег с оповещением Z2" `
    --steps-json '[{"kind":"warmup","duration_s":1680,"hr_zone":2},{"kind":"interval","duration_s":1200},{"kind":"cooldown","duration_s":960,"hr_zone":2}]'

# Локальный веб-интерфейс (/setup, /dashboard) - см. ниже
python -m garmin_pipeline.cli web --port 8765

# Telegram-бот (polling, блокирует процесс) - нужен настроенный telegram_bot_token
python -m garmin_pipeline.cli bot
```

## Автоматизация weekly (Windows Task Scheduler)

```powershell
.\scripts\register_weekly_task.ps1
# другое время/день:
.\scripts\register_weekly_task.ps1 -DayOfWeek Monday -Time "07:30"
```

Скрипт сам находит `python` (сначала смотрит в `.venv`, если её нет -
использует системный) и регистрирует задачу, которая раз в неделю пишет
`data/library/weekly/{ISO-неделя}.md`.

## Автоматизация daily sync (Windows Task Scheduler)

По умолчанию локальный кэш (SQLite) наполняется только как побочный эффект
явных действий (`weekly`/`daily`/`context`/`range`) - если ни разу их не
запускать, кэш пустой. Чтобы отчёт за произвольный период (`range`, страница
`/range` в дашборде) собирался мгновенно, а не тянул Garmin API за каждый
день заново - как у самого Garmin Connect, где графики за несколько дней уже
готовы, а не "пересобираются" по клику - есть отдельная фоновая задача:

```powershell
.\scripts\register_daily_sync_task.ps1
# другое время/глубина:
.\scripts\register_daily_sync_task.ps1 -Time "07:00" -Days 5
```

Она раз в день тихо синхронизирует последние N дней (`cli sync`), не пишет
никаких файлов в библиотеку. В Windows-дистрибутиве (`.exe`, см. ниже) эта же
роль у фонового потока внутри `desktop_app.py` - он сам держит кэш тёплым,
пока приложение открыто, без Task Scheduler.

## MCP-сервер (для внешних LLM-клиентов)

Помимо CLI (для Cursor - см. `.cursor/skills/garmin-health/SKILL.md`) есть
MCP-сервер (`garmin_pipeline/mcp_server.py`) - те же данные, но по протоколу
[Model Context Protocol](https://modelcontextprotocol.io/), чтобы ими мог
пользоваться любой MCP-совместимый клиент (Claude Desktop и т.п.), не только
Cursor. Инструменты отдают "сырые" данные (`get_daily_metrics`,
`get_activities`, `find_activities`, `get_activity_detail`, `sync_cache`) -
считать ответ на конкретный вопрос ("сколько я пробежал в мае") должна сама
модель, а не сервер; единственное исключение - `build_shareable_range_report`
для готового файла/страницы публикации.

Сервер работает через stdio - клиент сам поднимает процесс, отдельно
запускать `cli mcp` руками не нужно. Регистрация:

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "garmin-health-pipeline": {
      "command": "C:\\путь\\к\\garmin-health-pipeline\\.venv\\Scripts\\python.exe",
      "args": ["-m", "garmin_pipeline.cli", "mcp"],
      "cwd": "C:\\путь\\к\\garmin-health-pipeline"
    }
  }
}
```

**Cursor** (`.cursor/mcp.json` в корне проекта или в `~/.cursor/mcp.json` глобально) -
такой же формат, только ключ `mcpServers` внутри файла `mcp.json`. После
сохранения конфига перезапусти клиент - он должен показать 6 доступных
инструментов сервера `garmin-health-pipeline`.

## Как выгружать конкретную тренировку "по запросу в чате"

Идея: ты пишешь агенту (мне) в Cursor что-то вроде "выгрузи вчерашний бег"
или "выгрузи тот забег в горах на прошлой неделе" — я перевожу это в вызов
`activity search`/`activity export` с подходящими фильтрами (`--date`,
`--from/--to`, `--type`, `--name`). Если под описание подходит ровно одна
тренировка — сразу экспортирую и подкладываю файл в библиотеку. Если
несколько — показываю тебе короткий список (дата/тип/дистанция/название),
чтобы ты подтвердил нужную по `--id`.

## Skill для Cursor/Claude Code

В [.cursor/skills/garmin-health/SKILL.md](.cursor/skills/garmin-health/SKILL.md)
описаны все CLI-команды пайплайна и когда их вызывать — это позволяет
агенту в Cursor/Claude Code самому понимать, что нужно запустить `daily`,
`weekly`, `activity export` или `context`, когда ты просто попросишь словами
("покажи мой сон за последнюю неделю", "выгрузи вчерашнюю тренировку").
Skill работает поверх того же CLI, что описан выше — никакой дополнительной
установки не требует, если пайплайн уже настроен в этом репозитории.

## Дальше — заливка в ChatGPT Project

1. Заходишь в свой Project в ChatGPT (тот, где уже есть контекст про твой
   образ жизни).
2. Drag&drop новые файлы из `data/library/` (обычно — свежий `weekly/*.md`,
   и, если просил — `daily/*.md`, `context/*.md` или `activities/*.md` +
   `.csv`).
3. Раз в 1-2 месяца подчищаешь старые `daily/`-файлы, предварительно свернув
   их в `monthly/` через `rollup`, чтобы не упереться в лимит файлов проекта.

## BYOK/BYOM LLM и Telegram-бот

Если не хочется руками таскать файлы в ChatGPT, можно настроить прямой
анализ через свой API-ключ (BYOK - Bring Your Own Key) или свою локальную
модель (BYOM - Bring Your Own Model) и общаться с пайплайном через
Telegram-бота.

Настраивается через `data/config.json` (проще всего — через веб-форму
`/setup`, см. ниже) или напрямую в `.env`:

- `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — любой OpenAI-совместимый
  `/chat/completions`-эндпоинт. Веб-форма `/setup` предлагает готовые
  пресеты (выбор провайдера сам подставляет base URL и модель):
  - **[Cloud.ru Evolution Foundation Models](https://cloud.ru/docs/foundation-models/ug/topics/quickstart)**
    (`https://foundation-models.api.cloud.ru/v1`) — рекомендуется для РФ:
    работает без VPN, каталог из 20+ моделей (DeepSeek, Qwen, GigaChat,
    Llama и др.), ключ создаётся в личном кабинете за пару минут
    (Foundation Models → сервисный аккаунт → «Учётные данные доступа» →
    «Создать API-ключ»). Дефолт пайплайна, если ничего не настроено.
  - **OpenAI** (`https://api.openai.com/v1`) или **DeepSeek напрямую**
    (`https://api.deepseek.com/v1`).
  - **Локальный Ollama/LM Studio** (`http://localhost:11434/v1` и т.п.) —
    `LLM_API_KEY` не нужен, данные вообще не покидают твой компьютер.
  - ⚠️ **OpenRouter больше не работает для пользователей из РФ без VPN** —
    если он был настроен ранее, замени на один из вариантов выше.
- `TELEGRAM_BOT_TOKEN` — токен бота от [@BotFather](https://t.me/BotFather).
- `TELEGRAM_ALLOWED_USER_ID` — твой числовой Telegram user id (узнать можно
  у [@userinfobot](https://t.me/userinfobot)); если не задан, бот отвечает
  любому, кто напишет — для личного использования крайне рекомендуется
  задать.

Команды бота: `/start`, `/today`, `/week`, `/activity <запрос>`, а также
обычный текст — он идёт в `llm_client.ask(...)` вместе с последним
`context.md`, чтобы модель отвечала с учётом твоих метрик.

## Локальный веб-интерфейс

```powershell
python -m garmin_pipeline.cli web --port 8765
```

Откроет FastAPI-приложение на `http://127.0.0.1:8765`:

- **`/setup`** — форма для Garmin-логина, LLM (BYOK/BYOM) и Telegram-бота;
  пишет в `data/config.json`, подхватывается на лету без перезапуска
  (кроме Telegram-бота — см. ограничение ниже).
- **`/dashboard`** — список файлов библиотеки + кнопки "собрать
  today/week/context" без похода в консоль.
- **`/view?path=...`** — просмотр содержимого файла библиотеки в браузере.

## Windows-дистрибутив (.exe)

Для тех, кто не хочет ставить Python: `desktop_app.py` поднимает и
веб-интерфейс, и Telegram-бота (если настроен) в одном процессе и
упаковывается PyInstaller'ом в единый `.exe`.

### Собрать

```powershell
.venv\Scripts\Activate.ps1
pip install pyinstaller
pyinstaller desktop_app.spec --noconfirm
```

Результат — папка `dist/GarminHealthPipeline/` с `GarminHealthPipeline.exe`
и всеми зависимостями рядом (сборка `--onedir`, не `--onefile` — так быстрее
стартует и проще смотреть логи; см. комментарий в
[desktop_app.spec](desktop_app.spec)). Эту папку целиком можно упаковать в
zip и раздать — Python на целевой машине не нужен.

### Запустить

Просто открыть `GarminHealthPipeline.exe` — при первом запуске (нет
`data/config.json`) откроется браузер на `http://127.0.0.1:8765/setup` для
ввода Garmin/LLM/Telegram настроек; при повторных — сразу на `/dashboard`.
Порт можно переопределить переменной окружения `GARMIN_PIPELINE_PORT`.

### Известное ограничение дистрибутива

Telegram-бот запускается один раз при старте приложения. Если токен бота
добавлен или изменён через `/setup` уже во время работы — для его
подключения нужен перезапуск `.exe` (веб-интерфейс и учётные данные
Garmin/LLM подхватываются на лету, без перезапуска).

## Важные оговорки

- Это неофициальный доступ к Garmin Connect (`python-garminconnect`) — при
  изменениях на стороне Garmin логин/парсинг может потребовать обновления
  библиотеки (`pip install -U garminconnect`).
- Часть полей в `formatting.py`/`collectors/*.py` подобрана по документации
  и публичным примерам ответов Garmin API — на первом реальном запуске стоит
  сверить получившиеся markdown-файлы и, если что-то показывает "н/д" вместо
  реального значения, поправить парсинг в `collectors/daily.py` или
  `collectors/activity.py` (ключи ответа у Garmin иногда отличаются между
  типами устройств/тренировок).
- Запись тренировок в Garmin (`workout create`) использует те же
  неофициальные эндпоинты — доступность и формат шагов могут отличаться
  между типами устройств; перед регулярным использованием стоит проверить
  результат в приложении Garmin Connect.
- `data/` и `.env` не коммитятся (см. `.gitignore`) — там твои персональные
  данные, токен сессии и API-ключи. `data/config.json` (пишется веб-формой)
  туда же попадает автоматически, т.к. лежит внутри `data/`.
- Это self-hosted open-source инструмент, а не облачный сервис: всё крутится
  на твоей машине, ключи и данные никуда не отправляются кроме Garmin
  Connect и явно указанного тобой LLM-провайдера.

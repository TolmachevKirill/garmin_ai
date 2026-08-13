"""Единая точка входа пайплайна.

Примеры:
    python -m garmin_pipeline.cli login
    python -m garmin_pipeline.cli weekly
    python -m garmin_pipeline.cli daily --today
    python -m garmin_pipeline.cli daily --date 2026-07-12
    python -m garmin_pipeline.cli context --days 14
    python -m garmin_pipeline.cli range --from 2026-07-18 --to 2026-07-31
    python -m garmin_pipeline.cli sync --days 3
    python -m garmin_pipeline.cli export --from 2026-07-18 --to 2026-07-31  # сырой JSON для ad hoc вопросов
    python -m garmin_pipeline.cli mcp  # MCP-сервер для внешних LLM-клиентов (не для ручного запуска)
    python -m garmin_pipeline.cli activity search --latest
    python -m garmin_pipeline.cli activity search --date 2026-07-05 --type running
    python -m garmin_pipeline.cli activity export --latest
    python -m garmin_pipeline.cli activity export --date 2026-07-05 --id 123456789
    python -m garmin_pipeline.cli rollup --month 2026-06
    python -m garmin_pipeline.cli index
    python -m garmin_pipeline.cli cache coverage --days 30
    python -m garmin_pipeline.cli workout create --sport running --name "Лёгкий бег" \
        --steps-json '[{"kind":"warmup","duration_s":300},{"kind":"interval","duration_s":1200},{"kind":"cooldown","duration_s":300}]' \
        --date 2026-07-20
    # "hr_zone": 1-5 на шаге - часы дадут оповещение при выходе пульса за пределы зоны
    python -m garmin_pipeline.cli workout create --sport running --name "Бег с оповещением Z2" \
        --steps-json '[{"kind":"warmup","duration_s":1680,"hr_zone":2},{"kind":"interval","duration_s":1200},{"kind":"cooldown","duration_s":960,"hr_zone":2}]'
    # Силовая/кор-тренировка: "exercise" (reps ИЛИ duration_s, category+exercise_name
    # из справочника Garmin, опционально weight_kg) + "rest" между подходами
    python -m garmin_pipeline.cli workout create --sport strength_training --name "Кор" \
        --steps-json '[{"kind":"repeat","iterations":2,"steps":[{"kind":"exercise","category":"HIP_STABILITY","exercise_name":"DEAD_BUG","reps":20},{"kind":"rest","duration_s":30}]}]'
    python -m garmin_pipeline.cli web --port 8765
    python -m garmin_pipeline.cli bot
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date as date_cls
from pathlib import Path

from garmin_pipeline.analyze import coverage as cache_coverage
from garmin_pipeline.cache import get_connection, upsert_activity, upsert_daily_metrics
from garmin_pipeline.client import GarminLoginError, get_client
from garmin_pipeline.collectors.activity import (
    fetch_activity_records,
    get_exercise_sets,
    get_hr_zones,
    is_set_based_activity,
    search_activities,
    write_activity_csv,
)
from garmin_pipeline.collectors.fit import compute_km_splits_with_fallback
from garmin_pipeline.collectors.context import build_context
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.export import export_raw_range
from garmin_pipeline.collectors.range_report import build_range_report
from garmin_pipeline.collectors.sync import sync_recent_days
from garmin_pipeline.collectors.weekly import _activity_to_summary, build_weekly_report  # noqa: F401 (переиспользуем агрегатор)
from garmin_pipeline.collectors.workouts import create_and_schedule
from garmin_pipeline.formatting import (
    render_activity_md,
    render_context_md,
    render_daily_md,
    render_range_report_md,
    render_weekly_md,
)
from garmin_pipeline.library import (
    activity_csv_path,
    activity_file_stem,
    update_index,
    write_activity_md,
    write_context,
    write_daily,
    write_range_report,
    write_weekly,
)
from garmin_pipeline.rollup import build_monthly_rollup


def _print_candidates(candidates: list[dict]) -> None:
    print(json.dumps(candidates, ensure_ascii=False, indent=2, default=str))


def cmd_login(_args: argparse.Namespace) -> int:
    try:
        get_client(interactive=True)
    except GarminLoginError as err:
        print(f"Ошибка логина: {err}", file=sys.stderr)
        return 1
    print("Логин успешен, токены сохранены.")
    return 0


def cmd_weekly(args: argparse.Namespace) -> int:
    client = get_client(interactive=False)
    reference = date_cls.fromisoformat(args.date) if args.date else None
    report = build_weekly_report(client, reference)
    content = render_weekly_md(report)
    path = write_weekly(report["week_label"], content)
    update_index()
    print(f"Недельный отчёт записан: {path}")
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    client = get_client(interactive=False)
    day = args.date or date_cls.today().isoformat()
    with get_connection() as conn:
        bundle = collect_daily(client, day, with_activity_splits=True, conn=conn)
        upsert_daily_metrics(conn, bundle.to_cache_metrics())
        for act in bundle.activities:
            upsert_activity(conn, _activity_to_summary(act))
    content = render_daily_md(bundle.as_render_dict())
    path = write_daily(day, content)
    update_index()
    print(f"Дневной отчёт записан: {path}")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    client = get_client(interactive=False)
    context = build_context(client, days=args.days)
    content = render_context_md(context)
    path = write_context(content)
    update_index()
    print(f"Снапшот записан: {path}")
    return 0


def cmd_range(args: argparse.Namespace) -> int:
    client = get_client(interactive=False)
    report = build_range_report(client, args.date_from, args.date_to)
    content = render_range_report_md(report)
    path = write_range_report(args.date_from, args.date_to, content)
    update_index()
    print(f"Отчёт за период записан: {path}")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Запускает MCP-сервер (stdio) - см. mcp_server.py и README ("MCP-сервер").

    Не предназначен для запуска руками в терминале - клиент (Claude Desktop,
    Cursor и т.п.) сам поднимает этот процесс и общается с ним через stdio.
    """
    from garmin_pipeline.mcp_server import main as run_mcp_server

    run_mcp_server()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    """"Сырой" JSON за период - без готового отчёта, для ad hoc вопросов.

    Используй это (а не пиши новый агрегатор), когда пользователь просит
    что-то, для чего нет готовой команды - посчитай ответ сам по этим данным
    (см. export.py для описания единиц измерения полей).
    """
    client = get_client(interactive=False)
    payload = export_raw_range(args.date_from, args.date_to, client=client)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Фоновая синхронизация кэша без записи файлов - см. collectors/sync.py.

    Гоняется вручную или по расписанию (scripts/register_daily_sync_task.ps1),
    чтобы отчёты за произвольный период (`range`) собирались из уже тёплого
    кэша, а не тянули Garmin API заново при каждом запросе.
    """
    client = get_client(interactive=False)
    n = sync_recent_days(client, days=args.days)
    print(f"Кэш обновлён за последние {n} дн.")
    return 0


def cmd_activity_search(args: argparse.Namespace) -> int:
    client = get_client(interactive=False)
    candidates = search_activities(
        client,
        date=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        activity_type=args.type,
        name_contains=args.name,
        activity_id=args.id,
        latest=args.latest,
        limit=args.limit,
    )
    _print_candidates(candidates)
    return 0


def cmd_activity_export(args: argparse.Namespace) -> int:
    client = get_client(interactive=False)
    candidates = search_activities(
        client,
        date=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        activity_type=args.type,
        name_contains=args.name,
        activity_id=args.id,
        latest=args.latest,
        limit=args.limit,
    )

    if not candidates:
        print("Не найдено ни одной тренировки под эти фильтры.", file=sys.stderr)
        return 2

    if len(candidates) > 1:
        print(
            f"Найдено {len(candidates)} тренировок - уточни выбор через --id "
            "(id указан в каждой карточке ниже):",
            file=sys.stderr,
        )
        _print_candidates(candidates)
        return 3

    act = candidates[0]
    stem = activity_file_stem(act["date"], act.get("type"), act.get("name"))

    records = fetch_activity_records(client, act["activity_id"])
    csv_path, rows = write_activity_csv(records, activity_csv_path(stem))
    act["splits"] = compute_km_splits_with_fallback(client, act["activity_id"], records)
    act["hr_zones"] = get_hr_zones(client, act["activity_id"])
    if is_set_based_activity(act.get("type")):
        act["exercise_sets"] = get_exercise_sets(client, act["activity_id"])
    act["csv_filename"] = csv_path.name if csv_path else None

    content = render_activity_md(act)
    md_path = write_activity_md(stem, content)
    update_index()

    print(f"Markdown записан: {md_path}")
    if csv_path:
        print(f"CSV записан: {csv_path} ({rows} строк)")
    else:
        print("Секундные данные недоступны для этой активности (нет CSV).")
    return 0


def cmd_rollup(args: argparse.Namespace) -> int:
    year, month = (int(x) for x in args.month.split("-"))
    label = build_monthly_rollup(year, month)
    update_index()
    print(f"Месячный rollup записан: {label}")
    return 0


def cmd_index(_args: argparse.Namespace) -> int:
    path = update_index()
    print(f"Индекс обновлён: {path}")
    return 0


def cmd_workout_create(args: argparse.Namespace) -> int:
    if args.steps_file:
        steps = json.loads(Path(args.steps_file).read_text(encoding="utf-8"))
    elif args.steps_json:
        steps = json.loads(args.steps_json)
    else:
        print("Нужно указать --steps-json '<json>' или --steps-file path.json")
        return 1

    client = get_client(interactive=False)
    result = create_and_schedule(
        client, sport=args.sport, name=args.name, steps=steps, schedule_date=args.date
    )
    print(f"Тренировка создана в Garmin Connect: workout_id={result.get('workout_id')}")
    if args.date:
        print(f"Запланирована на {args.date}")
    return 0


def cmd_ollama_status(_args: argparse.Namespace) -> int:
    from garmin_pipeline import ollama_setup

    st = ollama_setup.status()
    print(f"Бинарник ollama в PATH: {'да' if st['binary_found'] else 'нет'}")
    print(f"Сервис отвечает (localhost:11434): {'да' if st['running'] else 'нет'}")
    if st["running"]:
        print(f"Локальные модели: {', '.join(st['models']) or '(пусто)'}")
        print(
            f"Рекомендованная модель {st['recommended_model']}: "
            f"{'скачана' if st['recommended_pulled'] else 'не скачана'}"
        )
    else:
        print(f"Установить: `python -m garmin_pipeline.cli ollama install` или {st['download_url']}")
    return 0


def cmd_ollama_install(_args: argparse.Namespace) -> int:
    from garmin_pipeline import ollama_setup

    ok, message = ollama_setup.install()
    print(message)
    return 0 if ok else 1


def cmd_ollama_pull(args: argparse.Namespace) -> int:
    from garmin_pipeline import ollama_setup

    try:
        ollama_setup.pull_model_cli(args.model or ollama_setup.RECOMMENDED_MODEL)
    except RuntimeError as err:
        print(f"Ошибка: {err}", file=sys.stderr)
        return 1
    return 0


def cmd_bot(_args: argparse.Namespace) -> int:
    from garmin_pipeline.bot import run_bot

    run_bot()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    import uvicorn

    from garmin_pipeline.webapp.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0


def cmd_cache_coverage(args: argparse.Namespace) -> int:
    df = cache_coverage(days=args.days)
    print(df.to_string(index=False))
    missing = df[~df["has_data"]]
    print(f"\nДней без данных: {len(missing)} из {len(df)}")
    if not missing.empty:
        print("Пропуски:", ", ".join(missing["date"].tolist()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="garmin_pipeline", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Разовый интерактивный логин, сохранить токены").set_defaults(func=cmd_login)

    p_weekly = sub.add_parser("weekly", help="Собрать недельный отчёт (по расписанию)")
    p_weekly.add_argument("--date", help="Любая дата внутри целевой недели (по умолчанию - сегодня)")
    p_weekly.set_defaults(func=cmd_weekly)

    p_daily = sub.add_parser("daily", help="Собрать дневной отчёт (по запросу)")
    p_daily.add_argument("--date", help="YYYY-MM-DD")
    p_daily.add_argument("--today", action="store_true", help="Использовать сегодняшнюю дату")
    p_daily.set_defaults(func=cmd_daily)

    p_context = sub.add_parser(
        "context", help="Единый агрегированный снапшот последних N дней (для быстрой заливки в LLM)"
    )
    p_context.add_argument("--days", type=int, default=14, help="Сколько последних дней включить (по умолчанию 14)")
    p_context.set_defaults(func=cmd_context)

    p_range = sub.add_parser(
        "range", help="Отчёт за произвольный период: шаги/дистанция + тренировки по типам"
    )
    p_range.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_range.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p_range.set_defaults(func=cmd_range)

    p_export = sub.add_parser(
        "export",
        help="'Сырой' JSON (дневные метрики + тренировки) за период - для ad hoc вопросов без готового отчёта",
    )
    p_export.add_argument("--from", dest="date_from", required=True, help="YYYY-MM-DD")
    p_export.add_argument("--to", dest="date_to", required=True, help="YYYY-MM-DD")
    p_export.set_defaults(func=cmd_export)

    p_sync = sub.add_parser(
        "sync", help="Фоновая синхронизация кэша за последние N дней (без записи файлов)"
    )
    p_sync.add_argument("--days", type=int, default=3, help="Сколько последних дней синхронизировать (по умолчанию 3)")
    p_sync.set_defaults(func=cmd_sync)

    p_activity = sub.add_parser("activity", help="Поиск/экспорт конкретных тренировок")
    activity_sub = p_activity.add_subparsers(dest="activity_command", required=True)

    def _add_common_activity_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--date", help="Конкретная дата YYYY-MM-DD")
        p.add_argument("--from", dest="date_from", help="Начало диапазона YYYY-MM-DD")
        p.add_argument("--to", dest="date_to", help="Конец диапазона YYYY-MM-DD")
        p.add_argument("--type", help="Тип активности (running, cycling, swimming, ...)")
        p.add_argument("--name", help="Подстрока в названии тренировки")
        p.add_argument("--id", help="Точный ID активности (для однозначного выбора)")
        p.add_argument("--latest", action="store_true", help="Только самая последняя тренировка")
        p.add_argument("--limit", type=int, default=20, help="Сколько последних тренировок просматривать")

    p_search = activity_sub.add_parser("search", help="Найти тренировки под фильтры (без экспорта)")
    _add_common_activity_filters(p_search)
    p_search.set_defaults(func=cmd_activity_search)

    p_export = activity_sub.add_parser("export", help="Найти и экспортировать тренировку (md + csv)")
    _add_common_activity_filters(p_export)
    p_export.set_defaults(func=cmd_activity_export)

    p_rollup = sub.add_parser("rollup", help="Свернуть месяц из кэша в monthly-отчёт")
    p_rollup.add_argument("--month", required=True, help="YYYY-MM")
    p_rollup.set_defaults(func=cmd_rollup)

    sub.add_parser("index", help="Пересобрать _index.md библиотеки").set_defaults(func=cmd_index)

    p_workout = sub.add_parser(
        "workout", help="Создать и (опционально) запланировать структурированную тренировку в Garmin"
    )
    workout_sub = p_workout.add_subparsers(dest="workout_command", required=True)
    p_workout_create = workout_sub.add_parser("create", help="Создать тренировку из JSON-описания шагов")
    p_workout_create.add_argument(
        "--sport",
        required=True,
        choices=["running", "cycling", "strength_training", "cardio_training", "hiit"],
    )
    p_workout_create.add_argument("--name", required=True, help="Название тренировки")
    p_workout_create.add_argument(
        "--steps-json", help='JSON-список шагов, напр. \'[{"kind":"warmup","duration_s":300}, ...]\''
    )
    p_workout_create.add_argument("--steps-file", help="Путь к .json-файлу с тем же списком шагов")
    p_workout_create.add_argument("--date", help="YYYY-MM-DD - запланировать на эту дату (иначе просто в библиотеку)")
    p_workout_create.set_defaults(func=cmd_workout_create)

    sub.add_parser(
        "bot", help="Запустить Telegram-бота (polling, блокирует процесс) - нужен telegram_bot_token"
    ).set_defaults(func=cmd_bot)

    p_web = sub.add_parser("web", help="Запустить локальный веб-интерфейс (/setup, /dashboard)")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.set_defaults(func=cmd_web)

    p_mcp = sub.add_parser(
        "mcp", help="Запустить MCP-сервер (stdio) для внешних LLM-клиентов (Claude Desktop и т.п.)"
    )
    p_mcp.set_defaults(func=cmd_mcp)

    p_cache = sub.add_parser("cache", help="Диагностика локального SQLite-кэша")
    cache_sub = p_cache.add_subparsers(dest="cache_command", required=True)
    p_coverage = cache_sub.add_parser("coverage", help="Пропуски по дням за период")
    p_coverage.add_argument("--days", type=int, default=30, help="Сколько последних дней проверить")
    p_coverage.set_defaults(func=cmd_cache_coverage)

    p_ollama = sub.add_parser(
        "ollama", help="Локальная LLM для агентного Telegram-бота (сама Ollama не часть репозитория)"
    )
    ollama_sub = p_ollama.add_subparsers(dest="ollama_command", required=True)
    ollama_sub.add_parser("status", help="Установлена/запущена ли Ollama, какие модели скачаны").set_defaults(
        func=cmd_ollama_status
    )
    ollama_sub.add_parser(
        "install", help="Best-effort автоустановка через winget/brew/install.sh"
    ).set_defaults(func=cmd_ollama_install)
    p_ollama_pull = ollama_sub.add_parser("pull", help="Скачать модель (по умолчанию - рекомендованная qwen3:4b)")
    p_ollama_pull.add_argument("--model", default=None, help="Имя модели (по умолчанию qwen3:4b)")
    p_ollama_pull.set_defaults(func=cmd_ollama_pull)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "daily" and getattr(args, "today", False):
        args.date = date_cls.today().isoformat()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

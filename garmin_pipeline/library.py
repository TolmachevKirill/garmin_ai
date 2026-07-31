"""Запись файлов в библиотеку (data/library) + обновление индекса.

Библиотека - это то, что заливается в ChatGPT Project. Структура:
    daily/2026-07-12.md          - по запросу
    weekly/2026-W28.md           - по расписанию
    monthly/2026-06.md           - rollup старых daily
    activities/2026-07-12_run.md + .csv  - по запросу
    _index.md                    - каталог, что есть в библиотеке
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from garmin_pipeline.config import settings


def slugify(text: str | None) -> str:
    if not text:
        return "activity"
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9а-я]+", "_", text, flags=re.IGNORECASE)
    return text.strip("_")[:40] or "activity"


def write_daily(date_str: str, content: str) -> Path:
    settings.ensure_dirs()
    path = settings.daily_dir / f"{date_str}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_weekly(week_label: str, content: str) -> Path:
    settings.ensure_dirs()
    path = settings.weekly_dir / f"{week_label}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_monthly(month_label: str, content: str) -> Path:
    settings.ensure_dirs()
    path = settings.monthly_dir / f"{month_label}.md"
    path.write_text(content, encoding="utf-8")
    return path


def write_context(content: str) -> Path:
    settings.ensure_dirs()
    path = settings.context_path
    path.write_text(content, encoding="utf-8")
    return path


def activity_file_stem(date_str: str, activity_type: str | None, name: str | None) -> str:
    label = name or activity_type or "activity"
    return f"{date_str}_{slugify(label)}"


def write_activity_md(stem: str, content: str) -> Path:
    settings.ensure_dirs()
    path = settings.activities_dir / f"{stem}.md"
    path.write_text(content, encoding="utf-8")
    return path


def activity_csv_path(stem: str) -> Path:
    settings.ensure_dirs()
    return settings.activities_dir / f"{stem}.csv"


def range_report_stem(date_from: str, date_to: str) -> str:
    return f"{date_from}_{date_to}"


def write_range_report(date_from: str, date_to: str, content: str) -> Path:
    settings.ensure_dirs()
    path = settings.range_dir / f"{range_report_stem(date_from, date_to)}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _list_files(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.glob("*.md"))


def library_summary() -> dict[str, Any]:
    """Компактная сводка библиотеки - для веб-дашборда (см. webapp/app.py)."""
    settings.ensure_dirs()
    return {
        "context_exists": settings.context_path.exists(),
        "daily": _list_files(settings.daily_dir),
        "weekly": _list_files(settings.weekly_dir),
        "monthly": _list_files(settings.monthly_dir),
        "activities": _list_files(settings.activities_dir),
        "range": _list_files(settings.range_dir),
    }


def read_library_file(relative_path: str) -> str | None:
    """Читает файл библиотеки по пути относительно library_root, защищаясь от

    выхода за его пределы (path traversal) - для просмотра отчётов в дашборде.
    Возвращает None, если пути не существует или он ведёт наружу.
    """
    root = settings.library_root.resolve()
    try:
        target = (root / relative_path).resolve()
        target.relative_to(root)
    except (ValueError, OSError):
        return None
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def update_index() -> Path:
    settings.ensure_dirs()

    daily_files = _list_files(settings.daily_dir)
    weekly_files = _list_files(settings.weekly_dir)
    monthly_files = _list_files(settings.monthly_dir)
    activity_files = _list_files(settings.activities_dir)
    range_files = _list_files(settings.range_dir)

    lines: list[str] = []
    lines.append("# Индекс библиотеки Garmin")
    lines.append("")
    lines.append(
        "Эту библиотеку заливаешь файлами в ChatGPT Project. "
        "daily/activities - выборочные (создаются по запросу, не за каждый день)."
    )
    lines.append("")

    lines.append("## Context (снапшот)")
    if settings.context_path.exists():
        lines.append(
            "`context.md` - агрегированный снапшот последних дней (перезаписывается "
            "при каждом запуске `cli.py context`, не история)."
        )
    else:
        lines.append("Пока не сформирован (`python -m garmin_pipeline.cli context`).")
    lines.append("")

    lines.append(f"## Weekly ({len(weekly_files)}) - автоматически по расписанию")
    if weekly_files:
        lines.append(f"Диапазон: {weekly_files[0].removesuffix('.md')} … {weekly_files[-1].removesuffix('.md')}")
    else:
        lines.append("Пока нет ни одного отчёта.")
    lines.append("")

    lines.append(f"## Monthly rollup ({len(monthly_files)})")
    if monthly_files:
        lines.append(", ".join(f.removesuffix(".md") for f in monthly_files))
    else:
        lines.append("Пока нет.")
    lines.append("")

    lines.append(f"## Daily ({len(daily_files)}) - по запросу, не сплошные даты")
    if daily_files:
        lines.append(", ".join(f.removesuffix(".md") for f in daily_files))
    else:
        lines.append("Пока нет.")
    lines.append("")

    lines.append(f"## Activities ({len(activity_files)}) - по запросу")
    if activity_files:
        lines.append(", ".join(f.removesuffix(".md") for f in activity_files))
    else:
        lines.append("Пока нет.")
    lines.append("")

    lines.append(f"## Range-отчёты ({len(range_files)}) - за произвольный период, по запросу")
    if range_files:
        lines.append(", ".join(f.removesuffix(".md") for f in range_files))
    else:
        lines.append("Пока нет.")
    lines.append("")

    content = "\n".join(lines) + "\n"
    settings.index_path.write_text(content, encoding="utf-8")
    return settings.index_path

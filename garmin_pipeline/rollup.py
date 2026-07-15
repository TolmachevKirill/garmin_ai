"""Сворачивание старых daily-данных в помесячный отчёт.

Тянет агрегаты из локального SQLite-кэша (cache.py), а не из daily-файлов
библиотеки - daily-файлы создаются выборочно по запросу, поэтому не могут
быть надёжным источником для агрегации целого месяца.
"""

from __future__ import annotations

import calendar
import statistics
from datetime import date

from garmin_pipeline.cache import get_activities_range, get_connection, get_daily_metrics_range
from garmin_pipeline.collectors.weekly import _aggregate_activities  # noqa: F401 (переиспользуем агрегатор)
from garmin_pipeline.library import write_monthly


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else None


def build_monthly_rollup(year: int, month: int) -> str:
    month_label = f"{year}-{month:02d}"
    last_day = calendar.monthrange(year, month)[1]
    date_from = date(year, month, 1).isoformat()
    date_to = date(year, month, last_day).isoformat()

    with get_connection() as conn:
        daily_rows = get_daily_metrics_range(conn, date_from, date_to)
        activity_rows = get_activities_range(conn, date_from, date_to)

    activities_agg = _aggregate_activities(activity_rows)

    lines = [
        "---",
        f"month: {month_label}",
        f"date_from: {date_from}",
        f"date_to: {date_to}",
        "---",
        "",
        f"## Месячный отчёт — {month_label}",
        "",
        f"Тренировки: {activities_agg['count']} "
        f"({', '.join(f'{v} {k}' for k, v in activities_agg['by_type'].items()) or 'нет'})",
        f"Суммарная дистанция: {(activities_agg['total_distance_m'] or 0) / 1000:.1f} км",
        f"Средний сон: {_mean([r['sleep_hours'] for r in daily_rows]) or 'н/д'} ч",
        f"Средний HRV: {_mean([r['hrv_ms'] for r in daily_rows]) or 'н/д'} мс",
        f"Средний RHR: {_mean([r['rhr'] for r in daily_rows]) or 'н/д'}",
        f"Средний стресс: {_mean([r['stress_avg'] for r in daily_rows]) or 'н/д'}",
        f"Дней с данными в кэше: {len(daily_rows)} из {last_day}",
        "",
    ]
    content = "\n".join(lines) + "\n"
    write_monthly(month_label, content)
    return month_label

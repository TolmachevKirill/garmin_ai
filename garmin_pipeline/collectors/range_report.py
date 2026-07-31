"""Агрегированный отчёт за произвольный период (не привязан к ISO-неделе и не

"последние N дней от сегодня", как context) - специально под запросы вида
"покажи мою активность с 18 по 31 июля": шаги/дистанция по дням + все
тренировки за период, агрегированные по типу активности (count/суммарно/
в среднем), а не просто список. Используется дашбордом (см. webapp/app.py,
"красивая" страница /range) и CLI-командой `range`.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from datetime import date as date_cls
from typing import Any

from garminconnect import Garmin

from garmin_pipeline.cache import (
    get_activities_range,
    get_connection,
    get_daily_metrics_range,
    upsert_activity,
    upsert_daily_metrics,
)
from garmin_pipeline.collectors.activity import daterange
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.weekly import _activity_to_summary  # noqa: F401 (переиспользуем)


def _aggregate_by_type(rows: list[dict[str, Any]] | list[sqlite3.Row]) -> dict[str, dict[str, Any]]:
    """Группирует активности по типу и считает count/суммарно/в среднем.

    Принимает как "живые" словари активностей (ключи type/distance_m/...),
    так и строки из кэша (activity_type/distance_km/...) - см. аналогичный
    приём в collectors/weekly.py::_aggregate_activities.
    """
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        row = dict(row) if isinstance(row, sqlite3.Row) else row
        activity_type = row.get("activity_type") or row.get("type") or "other"
        distance_m = row.get("distance_m")
        if distance_m is None and row.get("distance_km") is not None:
            distance_m = row["distance_km"] * 1000.0
        grouped[activity_type].append(
            {
                "distance_m": distance_m,
                "duration_s": row.get("duration_s"),
                "avg_hr": row.get("avg_hr"),
                "avg_pace_s_per_km": row.get("avg_pace_s_per_km"),
                "calories": row.get("calories"),
            }
        )

    result: dict[str, dict[str, Any]] = {}
    for activity_type, items in grouped.items():
        distances = [i["distance_m"] for i in items if i.get("distance_m")]
        durations = [i["duration_s"] for i in items if i.get("duration_s")]
        hrs = [i["avg_hr"] for i in items if i.get("avg_hr")]
        paces = [i["avg_pace_s_per_km"] for i in items if i.get("avg_pace_s_per_km")]
        calories = [i["calories"] for i in items if i.get("calories")]
        result[activity_type] = {
            "count": len(items),
            "total_distance_m": sum(distances) or None,
            "total_duration_s": sum(durations) or None,
            "avg_distance_m": (sum(distances) / len(distances)) if distances else None,
            "avg_duration_s": (sum(durations) / len(durations)) if durations else None,
            "avg_hr": round(statistics.mean(hrs)) if hrs else None,
            "avg_pace_s_per_km": (sum(paces) / len(paces)) if paces else None,
            "total_calories": sum(calories) or None,
        }
    return result


def _build_report(
    date_from: str,
    date_to: str,
    days: list[str],
    daily_table: list[dict[str, Any]],
    activities: list[dict[str, Any]] | list[sqlite3.Row],
) -> dict[str, Any]:
    steps_values = [r["steps"] for r in daily_table if r.get("steps") is not None]
    distance_values = [r["distance_m"] for r in daily_table if r.get("distance_m") is not None]
    steps_total = sum(steps_values) or None
    distance_total_m = sum(distance_values) or None

    return {
        "date_from": date_from,
        "date_to": date_to,
        "days_total": len(days),
        "days_with_steps": len(steps_values),
        "steps_total": steps_total,
        "steps_avg_per_day": round(steps_total / len(steps_values)) if steps_values else None,
        "distance_total_m": distance_total_m,
        "distance_avg_m_per_day": (distance_total_m / len(distance_values)) if distance_values else None,
        "daily_table": daily_table,
        "activities_count": len(activities),
        "by_type": _aggregate_by_type(activities),
    }


def build_range_report(client: Garmin, date_from: str, date_to: str) -> dict[str, Any]:
    """Инкрементально дособирает период и агрегирует из кэша.

    Раньше эта функция всегда перетягивала все дни периода из Garmin API -
    даже если они уже были в кэше (например, после weekly/daily-отчёта или
    предыдущего range-запроса на пересекающийся период). Это лишний трафик
    и медленно, а сама по себе выборка за произвольный период дат - базовая
    операция, которая должна быть "мгновенной" (примерно как графики за
    несколько дней в самом Garmin Connect), а не требовать пересбора каждый
    раз. Поэтому сейчас идём в API только за:
    - днями, которых ещё нет в кэше;
    - сегодняшним днём - его метрики (шаги, сон и т.д.) в течение дня ещё
      меняются, поэтому его обновляем всегда, даже если он уже был закэширован.

    Если период целиком уже синхронизирован (см. sync.py и Task Scheduler-
    задачу scripts/register_daily_sync_task.ps1) - обращений к Garmin вообще
    не будет, отчёт соберётся из локальной SQLite мгновенно.
    """
    days = daterange(date_from, date_to)
    today = date_cls.today()
    past_days = [d for d in days if date_cls.fromisoformat(d) <= today]

    with get_connection() as conn:
        cached_dates = {r["date"] for r in get_daily_metrics_range(conn, date_from, date_to)}

    missing_days = [d for d in past_days if d not in cached_dates or date_cls.fromisoformat(d) == today]

    if missing_days:
        with get_connection() as conn:
            for day in missing_days:
                bundle = collect_daily(client, day, with_activity_splits=False, conn=conn)
                upsert_daily_metrics(conn, bundle.to_cache_metrics())
                for act in bundle.activities:
                    upsert_activity(conn, _activity_to_summary(act))

    return range_report_from_cache(date_from, date_to)


def range_report_from_cache(date_from: str, date_to: str) -> dict[str, Any]:
    """Тот же отчёт, но целиком по уже закэшированным данным - без обращения

    к Garmin API вообще (не нужен даже клиент). Подходит для страницы отчёта
    (см. webapp/app.py, GET /range) после того, как период был синхронизирован
    - через build_range_report, weekly/daily/context-отчёты или фоновую
    sync.py - быстро, offline-friendly и не расходует лимиты API.
    """
    days = daterange(date_from, date_to)
    with get_connection() as conn:
        daily_rows = [dict(r) for r in get_daily_metrics_range(conn, date_from, date_to)]
        activity_rows = get_activities_range(conn, date_from, date_to)

    activities_by_date: dict[str, int] = defaultdict(int)
    for a in activity_rows:
        activities_by_date[a["date"]] += 1

    daily_table = [
        {
            "date": r["date"],
            "sleep_hours": r["sleep_hours"],
            "hrv_ms": r["hrv_ms"],
            "rhr": r["rhr"],
            "stress_avg": r["stress_avg"],
            "steps": r["steps"],
            "distance_m": r.get("distance_m"),
            "activities_count": activities_by_date.get(r["date"], 0),
        }
        for r in daily_rows
    ]
    return _build_report(date_from, date_to, days, daily_table, activity_rows)

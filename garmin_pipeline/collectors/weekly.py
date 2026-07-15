"""Недельная агрегация: тянет каждый день недели из Garmin API напрямую

(не зависит от того, создавались ли daily-файлы в библиотеке - см. README),
кэширует в SQLite и сравнивает с прошлой неделей по локальному кэшу.
"""

from __future__ import annotations

import sqlite3
import statistics
from collections import Counter
from datetime import date as date_cls
from datetime import timedelta
from typing import Any

from garminconnect import Garmin

from garmin_pipeline.cache import (
    get_activities_range,
    get_connection,
    get_daily_metrics_range,
    upsert_activity,
    upsert_daily_metrics,
)
from garmin_pipeline.cache import ActivitySummary
from garmin_pipeline.collectors.activity import daterange, resolve_week_range
from garmin_pipeline.collectors.daily import collect_daily


# Типы активностей, которые обычно не несут тренировочного сигнала (прогулки
# до метро и т.п.) - не искажают суммарную дистанцию/длительность недели, но
# остаются в кэше activities и в детальном списке дня.
LOW_SIGNAL_ACTIVITY_TYPES: set[str] = {"walking"}


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else None


def _activity_to_summary(act: dict[str, Any]) -> ActivitySummary:
    return ActivitySummary(
        activity_id=act["activity_id"],
        date=act["date"],
        activity_type=act.get("type"),
        name=act.get("name"),
        distance_km=(act["distance_m"] / 1000.0) if act.get("distance_m") else None,
        duration_s=act.get("duration_s"),
        avg_hr=act.get("avg_hr"),
        max_hr=act.get("max_hr"),
        avg_pace_s_per_km=act.get("avg_pace_s_per_km"),
        elevation_gain_m=act.get("elevation_gain_m"),
        training_effect_aerobic=act.get("training_effect_aerobic"),
        raw=act,
    )


def _aggregate_activities(
    rows: list[dict[str, Any]] | list[sqlite3.Row],
    *,
    exclude_types: set[str] = LOW_SIGNAL_ACTIVITY_TYPES,
) -> dict[str, Any]:
    by_type: Counter = Counter()
    total_distance_m = 0.0
    total_duration_s = 0.0
    count = 0
    for row in rows:
        row = dict(row) if isinstance(row, sqlite3.Row) else row
        activity_type = row.get("activity_type") or row.get("type") or "other"
        if activity_type in exclude_types:
            continue
        count += 1
        by_type[activity_type] += 1
        distance_km = row.get("distance_km")
        if distance_km:
            total_distance_m += distance_km * 1000.0
        elif row.get("distance_m"):
            total_distance_m += row["distance_m"]
        if row.get("duration_s"):
            total_duration_s += row["duration_s"]
    return {
        "count": count,
        "by_type": dict(by_type),
        "total_distance_m": total_distance_m or None,
        "total_duration_s": total_duration_s or None,
    }


def build_weekly_report(client: Garmin, reference: date_cls | None = None) -> dict[str, Any]:
    date_from, date_to, week_label = resolve_week_range(reference)
    days = daterange(date_from, date_to)

    sleep_values: list[float] = []
    hrv_values: list[float] = []
    rhr_values: list[float] = []
    stress_values: list[float] = []
    activities_raw: list[dict[str, Any]] = []
    missing_days: list[str] = []
    daily_table: list[dict[str, Any]] = []

    with get_connection() as conn:
        for day in days:
            if date_cls.fromisoformat(day) > date_cls.today():
                continue  # будущий день недели - пропускаем
            bundle = collect_daily(client, day, with_activity_splits=False, conn=conn)
            upsert_daily_metrics(conn, bundle.to_cache_metrics())
            daily_table.append(bundle.as_summary_row())

            has_any_data = any(
                v is not None
                for v in (bundle.sleep_hours, bundle.hrv_ms, bundle.rhr, bundle.stress_avg)
            ) or bool(bundle.activities)
            if not has_any_data:
                missing_days.append(day)

            if bundle.sleep_hours is not None:
                sleep_values.append(bundle.sleep_hours)
            if bundle.hrv_ms is not None:
                hrv_values.append(bundle.hrv_ms)
            if bundle.rhr is not None:
                rhr_values.append(bundle.rhr)
            if bundle.stress_avg is not None:
                stress_values.append(bundle.stress_avg)

            for act in bundle.activities:
                upsert_activity(conn, _activity_to_summary(act))
                activities_raw.append(act)

        # Предыдущая неделя - берём из кэша (могла быть заполнена прошлым запуском).
        prev_monday = date_cls.fromisoformat(date_from) - timedelta(days=7)
        prev_sunday = date_cls.fromisoformat(date_to) - timedelta(days=7)
        prev_daily_rows = get_daily_metrics_range(conn, prev_monday.isoformat(), prev_sunday.isoformat())
        prev_activity_rows = get_activities_range(conn, prev_monday.isoformat(), prev_sunday.isoformat())

    prev_sleep = _mean([r["sleep_hours"] for r in prev_daily_rows])
    prev_hrv = _mean([r["hrv_ms"] for r in prev_daily_rows])
    prev_rhr = _mean([r["rhr"] for r in prev_daily_rows])
    prev_stress = _mean([r["stress_avg"] for r in prev_daily_rows])
    prev_activities_agg = _aggregate_activities(prev_activity_rows)

    activities_agg = _aggregate_activities(activities_raw)
    activities_agg["prev_total_distance_m"] = prev_activities_agg["total_distance_m"]

    return {
        "week_label": week_label,
        "date_from": date_from,
        "date_to": date_to,
        "activities": activities_agg,
        "sleep_avg_hours": _mean(sleep_values),
        "prev_sleep_avg_hours": prev_sleep,
        "hrv_avg_ms": _mean(hrv_values),
        "prev_hrv_avg_ms": prev_hrv,
        "rhr_avg": _mean(rhr_values),
        "prev_rhr_avg": prev_rhr,
        "stress_avg": _mean(stress_values),
        "prev_stress_avg": prev_stress,
        "missing_days": missing_days,
        "daily_table": daily_table,
    }

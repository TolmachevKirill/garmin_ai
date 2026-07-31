"""Сбор дневных биометрических данных + тренировок за конкретный день.

Используется как из weekly-агрегатора (для каждого дня недели), так и
напрямую при запросе daily-отчёта по требованию.
"""

from __future__ import annotations

import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from garminconnect import Garmin

from garmin_pipeline.cache import DailyMetrics, get_connection, save_raw_payload
from garmin_pipeline.collectors.activity import fetch_activity_records, search_activities
from garmin_pipeline.collectors.fit import compute_km_splits_with_fallback
from garmin_pipeline.formatting import fmt_speed_kmh, uses_speed_not_pace


@dataclass
class DailyBundle:
    date: str
    sleep_hours: float | None = None
    sleep_deep_hours: float | None = None
    sleep_score: int | None = None
    hrv_ms: float | None = None
    hrv_status: str | None = None
    rhr: int | None = None
    stress_avg: int | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    training_readiness_score: int | None = None
    training_readiness_feedback: str | None = None
    total_steps: int | None = None
    total_distance_m: float | None = None
    total_calories: float | None = None
    active_calories: float | None = None
    activities: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_cache_metrics(self) -> DailyMetrics:
        return DailyMetrics(
            date=self.date,
            sleep_hours=self.sleep_hours,
            sleep_score=self.sleep_score,
            hrv_ms=self.hrv_ms,
            rhr=self.rhr,
            stress_avg=self.stress_avg,
            body_battery_high=self.body_battery_high,
            body_battery_low=self.body_battery_low,
            steps=self.total_steps,
            distance_m=self.total_distance_m,
            raw=self.raw,
        )

    def as_summary_row(self) -> dict[str, Any]:
        """Компактная строка дня - для таблиц по дням (weekly, context, range)."""
        return {
            "date": self.date,
            "sleep_hours": self.sleep_hours,
            "hrv_ms": self.hrv_ms,
            "rhr": self.rhr,
            "stress_avg": self.stress_avg,
            "steps": self.total_steps,
            "distance_m": self.total_distance_m,
            "activities_count": len(self.activities),
        }

    def as_render_dict(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "sleep_hours": self.sleep_hours,
            "sleep_deep_hours": self.sleep_deep_hours,
            "sleep_score": self.sleep_score,
            "hrv_ms": self.hrv_ms,
            "hrv_status": self.hrv_status,
            "rhr": self.rhr,
            "stress_avg": self.stress_avg,
            "body_battery_high": self.body_battery_high,
            "body_battery_low": self.body_battery_low,
            "training_readiness_score": self.training_readiness_score,
            "training_readiness_feedback": self.training_readiness_feedback,
            "total_steps": self.total_steps,
            "total_distance_m": self.total_distance_m,
            "total_calories": self.total_calories,
            "active_calories": self.active_calories,
            "activities": self.activities,
        }


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def collect_daily(
    client: Garmin,
    date_str: str,
    *,
    with_activity_splits: bool = True,
    conn: sqlite3.Connection | None = None,
) -> DailyBundle:
    """Собирает дневной дайджест.

    Если `conn` передан - переиспользует его (например, weekly-агрегатор уже
    держит открытое соединение на всю неделю). Если нет - открывает своё,
    короткоживущее, только чтобы сохранить raw-ответы Garmin API в
    raw_payloads (см. cache.py) - это работает независимо от того, попадёт
    ли день в daily_metrics (upsert_daily_metrics вызывающий код делает сам).
    """
    bundle = DailyBundle(date=date_str)

    with (nullcontext(conn) if conn is not None else get_connection()) as c:
        stats = _safe(client.typed.get_stats, date_str)
        if stats is not None:
            bundle.rhr = stats.resting_heart_rate
            bundle.stress_avg = stats.average_stress_level
            bundle.body_battery_high = stats.body_battery_highest_value
            bundle.body_battery_low = stats.body_battery_lowest_value
            bundle.total_steps = stats.total_steps
            bundle.total_distance_m = stats.total_distance_meters
            bundle.total_calories = stats.total_kilocalories
            bundle.active_calories = stats.active_kilocalories
            bundle.raw["stats"] = stats.model_dump(by_alias=True)
            save_raw_payload(c, "stats", date_str, bundle.raw["stats"])

        sleep = _safe(client.typed.get_sleep_data, date_str)
        if sleep is not None and sleep.daily_sleep_dto is not None:
            dto = sleep.daily_sleep_dto
            if dto.sleep_time_seconds:
                bundle.sleep_hours = round(dto.sleep_time_seconds / 3600, 2)
            if dto.deep_sleep_seconds:
                bundle.sleep_deep_hours = round(dto.deep_sleep_seconds / 3600, 2)
            if dto.sleep_scores and dto.sleep_scores.overall:
                bundle.sleep_score = dto.sleep_scores.overall.value
            bundle.raw["sleep"] = sleep.model_dump(by_alias=True)
            save_raw_payload(c, "sleep", date_str, bundle.raw["sleep"])

        hrv = _safe(client.typed.get_hrv_data, date_str)
        if hrv is not None and hrv.hrv_summary is not None:
            bundle.hrv_ms = hrv.hrv_summary.last_night_avg
            bundle.hrv_status = hrv.hrv_summary.status
            bundle.raw["hrv"] = hrv.model_dump(by_alias=True)
            save_raw_payload(c, "hrv", date_str, bundle.raw["hrv"])

        readiness_list = _safe(client.typed.get_training_readiness, date_str) or []
        if readiness_list:
            latest = max(readiness_list, key=lambda r: r.timestamp or "")
            bundle.training_readiness_score = latest.score
            bundle.training_readiness_feedback = latest.feedback_short or latest.level

        activities = search_activities(client, date=date_str)
        for act in activities:
            if with_activity_splits and act.get("distance_m"):
                records = fetch_activity_records(client, act["activity_id"], conn=c)
                splits = compute_km_splits_with_fallback(client, act["activity_id"], records, conn=c)
                if uses_speed_not_pace(act.get("type")):
                    act["splits_pace"] = [
                        fmt_speed_kmh(s["pace_s_per_km"]) for s in splits if s.get("pace_s_per_km")
                    ]
                else:
                    act["splits_pace"] = [
                        _fmt_pace(s["pace_s_per_km"]) for s in splits if s.get("pace_s_per_km")
                    ]
            bundle.activities.append(act)

    return bundle


def _fmt_pace(sec_per_km: float | None) -> str:
    if not sec_per_km:
        return "н/д"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}"

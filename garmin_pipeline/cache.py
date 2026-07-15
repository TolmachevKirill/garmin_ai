"""Локальный SQLite-кэш истории метрик и тренировок.

Нужен для того, чтобы weekly/monthly отчёты могли сравнивать текущий период
с прошлыми, даже если daily-файлы за эти дни никогда не создавались в
библиотеке (daily/activity - опциональны и генерируются по запросу, а
агрегация должна работать всегда).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from garmin_pipeline.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_metrics (
    date TEXT PRIMARY KEY,
    sleep_hours REAL,
    sleep_score INTEGER,
    hrv_ms REAL,
    rhr INTEGER,
    stress_avg INTEGER,
    body_battery_high INTEGER,
    body_battery_low INTEGER,
    steps INTEGER,
    raw_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    date TEXT,
    activity_type TEXT,
    name TEXT,
    distance_km REAL,
    duration_s REAL,
    avg_hr INTEGER,
    max_hr INTEGER,
    avg_pace_s_per_km REAL,
    elevation_gain_m REAL,
    training_effect_aerobic REAL,
    raw_json TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date);

CREATE TABLE IF NOT EXISTS raw_payloads (
    endpoint TEXT NOT NULL,
    key TEXT NOT NULL,
    payload_json TEXT,
    fetched_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (endpoint, key)
);
"""


@dataclass
class DailyMetrics:
    date: str
    sleep_hours: float | None = None
    sleep_score: int | None = None
    hrv_ms: float | None = None
    rhr: int | None = None
    stress_avg: int | None = None
    body_battery_high: int | None = None
    body_battery_low: int | None = None
    steps: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivitySummary:
    activity_id: str
    date: str
    activity_type: str | None = None
    name: str | None = None
    distance_km: float | None = None
    duration_s: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    avg_pace_s_per_km: float | None = None
    elevation_gain_m: float | None = None
    training_effect_aerobic: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path or settings.cache_db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_daily_metrics(conn: sqlite3.Connection, metrics: DailyMetrics) -> None:
    conn.execute(
        """
        INSERT INTO daily_metrics (
            date, sleep_hours, sleep_score, hrv_ms, rhr, stress_avg,
            body_battery_high, body_battery_low, steps, raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(date) DO UPDATE SET
            sleep_hours=excluded.sleep_hours,
            sleep_score=excluded.sleep_score,
            hrv_ms=excluded.hrv_ms,
            rhr=excluded.rhr,
            stress_avg=excluded.stress_avg,
            body_battery_high=excluded.body_battery_high,
            body_battery_low=excluded.body_battery_low,
            steps=excluded.steps,
            raw_json=excluded.raw_json,
            updated_at=datetime('now')
        """,
        (
            metrics.date,
            metrics.sleep_hours,
            metrics.sleep_score,
            metrics.hrv_ms,
            metrics.rhr,
            metrics.stress_avg,
            metrics.body_battery_high,
            metrics.body_battery_low,
            metrics.steps,
            json.dumps(metrics.raw, ensure_ascii=False),
        ),
    )


def upsert_activity(conn: sqlite3.Connection, activity: ActivitySummary) -> None:
    conn.execute(
        """
        INSERT INTO activities (
            activity_id, date, activity_type, name, distance_km, duration_s,
            avg_hr, max_hr, avg_pace_s_per_km, elevation_gain_m,
            training_effect_aerobic, raw_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(activity_id) DO UPDATE SET
            date=excluded.date,
            activity_type=excluded.activity_type,
            name=excluded.name,
            distance_km=excluded.distance_km,
            duration_s=excluded.duration_s,
            avg_hr=excluded.avg_hr,
            max_hr=excluded.max_hr,
            avg_pace_s_per_km=excluded.avg_pace_s_per_km,
            elevation_gain_m=excluded.elevation_gain_m,
            training_effect_aerobic=excluded.training_effect_aerobic,
            raw_json=excluded.raw_json,
            updated_at=datetime('now')
        """,
        (
            activity.activity_id,
            activity.date,
            activity.activity_type,
            activity.name,
            activity.distance_km,
            activity.duration_s,
            activity.avg_hr,
            activity.max_hr,
            activity.avg_pace_s_per_km,
            activity.elevation_gain_m,
            activity.training_effect_aerobic,
            json.dumps(activity.raw, ensure_ascii=False),
        ),
    )


def get_daily_metrics_range(conn: sqlite3.Connection, date_from: str, date_to: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM daily_metrics WHERE date >= ? AND date <= ? ORDER BY date",
        (date_from, date_to),
    )
    return cur.fetchall()


def get_activities_range(conn: sqlite3.Connection, date_from: str, date_to: str) -> list[sqlite3.Row]:
    cur = conn.execute(
        "SELECT * FROM activities WHERE date >= ? AND date <= ? ORDER BY date",
        (date_from, date_to),
    )
    return cur.fetchall()


def save_raw_payload(conn: sqlite3.Connection, endpoint: str, key: str, payload: Any) -> None:
    """Сохраняет сырой ответ Garmin API как есть, до какой-либо нормализации.

    Смысл: производные поля/отчёты можно пересчитать из raw_payloads в любой
    момент в будущем без повторного похода в Garmin API (важно из-за лимитов
    и риска бана неофициального доступа при частых запросах).
    """
    conn.execute(
        """
        INSERT INTO raw_payloads (endpoint, key, payload_json, fetched_at)
        VALUES (?, ?, ?, datetime('now'))
        ON CONFLICT(endpoint, key) DO UPDATE SET
            payload_json=excluded.payload_json,
            fetched_at=datetime('now')
        """,
        (endpoint, key, json.dumps(payload, ensure_ascii=False, default=str)),
    )


def get_raw_payload(conn: sqlite3.Connection, endpoint: str, key: str) -> Any | None:
    cur = conn.execute(
        "SELECT payload_json FROM raw_payloads WHERE endpoint = ? AND key = ?",
        (endpoint, key),
    )
    row = cur.fetchone()
    if not row or row["payload_json"] is None:
        return None
    return json.loads(row["payload_json"])


def raw_payload_keys(conn: sqlite3.Connection, endpoint: str) -> set[str]:
    """Все ключи, уже закэшированные для эндпоинта - используется в coverage-диагностике."""
    cur = conn.execute("SELECT key FROM raw_payloads WHERE endpoint = ?", (endpoint,))
    return {row["key"] for row in cur.fetchall()}

"""Скачивание и парсинг оригинального FIT-файла активности.

Точнее, чем time-series из get_activity_details (мобильный API отдаёт
урезанный/агрегированный набор метрик): в оригинальном FIT-файле есть все
поля, которые записало само устройство - высота, каденс, мощность без
дополнительного округления сервером Garmin. Используется как более точный
источник для compute_km_splits, с фолбэком на time-series API, если FIT
недоступен (ручная запись, старая активность, сетевая ошибка).
"""

from __future__ import annotations

import io
import sqlite3
import zipfile
from contextlib import nullcontext
from datetime import datetime
from typing import Any

import fitdecode
from garminconnect import Garmin

from garmin_pipeline.cache import get_connection, get_raw_payload, save_raw_payload
from garmin_pipeline.collectors.activity import compute_km_splits, compute_km_splits_from_points


def _parse_fit_bytes(fit_bytes: bytes) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with fitdecode.FitReader(io.BytesIO(fit_bytes)) as fit:
            for frame in fit:
                # FitDefinitionMessage тоже несёт frame.name == "record", но у
                # него нет .fields - только у FitDataMessage (реальные данные).
                if not isinstance(frame, fitdecode.FitDataMessage) or frame.name != "record":
                    continue
                row: dict[str, Any] = {}
                for field in frame.fields:
                    value = field.value
                    if value is None:
                        continue
                    if isinstance(value, datetime):
                        # raw_payloads хранит JSON (см. cache.save_raw_payload) - datetime
                        # сериализуется через default=str, но обратно не восстанавливается
                        # автоматически. Приводим к ISO-строке здесь же, чтобы что при первом
                        # разборе, что при чтении из кэша, fit_records_to_points получал одно
                        # и то же представление.
                        value = value.isoformat()
                    row[field.name] = value
                if row:
                    records.append(row)
    except Exception:
        return []
    return records


def _parse_fit_zip(raw: bytes) -> list[dict[str, Any]]:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            fit_names = [n for n in zf.namelist() if n.lower().endswith(".fit")]
            if not fit_names:
                return []
            fit_bytes = zf.read(fit_names[0])
    except zipfile.BadZipFile:
        fit_bytes = raw  # иногда Garmin отдаёт .fit без zip-обёртки
    return _parse_fit_bytes(fit_bytes)


def download_fit_records(
    client: Garmin, activity_id: str, *, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """Record-сообщения оригинального FIT-файла активности (timestamp, distance,

    heart_rate, altitude/enhanced_altitude, cadence, power - что есть у
    конкретного устройства). Пустой список, если FIT недоступен. Кэшируется
    в raw_payloads (endpoint "fit_records"), как и остальные дорогие вызовы.
    """
    with (nullcontext(conn) if conn is not None else get_connection()) as c:
        cached = get_raw_payload(c, "fit_records", activity_id)
        if cached is not None:
            return cached
        try:
            raw = client.download_activity(activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
        except Exception:
            return []
        records = _parse_fit_zip(raw)
        if records:
            save_raw_payload(c, "fit_records", activity_id, records)
        return records


def fit_records_to_points(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """FIT record-сообщения -> точки (elapsed_s, distance_m, hr, elevation_m)

    в формате, который понимает compute_km_splits_from_points."""
    points: list[dict[str, Any]] = []
    first_ts: datetime | None = None
    for r in records:
        distance = r.get("distance")
        ts = r.get("timestamp")
        if distance is None or ts is None:
            continue
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        if first_ts is None:
            first_ts = ts
        elapsed = (ts - first_ts).total_seconds()
        points.append(
            {
                "elapsed_s": elapsed,
                "distance_m": float(distance),
                "hr": r.get("heart_rate"),
                "elevation_m": r.get("enhanced_altitude", r.get("altitude")),
            }
        )
    points.sort(key=lambda p: p["elapsed_s"])
    return points


def compute_km_splits_from_fit(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return compute_km_splits_from_points(fit_records_to_points(records))


def compute_km_splits_with_fallback(
    client: Garmin,
    activity_id: str,
    api_records: list[dict[str, Any]],
    *,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """Сплиты по км: сначала пробуем точный оригинальный FIT, при неудаче -

    time-series API (`api_records` - то, что уже получено через
    fetch_activity_records, чтобы не дёргать API снова).
    """
    fit_records = download_fit_records(client, activity_id, conn=conn)
    if fit_records:
        fit_splits = compute_km_splits_from_fit(fit_records)
        if fit_splits:
            return fit_splits
    return compute_km_splits(api_records)

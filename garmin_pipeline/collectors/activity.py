"""Поиск и экспорт конкретных тренировок - используется по запросу (в чате).

Работает с "сырыми" (нетипизированными) методами python-garminconnect для
активностей, т.к. typed-обёртка для Activity помечена экспериментальной и не
покрывает точки трека, которые здесь и нужны.

Сплиты по км считаются синтетически - ресэмплингом time-series по накопленной
дистанции (см. compute_km_splits), а не через device-лапы Garmin
(get_activity_splits): у многих активностей (особенно велотренировок без
настроенного авто-лапа по дистанции) лапов записано мало или всего один на
всю тренировку, так что они не подходят для честных сплитов "по километру".
"""

from __future__ import annotations

import csv
import sqlite3
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date as date_cls
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from garminconnect import Garmin, GarminConnectConnectionError

from garmin_pipeline.cache import get_connection, get_raw_payload, save_raw_payload

# Ключи time-series метрик Garmin -> дружественные имена колонок CSV.
# Порядок/набор ключей у Garmin непостоянен между активностями, поэтому
# берём только то, что реально нашлось в metricDescriptors конкретной записи.
_METRIC_COLUMN_MAP: dict[str, str] = {
    "directTimestamp": "timestamp_ms",
    "sumDuration": "elapsed_s",
    "directHeartRate": "heart_rate",
    "directSpeed": "speed_mps",
    "directElevation": "elevation_m",
    "sumDistance": "distance_m",
    "directPower": "power_w",
    "directDoubleCadence": "cadence",
    "directRunCadence": "run_cadence",
    "directLatitude": "lat",
    "directLongitude": "lon",
}


@dataclass
class ActivityCandidate:
    activity_id: str
    date: str
    type: str | None
    name: str | None
    distance_m: float | None
    duration_s: float | None
    avg_hr: float | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "date": self.date,
            "type": self.type,
            "name": self.name,
            "distance_m": self.distance_m,
            "duration_s": self.duration_s,
            "avg_hr": self.avg_hr,
        }


def _normalize_activity(raw: dict[str, Any]) -> dict[str, Any]:
    activity_type = raw.get("activityType") or {}
    start_local = raw.get("startTimeLocal") or ""
    distance_m = raw.get("distance")
    duration_s = raw.get("duration")
    pace_s_per_km = None
    if distance_m and duration_s and distance_m > 0:
        pace_s_per_km = duration_s / (distance_m / 1000.0)

    return {
        "activity_id": str(raw.get("activityId")),
        "date": start_local.split(" ")[0].split("T")[0] if start_local else None,
        "start_time_local": start_local,
        "type": activity_type.get("typeKey"),
        "name": raw.get("activityName"),
        "distance_m": distance_m,
        "duration_s": duration_s,
        "avg_hr": raw.get("averageHR"),
        "max_hr": raw.get("maxHR"),
        "elevation_gain_m": raw.get("elevationGain"),
        "avg_power": raw.get("avgPower"),
        "max_power": raw.get("maxPower"),
        "training_effect_aerobic": raw.get("aerobicTrainingEffect"),
        "training_effect_anaerobic": raw.get("anaerobicTrainingEffect"),
        "avg_pace_s_per_km": pace_s_per_km,
        "calories": raw.get("calories"),
    }


def _is_subtype_error(err: Exception) -> bool:
    """Garmin's activityType filter only accepts parent categories (running,
    cycling, ...) - подтипы (jump_rope, yoga, hiit, meditation, ...) API
    отклоняет с 400 "Activity type cannot be an activity sub type"."""
    return "sub type" in str(err).lower()


def _get_activities_page(
    client: Garmin, start: int, limit: int, activity_type: str | None
) -> tuple[list[dict[str, Any]], bool]:
    """Одна страница get_activities. Возвращает (страница, filtered_server_side).

    Если activity_type - подтип, который Garmin не принимает в фильтр,
    откатывается на запрос без фильтра (страница тогда не отфильтрована -
    вызывающий код должен отфильтровать сам по нормализованному типу).
    """
    if not activity_type:
        return client.get_activities(start=start, limit=limit) or [], False
    try:
        return client.get_activities(start=start, limit=limit, activitytype=activity_type) or [], True
    except GarminConnectConnectionError as err:
        if _is_subtype_error(err):
            return client.get_activities(start=start, limit=limit) or [], False
        raise


def _paginate_activities(
    client: Garmin,
    activity_type: str | None,
    *,
    batch: int = 200,
    hard_cap: int = 5000,
    stop_on_first_match: bool = False,
) -> list[dict[str, Any]]:
    """Постранично обходит всю историю активностей (для подтипов, которые Garmin

    не умеет фильтровать на сервере). При stop_on_first_match=True
    останавливается на первом найденном совпадении (для '--latest') -
    активности идут от новых к старым, так что первое совпадение и есть
    самое последнее.
    """
    start = 0
    matches: list[dict[str, Any]] = []
    while start < hard_cap:
        page, filtered_server_side = _get_activities_page(client, start, batch, activity_type)
        if not page:
            break
        for raw in page:
            if filtered_server_side or not activity_type:
                matches.append(raw)
            else:
                type_key = (raw.get("activityType") or {}).get("typeKey")
                if type_key == activity_type:
                    matches.append(raw)
        if stop_on_first_match and matches:
            break
        if len(page) < batch:
            break
        start += batch
    return matches


def search_activities(
    client: Garmin,
    *,
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_type: str | None = None,
    name_contains: str | None = None,
    activity_id: str | None = None,
    latest: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Возвращает список кандидатов (нормализованные dict), подходящих под фильтры.

    Используется, когда пользователь описывает тренировку словами
    ("бег в горах на прошлой неделе") - сначала ищем кандидатов, и если их
    больше одного, вызывающий код (агент в чате) должен уточнить у пользователя.

    Кандидаты уже содержат все поля, нужные для markdown-экспорта - при
    однозначном совпадении можно сразу вызывать export без похода в
    ``get_activity`` (у него другая, вложенная форма ответа).
    """
    if date:
        date_from = date_to = date

    effective_limit = limit
    if activity_id and not date_from and not latest:
        effective_limit = max(limit, 200)  # widen the net for a bare-ID lookup

    if date_from:
        try:
            raw_activities = client.get_activities_by_date(date_from, date_to, activity_type)
        except GarminConnectConnectionError as err:
            if not (activity_type and _is_subtype_error(err)):
                raise
            raw_activities = client.get_activities_by_date(date_from, date_to)
            raw_activities = [
                a for a in raw_activities
                if (a.get("activityType") or {}).get("typeKey") == activity_type
            ]
    elif latest:
        raw_activities = _paginate_activities(client, activity_type, stop_on_first_match=True)
    elif activity_type:
        # Без диапазона дат, но с фильтром по типу - типичный запрос "сколько
        # всего было X" или "найди все X" - сканируем всю историю, а не только
        # последние `limit` штук, иначе легко получить 0 совпадений впустую.
        raw_activities = _paginate_activities(client, activity_type)
    else:
        raw_activities = client.get_activities(start=0, limit=effective_limit)

    candidates = [_normalize_activity(a) for a in (raw_activities or [])]

    if name_contains:
        needle = name_contains.lower()
        candidates = [c for c in candidates if needle in (c.get("name") or "").lower()]

    if activity_id:
        candidates = [c for c in candidates if c.get("activity_id") == str(activity_id)]

    if latest and candidates:
        candidates = candidates[:1]

    return candidates


def get_hr_zones(
    client: Garmin, activity_id: str, *, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """Распределение времени тренировки по пульсовым зонам.

    Сырой ответ кэшируется в raw_payloads (endpoint "hr_zones") - повторный
    запрос той же активности не бьёт по Garmin API снова.
    """
    with (nullcontext(conn) if conn is not None else get_connection()) as c:
        zones = get_raw_payload(c, "hr_zones", activity_id)
        if zones is None:
            try:
                zones = client.get_activity_hr_in_timezones(activity_id)
            except Exception:
                return []
            save_raw_payload(c, "hr_zones", activity_id, zones)

    zones = zones or []
    total_s = sum((z.get("secsInZone") or 0) for z in zones)

    result = []
    for z in zones:
        secs = z.get("secsInZone") or 0
        result.append(
            {
                "zone": z.get("zoneNumber"),
                "low_bpm": z.get("zoneLowBoundary"),
                "seconds": secs,
                "percent": round(100 * secs / total_s, 1) if total_s else 0.0,
            }
        )
    return result


# Типы активностей, у которых Garmin может распознавать отдельные силовые
# сеты (упражнение/повторы/вес) через акселерометр устройства - см.
# get_exercise_sets. Для остальных типов (бег, плавание, ...) этот эндпоинт
# всегда пустой, поэтому не дёргаем его зря.
_SET_BASED_TYPES = {
    "strength_training", "cardio_training", "indoor_cardio", "hiit",
    "crossfit", "bootcamp", "mixed_martial_arts", "boxing",
}


def is_set_based_activity(activity_type: str | None) -> bool:
    return bool(activity_type) and activity_type in _SET_BASED_TYPES


def get_exercise_sets(
    client: Garmin, activity_id: str, *, conn: sqlite3.Connection | None = None
) -> dict[str, Any]:
    """Силовые сеты (упражнение/повторы/вес) - для strength/cardio-тренировок,

    где устройство их распознаёт по акселерометру (см. is_set_based_activity).

    Сырой ответ get_activity_exercise_sets кэшируется в raw_payloads (endpoint
    "exercise_sets") - повторный запрос той же активности не бьёт по Garmin
    API снова. Возвращает {} если у активности нет сетов (не тот тип
    активности, ручная запись, старое устройство без детекции упражнений и
    т.п.) - вызывающий код должен просто пропустить рендер этого блока.

    Формат возврата:
        {
            "active_sets": int, "rest_sets": int,
            "total_active_s": float, "total_rest_s": float,
            "exercises": [
                {"name": "Curl", "sets": 3, "reps_total": 60,
                 "weight_kg": 5.0 | None, "duration_s": 240.1},
                ...
            ],
        }
    """
    with (nullcontext(conn) if conn is not None else get_connection()) as c:
        raw = get_raw_payload(c, "exercise_sets", activity_id)
        if raw is None:
            try:
                raw = client.get_activity_exercise_sets(activity_id)
            except Exception:
                return {}
            save_raw_payload(c, "exercise_sets", activity_id, raw)

    sets = (raw or {}).get("exerciseSets") or []
    if not sets:
        return {}

    def _label(exercises: list[dict[str, Any]]) -> str | None:
        if not exercises:
            return None
        best = max(exercises, key=lambda e: e.get("probability") or 0)
        category = (best.get("category") or "").replace("_", " ").strip().title()
        name = best.get("name")
        if name:
            return f"{category} ({name.replace('_', ' ').strip().title()})"
        return category or None

    exercises_agg: dict[str, dict[str, Any]] = {}
    total_active_s = 0.0
    total_rest_s = 0.0
    active_sets = 0
    rest_sets = 0

    for s in sets:
        duration = s.get("duration") or 0.0
        if s.get("setType") == "REST":
            rest_sets += 1
            total_rest_s += duration
            continue
        active_sets += 1
        total_active_s += duration
        label = _label(s.get("exercises")) or "Упражнение не распознано"
        agg = exercises_agg.setdefault(
            label,
            {"name": label, "sets": 0, "reps_total": 0, "weight_kg": None, "duration_s": 0.0},
        )
        agg["sets"] += 1
        reps = s.get("repetitionCount")
        if reps:
            agg["reps_total"] += reps
        weight = s.get("weight")
        if weight:
            # Garmin отдаёт вес в граммах.
            weight_kg = weight / 1000.0
            agg["weight_kg"] = weight_kg if agg["weight_kg"] is None else max(agg["weight_kg"], weight_kg)
        agg["duration_s"] += duration

    return {
        "active_sets": active_sets,
        "rest_sets": rest_sets,
        "total_active_s": round(total_active_s, 1),
        "total_rest_s": round(total_rest_s, 1),
        "exercises": list(exercises_agg.values()),
    }


def _extract_time_series(details: dict[str, Any]) -> list[dict[str, Any]]:
    descriptors = details.get("metricDescriptors") or []
    index_by_key = {
        d["key"]: d["metricsIndex"]
        for d in descriptors
        if isinstance(d, dict) and "key" in d and "metricsIndex" in d
    }
    rows_raw = details.get("activityDetailMetrics") or []

    records: list[dict[str, Any]] = []
    for row in rows_raw:
        values = row.get("metrics") or []
        record: dict[str, Any] = {}
        for key, idx in index_by_key.items():
            if idx < len(values):
                record[key] = values[idx]
        records.append(record)
    return records


def fetch_activity_records(
    client: Garmin, activity_id: str, *, conn: sqlite3.Connection | None = None
) -> list[dict[str, Any]]:
    """Точки трека активности (переменный интервал записи) - один запрос к API.

    Используется и для CSV-экспорта, и для расчёта сплитов по км
    (compute_km_splits) - чтобы не дёргать get_activity_details дважды.

    Сырой ответ get_activity_details кэшируется в raw_payloads (endpoint
    "activity_details") - при повторном обращении к той же тренировке (например,
    CSV уже есть, а нужны только сплиты) Garmin API не дёргается снова.
    """
    with (nullcontext(conn) if conn is not None else get_connection()) as c:
        details = get_raw_payload(c, "activity_details", activity_id)
        if details is None:
            try:
                details = client.get_activity_details(activity_id)
            except Exception:
                return []
            save_raw_payload(c, "activity_details", activity_id, details)
    return _extract_time_series(details)


def write_activity_csv(records: list[dict[str, Any]], out_path: Path) -> tuple[Path | None, int]:
    """Пишет уже полученные точки трека (см. fetch_activity_records) в CSV.

    Возвращает (путь_к_файлу|None, количество_строк). None, если у активности
    нет доступных детальных метрик (например, ручная запись без сенсоров).
    """
    if not records:
        return None, 0

    present_keys = [k for k in _METRIC_COLUMN_MAP if any(k in r for r in records)]
    if not present_keys:
        return None, 0

    columns = [_METRIC_COLUMN_MAP[k] for k in present_keys]

    first_timestamp_ms = None
    if "directTimestamp" in present_keys:
        for r in records:
            if r.get("directTimestamp") is not None:
                first_timestamp_ms = r["directTimestamp"]
                break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        header = list(columns)
        if "elapsed_s" not in header and first_timestamp_ms is not None:
            header = ["elapsed_s"] + header
        if "speed_mps" in header:
            header.append("pace_s_per_km")
        writer.writerow(header)

        for r in records:
            row = []
            elapsed_s = None
            if "sumDuration" in r:
                elapsed_s = r["sumDuration"]
            elif "directTimestamp" in r and first_timestamp_ms is not None:
                elapsed_s = (r["directTimestamp"] - first_timestamp_ms) / 1000.0

            if "elapsed_s" not in columns and first_timestamp_ms is not None:
                row.append(round(elapsed_s, 1) if elapsed_s is not None else "")

            for key in present_keys:
                value = r.get(key)
                if key == "sumDuration":
                    value = round(value, 1) if value is not None else ""
                row.append(value if value is not None else "")

            if "speed_mps" in header:
                speed = r.get("directSpeed")
                pace = round(1000.0 / speed, 1) if speed else ""
                row.append(pace)

            writer.writerow(row)

    return out_path, len(records)


def _series_points(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Точки (elapsed_s, distance_m, hr, elevation_m) для ресэмплинга по дистанции."""
    points: list[dict[str, Any]] = []
    first_timestamp_ms = None
    for r in records:
        distance = r.get("sumDistance")
        if distance is None:
            continue
        if r.get("sumDuration") is not None:
            elapsed = r["sumDuration"]
        elif r.get("directTimestamp") is not None:
            if first_timestamp_ms is None:
                first_timestamp_ms = r["directTimestamp"]
            elapsed = (r["directTimestamp"] - first_timestamp_ms) / 1000.0
        else:
            continue
        points.append(
            {
                "elapsed_s": elapsed,
                "distance_m": distance,
                "hr": r.get("directHeartRate"),
                "elevation_m": r.get("directElevation"),
            }
        )
    points.sort(key=lambda p: p["elapsed_s"])
    return points


def compute_km_splits(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сплиты по километрам из time-series API (get_activity_details).

    См. compute_km_splits_from_points - здесь только конвертация "сырых"
    records в точки (elapsed_s/distance_m/hr/elevation_m).
    """
    return compute_km_splits_from_points(_series_points(records))


def compute_km_splits_from_points(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сплиты по километрам, посчитанные ресэмплингом трека по дистанции.

    Не использует device-лапы Garmin (get_activity_splits) - у многих
    активностей (особенно велотренировок без авто-лапа по дистанции) лапов
    записано мало или всего один на всю тренировку, поэтому они не дают
    честных сплитов "по километру". Здесь вместо этого берём накопленную
    дистанцию из точек трека (либо time-series API, либо FIT - см.
    collectors/fit.py) и сами находим момент пересечения каждой границы в
    1000м (линейная интерполяция времени между соседними точками), а
    HR/набор высоты - усреднением/разницей точек внутри сегмента.

    `points` - список dict с ключами elapsed_s, distance_m, hr, elevation_m,
    отсортированный по elapsed_s (см. _series_points и fit.fit_records_to_points).
    """
    if len(points) < 2:
        return []

    max_distance = points[-1]["distance_m"]
    if not max_distance or max_distance < 200:
        return []

    def elapsed_at(distance_target: float) -> float:
        for i in range(1, len(points)):
            if points[i]["distance_m"] >= distance_target:
                p0, p1 = points[i - 1], points[i]
                d0, d1 = p0["distance_m"], p1["distance_m"]
                if d1 == d0:
                    return p1["elapsed_s"]
                frac = (distance_target - d0) / (d1 - d0)
                return p0["elapsed_s"] + frac * (p1["elapsed_s"] - p0["elapsed_s"])
        return points[-1]["elapsed_s"]

    def segment_stats(dist_from: float, dist_to: float) -> tuple[float | None, float | None]:
        seg = [p for p in points if dist_from <= p["distance_m"] <= dist_to]
        hr_values = [p["hr"] for p in seg if p.get("hr") is not None]
        ele_values = [p["elevation_m"] for p in seg if p.get("elevation_m") is not None]
        avg_hr = round(sum(hr_values) / len(hr_values)) if hr_values else None
        elevation_gain = round(max(0.0, ele_values[-1] - ele_values[0]), 1) if len(ele_values) >= 2 else None
        return avg_hr, elevation_gain

    splits: list[dict[str, Any]] = []
    prev_elapsed = 0.0
    prev_distance = 0.0
    full_km_count = int(max_distance // 1000)

    for km in range(1, full_km_count + 1):
        target = km * 1000.0
        elapsed_at_target = elapsed_at(target)
        avg_hr, elevation_gain = segment_stats(prev_distance, target)
        duration_s = elapsed_at_target - prev_elapsed
        splits.append(
            {
                "index": str(km),
                "distance_m": target - prev_distance,
                "duration_s": duration_s,
                "pace_s_per_km": duration_s if duration_s > 0 else None,
                "avg_hr": avg_hr,
                "elevation_gain_m": elevation_gain,
            }
        )
        prev_elapsed = elapsed_at_target
        prev_distance = target

    remaining = max_distance - prev_distance
    if remaining > 100:
        avg_hr, elevation_gain = segment_stats(prev_distance, max_distance)
        duration_s = points[-1]["elapsed_s"] - prev_elapsed
        pace_s_per_km = duration_s / (remaining / 1000.0) if remaining > 0 else None
        splits.append(
            {
                "index": f"{full_km_count + 1} (частично, {remaining:.0f} м)",
                "distance_m": remaining,
                "duration_s": duration_s,
                "pace_s_per_km": pace_s_per_km,
                "avg_hr": avg_hr,
                "elevation_gain_m": elevation_gain,
            }
        )

    return splits


def resolve_week_range(reference: date_cls | None = None) -> tuple[str, str, str]:
    """ISO-неделя (пн-вс), содержащая reference (по умолчанию - сегодня).

    Возвращает (date_from, date_to, week_label), например
    ("2026-07-06", "2026-07-12", "2026-W28").
    """
    ref = reference or date_cls.today()
    monday = ref - timedelta(days=ref.weekday())
    sunday = monday + timedelta(days=6)
    iso_year, iso_week, _ = ref.isocalendar()
    return monday.isoformat(), sunday.isoformat(), f"{iso_year}-W{iso_week:02d}"


def daterange(date_from: str, date_to: str) -> list[str]:
    start = datetime.strptime(date_from, "%Y-%m-%d").date()
    end = datetime.strptime(date_to, "%Y-%m-%d").date()
    days = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days

"""'Сырой' экспорт данных за произвольный период - без готового отчёта.

В отличие от weekly/context/range_report (каждый - под конкретный, заранее
придуманный формат: неделя, снапшот для LLM, публикация), этот модуль не
агрегирует ничего сам - просто отдаёт дневные метрики и тренировки за период
как plain dict/list. Это generic-примитив специально под ad hoc вопросы вида
"сколько я пробежал в мае" или "сравни эти две недели по среднему пульсу" -
ответ на них считает сам вызывающий (LLM-агент через SKILL.md, или внешний
MCP-клиент через mcp_server.py), а не заранее написанный Python-агрегатор.

Используется:
- CLI-командой `export` (см. cli.py) - печатает JSON в stdout;
- MCP-инструментами get_daily_metrics/get_activities (см. mcp_server.py).
"""

from __future__ import annotations

from typing import Any

from garminconnect import Garmin

from garmin_pipeline.cache import get_activities_range, get_connection, get_daily_metrics_range
from garmin_pipeline.collectors.sync import ensure_range_synced

# Отдаём только "чистые" поля - без raw_json (полный сырой ответ Garmin API,
# см. cache.py) и служебных updated_at/PRIMARY KEY-деталей: агенту, который
# сам считает ad hoc метрику, не нужен мусор, из-за которого легко промахнуться
# с единицами измерения или утонуть в токенах на бесполезных данных.
DAILY_FIELDS = (
    "date", "sleep_hours", "sleep_score", "hrv_ms", "rhr", "stress_avg",
    "body_battery_high", "body_battery_low", "steps", "distance_m",
)
ACTIVITY_FIELDS = (
    "activity_id", "date", "activity_type", "name", "distance_km", "duration_s",
    "avg_hr", "max_hr", "avg_pace_s_per_km", "elevation_gain_m",
    "training_effect_aerobic", "calories",
)


def _pick(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    return {f: row.get(f) for f in fields}


def export_raw_range(date_from: str, date_to: str, *, client: Garmin | None = None) -> dict[str, Any]:
    """Дневные метрики + тренировки за период, без округлений/пересчёта единиц.

    Единицы: distance_m/distance_km - метры/километры, duration_s - секунды,
    avg_pace_s_per_km - секунд на км (для бега/ходьбы) или интерпретируй как
    скорость через 3600/avg_pace_s_per_km км/ч (для велоактивностей),
    sleep_hours - часы, hrv_ms - миллисекунды, steps - штуки.

    Если передан `client` - сначала дособирает недостающие дни периода из
    Garmin API (см. ensure_range_synced в sync.py); без client читает только
    то, что уже в локальном кэше (может быть неполным).
    """
    if client is not None:
        ensure_range_synced(client, date_from, date_to)

    with get_connection() as conn:
        daily_rows = [dict(r) for r in get_daily_metrics_range(conn, date_from, date_to)]
        activity_rows = [dict(r) for r in get_activities_range(conn, date_from, date_to)]

    return {
        "date_from": date_from,
        "date_to": date_to,
        "daily": [_pick(r, DAILY_FIELDS) for r in daily_rows],
        "activities": [_pick(r, ACTIVITY_FIELDS) for r in activity_rows],
    }

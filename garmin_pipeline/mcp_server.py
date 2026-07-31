"""MCP-сервер поверх garmin_pipeline - те же generic-примитивы, что и CLI

`export`/`sync`/`activity search`, но по протоколу Model Context Protocol -
для внешних LLM-клиентов (Claude Desktop, другие MCP-совместимые агенты),
которые не могут вызвать локальный CLI напрямую, в отличие от Cursor (там
для этого есть .cursor/skills/garmin-health/SKILL.md).

Инструменты отдают "сырые" данные, а не готовые отчёты - решение "что и как
посчитать" оставлено вызывающей модели (см. export.py и обоснование в
README/SKILL.md - раздел "Ad hoc аналитические запросы"). Единственное
исключение - build_shareable_range_report, которая создаёт готовую
markdown/HTML-страницу для публикации (для этого нужен фиксированный формат,
не имеет смысла заставлять каждую модель заново придумывать вёрстку).

Запуск (stdio-транспорт - клиент сам поднимает процесс):
    python -m garmin_pipeline.cli mcp

Регистрация в Claude Desktop / Cursor - см. README, раздел "MCP-сервер".
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from garmin_pipeline.client import get_client
from garmin_pipeline.collectors.activity import fetch_activity_records, get_hr_zones, search_activities
from garmin_pipeline.collectors.export import export_raw_range
from garmin_pipeline.collectors.fit import compute_km_splits_with_fallback
from garmin_pipeline.collectors.range_report import build_range_report
from garmin_pipeline.collectors.sync import sync_recent_days
from garmin_pipeline.formatting import render_range_report_md
from garmin_pipeline.library import write_range_report

mcp = FastMCP(
    "garmin-health-pipeline",
    instructions=(
        "Инструменты для чтения личных данных пользователя из Garmin Connect: сон, HRV, "
        "RHR, стресс, Body Battery, шаги, дистанция, тренировки. Для произвольных "
        "аналитических запросов ('сколько я пробежал в мае', 'сравни эти две недели по "
        "среднему пульсу', 'сколько было силовых тренировок') используй get_daily_metrics "
        "и/или get_activities и посчитай ответ сам - это сырые данные за период, а не "
        "готовый отчёт под конкретный вопрос. build_shareable_range_report нужен только "
        "когда пользователь явно просит красивую страницу/файл для публикации/шаринга."
    ),
)


@mcp.tool()
def get_daily_metrics(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Дневные метрики за период (включительно), по одной записи на день.

    Поля: date, sleep_hours, sleep_score (0-100), hrv_ms, rhr (уд/мин),
    stress_avg (0-100), body_battery_high/low (0-100), steps, distance_m
    (дистанция за день по шагам, метры). Отсутствующее поле = None (нет
    данных за этот день/метрика недоступна на устройстве).

    Автоматически дособирает из Garmin недостающие дни периода - при первом
    запросе за новый период может занять время, при повторном по тому же/
    пересекающемуся периоду отвечает мгновенно из локального кэша.
    """
    client = get_client(interactive=False)
    payload = export_raw_range(date_from, date_to, client=client)
    return payload["daily"]


@mcp.tool()
def get_activities(date_from: str, date_to: str, activity_type: str | None = None) -> list[dict[str, Any]]:
    """Тренировки за период (включительно), одна запись на тренировку.

    Поля: activity_id, date, activity_type (running/cycling/strength_training/
    jump_rope/... - как в Garmin), name, distance_km, duration_s, avg_hr,
    max_hr, avg_pace_s_per_km (для скорости в км/ч на велоактивностях: 3600 /
    avg_pace_s_per_km), elevation_gain_m, training_effect_aerobic (0-5),
    calories. activity_type - опциональный фильтр по точному типу.
    """
    client = get_client(interactive=False)
    payload = export_raw_range(date_from, date_to, client=client)
    activities = payload["activities"]
    if activity_type:
        activities = [a for a in activities if (a.get("activity_type") or "").lower() == activity_type.lower()]
    return activities


@mcp.tool()
def find_activities(
    date: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_type: str | None = None,
    name_contains: str | None = None,
    latest: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Ищет конкретные тренировки по фильтрам (для вопросов вида "та пробежка

    в горах на прошлой неделе" или "последняя тренировка") - в отличие от
    get_activities, тут можно искать по имени/типу без указания периода и
    получить activity_id для get_activity_detail. `latest=true` вернёт самую
    последнюю тренировку без прочих фильтров."""
    client = get_client(interactive=False)
    return search_activities(
        client,
        date=date,
        date_from=date_from,
        date_to=date_to,
        activity_type=activity_type,
        name_contains=name_contains,
        latest=latest,
        limit=limit,
    )


@mcp.tool()
def get_activity_detail(activity_id: str) -> dict[str, Any]:
    """Полная детализация одной тренировки по её activity_id (см. find_activities):

    сплиты по км (из оригинального FIT-файла, с фолбэком на пересчёт из
    time-series) и распределение по пульсовым зонам, в дополнение к базовым
    полям из get_activities."""
    client = get_client(interactive=False)
    candidates = search_activities(client, activity_id=activity_id, limit=1)
    if not candidates:
        return {"error": f"Тренировка с activity_id={activity_id} не найдена"}
    act = candidates[0]
    records = fetch_activity_records(client, activity_id)
    act["splits"] = compute_km_splits_with_fallback(client, activity_id, records)
    act["hr_zones"] = get_hr_zones(client, activity_id)
    return act


@mcp.tool()
def sync_cache(days: int = 3) -> str:
    """Синхронизирует последние N дней в локальный кэш без анализа - обычно

    не нужно вызывать вручную: get_daily_metrics/get_activities и так
    дособирают недостающее сами. Полезно перед серией запросов, чтобы
    прогреть кэш заранее одним вызовом."""
    client = get_client(interactive=False)
    n = sync_recent_days(client, days=days)
    return f"Синхронизировано {n} дн. в локальный кэш."


@mcp.tool()
def build_shareable_range_report(date_from: str, date_to: str) -> dict[str, Any]:
    """Готовит markdown-файл + агрегаты (шаги/дистанция всего и в среднем,

    тренировки по типам с count/суммарно/в среднем) для публикации/шаринга за
    период - используй, только если пользователь явно просит красивый отчёт/
    файл/страницу для публикации, а не для обычных аналитических вопросов
    (для них используй get_daily_metrics/get_activities и посчитай сам).
    Файл также открывается как HTML-страница в веб-дашборде на /range."""
    client = get_client(interactive=False)
    report = build_range_report(client, date_from, date_to)
    path = write_range_report(date_from, date_to, render_range_report_md(report))
    return {"markdown_path": str(path), **report}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

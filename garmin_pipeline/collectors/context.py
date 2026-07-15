"""Единый агрегированный снапшот для LLM - последние N дней сразу.

В отличие от daily/weekly (выборочные - по расписанию или по одному запросу),
context собирает сразу всё релевантное за период в один файл: биометрию по
дням + все тренировки за этот период. Нужен для случаев "дай мне сейчас всё
важное" одним файлом, без похода за тремя разными командами по отдельности.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta
from typing import Any

from garminconnect import Garmin

from garmin_pipeline.cache import get_connection, upsert_activity, upsert_daily_metrics
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.weekly import _activity_to_summary  # noqa: F401 (переиспользуем)


def build_context(client: Garmin, *, days: int = 14) -> dict[str, Any]:
    today = date_cls.today()
    date_from = today - timedelta(days=days - 1)

    daily_table: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []

    with get_connection() as conn:
        for offset in range(days):
            day = date_from + timedelta(days=offset)
            if day > today:
                continue
            bundle = collect_daily(client, day.isoformat(), with_activity_splits=False, conn=conn)
            upsert_daily_metrics(conn, bundle.to_cache_metrics())
            daily_table.append(bundle.as_summary_row())
            for act in bundle.activities:
                upsert_activity(conn, _activity_to_summary(act))
                activities.append(act)

    return {
        "date_from": date_from.isoformat(),
        "date_to": today.isoformat(),
        "days": days,
        "daily_table": daily_table,
        "activities": activities,
    }

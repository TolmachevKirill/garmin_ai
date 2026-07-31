"""Фоновая синхронизация локального кэша - "базовая" операция продукта.

Идея: у самого Garmin Connect графики за произвольный период всегда готовы -
они не "собираются" по клику, а просто читаются из уже засинканных данных.
До этого модуля в пайплайне такого не было: SQLite-кэш (см. cache.py)
наполнялся только как побочный эффект explicit-действий (кнопка "Неделя",
"Сегодня", "Снапшот" и т.п.) - если пользователь их не жал, данных не было.

sync_recent_days тянет последние N дней в кэш без генерации каких-либо
markdown-файлов - используется:
- CLI-командой `sync` (см. cli.py) - можно гонять вручную или по расписанию
  (см. scripts/register_daily_sync_task.ps1 - аналог weekly-задачи);
- desktop_app.py - фоновым потоком, пока открыт GUI-дистрибутив;
- collectors/range_report.py::build_range_report - неявно, через тот же
  принцип "не трогай API за уже закэшированный прошедший день".
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

from garminconnect import Garmin

from garmin_pipeline.cache import get_connection, upsert_activity, upsert_daily_metrics
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.weekly import _activity_to_summary  # noqa: F401 (переиспользуем)


def sync_days(client: Garmin, days: list[str]) -> int:
    """Затягивает конкретный список дат (YYYY-MM-DD) в кэш, без записи файлов

    в библиотеку. Возвращает количество обработанных дней."""
    with get_connection() as conn:
        for day in days:
            bundle = collect_daily(client, day, with_activity_splits=False, conn=conn)
            upsert_daily_metrics(conn, bundle.to_cache_metrics())
            for act in bundle.activities:
                upsert_activity(conn, _activity_to_summary(act))
    return len(days)


def sync_recent_days(client: Garmin, days: int = 3) -> int:
    """Синхронизирует последние `days` дней, включая сегодня.

    Сегодняшний день намеренно всегда перетягиваем заново (его шаги/сон/
    тренировки ещё меняются в течение дня), в отличие от build_range_report,
    который прошедшие дни, уже попавшие в кэш, повторно не трогает.
    """
    today = date_cls.today()
    date_list = [(today - timedelta(days=i)).isoformat() for i in range(days)]
    return sync_days(client, date_list)

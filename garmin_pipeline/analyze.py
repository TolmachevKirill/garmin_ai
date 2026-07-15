"""pandas-поверхность анализа над локальным SQLite-кэшем (см. cache.py).

Не заменяет markdown-отчёты (daily/weekly/monthly - фиксированные шаблоны),
а даёт возможность задавать произвольные вопросы к своей истории (корреляции,
тренды, кастомные срезы) - открывая кэш как DataFrame, а не только через
готовые отчёты.
"""

from __future__ import annotations

from datetime import date as date_cls
from datetime import timedelta

import pandas as pd

from garmin_pipeline.cache import get_connection


def daily_frame(days: int = 30) -> pd.DataFrame:
    """Один ряд на день за последние `days` дней из daily_metrics."""
    date_from = (date_cls.today() - timedelta(days=days - 1)).isoformat()
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM daily_metrics WHERE date >= ? ORDER BY date",
            conn,
            params=(date_from,),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def activities_frame(days: int = 90) -> pd.DataFrame:
    """Один ряд на тренировку за последние `days` дней из activities."""
    date_from = (date_cls.today() - timedelta(days=days - 1)).isoformat()
    with get_connection() as conn:
        df = pd.read_sql_query(
            "SELECT * FROM activities WHERE date >= ? ORDER BY date",
            conn,
            params=(date_from,),
        )
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def coverage(days: int = 30) -> pd.DataFrame:
    """Диагностика пропусков за период: по каждому дню - есть ли строка в

    daily_metrics, заполнены ли в ней ключевые поля, и сколько тренировок в
    этот день. Помогает заметить дни, когда кэш не наполнялся (например,
    забыли запустить daily/weekly, либо Garmin не отдал данные).
    """
    today = date_cls.today()
    date_from = today - timedelta(days=days - 1)
    all_days = [(date_from + timedelta(days=i)).isoformat() for i in range(days)]

    daily_df = daily_frame(days=days)
    act_df = activities_frame(days=days)

    has_row = set(daily_df["date"].dt.strftime("%Y-%m-%d")) if not daily_df.empty else set()

    filled_days: set[str] = set()
    if not daily_df.empty:
        meaningful_cols = [c for c in ("sleep_hours", "hrv_ms", "rhr", "stress_avg") if c in daily_df.columns]
        if meaningful_cols:
            mask = daily_df[meaningful_cols].notna().any(axis=1)
            filled_days = set(daily_df.loc[mask, "date"].dt.strftime("%Y-%m-%d"))

    act_counts: dict[str, int] = {}
    if not act_df.empty:
        act_counts = act_df.groupby(act_df["date"].dt.strftime("%Y-%m-%d")).size().to_dict()

    rows = [
        {
            "date": d,
            "has_row": d in has_row,
            "has_data": d in filled_days,
            "activities": act_counts.get(d, 0),
        }
        for d in all_days
    ]
    return pd.DataFrame(rows)

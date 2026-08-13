"""MCP-сервер поверх garmin_pipeline - те же generic-примитивы, что и CLI

`export`/`sync`/`activity search`, но по протоколу Model Context Protocol -
для внешних LLM-клиентов (Claude Desktop, другие MCP-совместимые агенты),
которые не могут вызвать локальный CLI напрямую, в отличие от Cursor (там
для этого есть .cursor/skills/garmin-health/SKILL.md).

Сама логика инструментов живёт в garmin_pipeline/actions.py (общая для
MCP-сервера и агентного Telegram-бота, см. agent_tools.py) - здесь только
тонкие @mcp.tool() обёртки. Инструменты read-only и отдают "сырые" данные,
а не готовые отчёты - решение "что и как посчитать" оставлено вызывающей
модели (см. export.py и README/SKILL.md, раздел "Ad hoc аналитические
запросы"). Единственное исключение - build_shareable_range_report, которая
создаёт готовую markdown/HTML-страницу для публикации (для этого нужен
фиксированный формат, не имеет смысла заставлять каждую модель заново
придумывать вёрстку). Write-действия (создание/удаление тренировок,
загрузка файлов) здесь намеренно не выставлены - см. agent_tools.py/bot.py,
где они защищены подтверждением пользователя перед выполнением.

Запуск (stdio-транспорт - клиент сам поднимает процесс):
    python -m garmin_pipeline.cli mcp

Регистрация в Claude Desktop / Cursor - см. README, раздел "MCP-сервер".
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from garmin_pipeline import actions

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
    return actions.get_daily_metrics(date_from, date_to)


@mcp.tool()
def get_activities(date_from: str, date_to: str, activity_type: str | None = None) -> list[dict[str, Any]]:
    """Тренировки за период (включительно), одна запись на тренировку.

    Поля: activity_id, date, activity_type (running/cycling/strength_training/
    jump_rope/... - как в Garmin), name, distance_km, duration_s, avg_hr,
    max_hr, avg_pace_s_per_km (для скорости в км/ч на велоактивностях: 3600 /
    avg_pace_s_per_km), elevation_gain_m, training_effect_aerobic (0-5),
    calories. activity_type - опциональный фильтр по точному типу.
    """
    return actions.get_activities(date_from, date_to, activity_type=activity_type)


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
    последнюю тренировку без прочих фильтров.
    """
    return actions.find_activities(
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
    time-series), распределение по пульсовым зонам, а для силовых/кардио
    тренировок (strength_training, hiit, ...) - ещё и exercise_sets: разбивка
    по упражнениям с числом подходов/повторов, весом (кг) и группами мышц,
    если устройство их распознало, в дополнение к базовым полям из get_activities.
    """
    return actions.get_activity_detail(activity_id)


@mcp.tool()
def sync_cache(days: int = 3) -> str:
    """Синхронизирует последние N дней в локальный кэш без анализа - обычно

    не нужно вызывать вручную: get_daily_metrics/get_activities и так
    дособирают недостающее сами. Полезно перед серией запросов, чтобы
    прогреть кэш заранее одним вызовом.
    """
    return actions.sync_cache(days=days)


@mcp.tool()
def build_shareable_range_report(date_from: str, date_to: str) -> dict[str, Any]:
    """Готовит markdown-файл + агрегаты (шаги/дистанция всего и в среднем,

    тренировки по типам с count/суммарно/в среднем) для публикации/шаринга за
    период - используй, только если пользователь явно просит красивый отчёт/
    файл/страницу для публикации, а не для обычных аналитических вопросов
    (для них используй get_daily_metrics/get_activities и посчитай сам).
    Файл также открывается как HTML-страница в веб-дашборде на /range.
    """
    return actions.build_shareable_range_report(date_from, date_to)


@mcp.tool()
def list_workouts(limit: int = 20) -> list[dict[str, Any]]:
    """Список структурированных тренировок в библиотеке Garmin (созданных

    через агентного бота/CLI или руками в приложении/на часах) - с
    workout_id, названием, видом спорта и датой создания.
    """
    return actions.list_workouts(limit=limit)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

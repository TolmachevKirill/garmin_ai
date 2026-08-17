"""Общий набор действий (read + write) над Garmin Connect - единая точка

правды, переиспользуемая тремя разными "фронтами":

- garmin_pipeline/mcp_server.py - тонкие @mcp.tool() обёртки для внешних
  MCP-клиентов (Claude Desktop, Cursor и т.п.), только read-действия;
- garmin_pipeline/agent_tools.py - JSON Schema (OpenAI tools) + диспетчер
  для агентного Telegram-бота (bot.py), read + write с подтверждением;
- в перспективе - любой другой интерфейс поверх тех же примитивов.

Каждая функция здесь - обычный питоновский callable с плоскими аргументами
JSON-совместимых типов (str/int/float/bool/None/list/dict) и понятным
докстрингом - именно докстринг/сигнатура становится описанием инструмента
для LLM (см. agent_tools.py), так что они должны быть по-настоящему понятны
модели, а не только человеку.

Write-действия (create_workout/delete_workout/upload_activity_file) -
единственные, что реально меняют состояние в Garmin Connect - именно они
помечены как WRITE в agent_tools.py и требуют подтверждения пользователя
перед выполнением в боте.
"""

from __future__ import annotations

import json
from typing import Any

from garmin_pipeline.client import get_client
from garmin_pipeline.collectors.activity import (
    fetch_activity_records,
    get_exercise_sets,
    get_hr_zones,
    is_set_based_activity,
    search_activities,
)
from garmin_pipeline.collectors.export import export_raw_range
from garmin_pipeline.collectors.fit import compute_km_splits_with_fallback
from garmin_pipeline.collectors.range_report import build_range_report
from garmin_pipeline.collectors.sync import sync_recent_days
from garmin_pipeline.collectors.workouts import create_and_schedule
from garmin_pipeline.formatting import render_range_report_md
from garmin_pipeline.library import write_range_report


# ---------------------------------------------------------------------------
# READ - только читают данные, безопасны для вызова без подтверждения.
# ---------------------------------------------------------------------------


def get_daily_metrics(date_from: str, date_to: str) -> list[dict[str, Any]]:
    """Дневные метрики за период (включительно), по одной записи на день.

    Поля: date, sleep_hours, sleep_score (0-100), hrv_ms, rhr (уд/мин),
    stress_avg (0-100), body_battery_high/low (0-100), steps, distance_m
    (дистанция за день по шагам, метры). Отсутствующее поле = None.

    Автоматически дособирает из Garmin недостающие дни периода - при первом
    запросе за новый период может занять время, при повторном по тому же/
    пересекающемуся периоду отвечает мгновенно из локального кэша.
    """
    client = get_client(interactive=False)
    payload = export_raw_range(date_from, date_to, client=client)
    return payload["daily"]


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
    получить activity_id для get_activity_detail. latest=true вернёт самую
    последнюю тренировку без прочих фильтров.
    """
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


def get_activity_detail(activity_id: str) -> dict[str, Any]:
    """Полная детализация одной тренировки по её activity_id (см. find_activities):

    сплиты по км, распределение по пульсовым зонам, а для силовых/кардио
    тренировок (strength_training, hiit, ...) - ещё и exercise_sets: разбивка
    по упражнениям с числом подходов/повторов, весом (кг) и задействованными
    группами мышц, если устройство их распознало.
    """
    client = get_client(interactive=False)
    candidates = search_activities(client, activity_id=activity_id, limit=1)
    if not candidates:
        return {"error": f"Тренировка с activity_id={activity_id} не найдена"}
    act = candidates[0]
    records = fetch_activity_records(client, activity_id)
    act["splits"] = compute_km_splits_with_fallback(client, activity_id, records)
    act["hr_zones"] = get_hr_zones(client, activity_id)
    if is_set_based_activity(act.get("type")):
        act["exercise_sets"] = get_exercise_sets(client, activity_id)
    return act


def sync_cache(days: int = 3) -> str:
    """Синхронизирует последние N дней в локальный кэш без анализа - обычно

    не нужно вызывать вручную: get_daily_metrics/get_activities и так
    дособирают недостающее сами. Полезно перед серией запросов, чтобы
    прогреть кэш заранее одним вызовом.
    """
    client = get_client(interactive=False)
    n = sync_recent_days(client, days=days)
    return f"Синхронизировано {n} дн. в локальный кэш."


def build_shareable_range_report(date_from: str, date_to: str) -> dict[str, Any]:
    """Готовит markdown-файл + агрегаты (шаги/дистанция всего и в среднем,

    тренировки по типам с count/суммарно/в среднем) для публикации/шаринга за
    период - используй, только если пользователь явно просит красивый отчёт/
    файл/страницу для публикации, а не для обычных аналитических вопросов.
    Файл также открывается как HTML-страница в веб-дашборде на /range.
    """
    client = get_client(interactive=False)
    report = build_range_report(client, date_from, date_to)
    path = write_range_report(date_from, date_to, render_range_report_md(report))
    return {"markdown_path": str(path), **report}


def list_workouts(limit: int = 20) -> list[dict[str, Any]]:
    """Список структурированных тренировок в библиотеке Garmin (созданных

    через create_workout здесь или руками в приложении/на часах) - с
    workout_id, нужным для delete_workout, если пользователь просит удалить
    конкретную тренировку по названию.
    """
    client = get_client(interactive=False)
    raw = client.get_workouts(start=0, limit=limit) or []
    return [
        {
            "workout_id": w.get("workoutId"),
            "name": w.get("workoutName"),
            "sport": ((w.get("sportType") or {}).get("sportTypeKey")),
            "created_date": w.get("createdDate"),
        }
        for w in raw
    ]


# ---------------------------------------------------------------------------
# WRITE - меняют состояние в Garmin Connect. В агентном боте требуют
# явного подтверждения пользователя перед выполнением (см. agent_tools.py).
# ---------------------------------------------------------------------------


def create_workout(sport: str, name: str, steps_json: str, date: str | None = None) -> dict[str, Any]:
    """Создаёт структурированную тренировку в библиотеке Garmin и, если

    указана date, планирует её на эту дату (появится в календаре Garmin
    Connect и на часах после синхронизации устройства).

    sport: "running" | "cycling" | "strength_training" | "cardio_training" | "hiit".

    steps_json - JSON-строка со списком шагов. Для running/cycling/cardio_training/
    hiit - шаги вида {"kind": "warmup"|"interval"|"recovery"|"cooldown",
    "duration_s": 300, "hr_zone": 2} (hr_zone 1-5 - опциональное оповещение
    по пульсовой зоне, обычно на warmup/cooldown), а также {"kind": "repeat",
    "repeat": 6, "steps": [...]} для повторов интервалов. Для strength_training -
    шаги вида {"kind": "exercise", "category": "PLANK", "exercise_name":
    "SIDE_PLANK", "reps": 20} (или "duration_s" вместо "reps" - удержание по
    времени, опционально "weight_kg") и {"kind": "rest", "duration_s": 30}
    между подходами.

    date - опционально, формат YYYY-MM-DD. Без даты тренировка просто
    попадёт в библиотеку Garmin (пользователь сам выберет день на часах).
    """
    client = get_client(interactive=False)
    steps = json.loads(steps_json)
    if not isinstance(steps, list):
        raise ValueError("steps_json должен быть JSON-массивом шагов")
    # validate_workout_steps вызывается внутри build_workout - здесь явно,
    # чтобы сломанный план отвалился до похода в Garmin API с понятной ошибкой.
    from garmin_pipeline.collectors.workouts import validate_workout_steps

    summary = validate_workout_steps(sport, steps)
    result = create_and_schedule(client, sport=sport, name=name, steps=steps, schedule_date=date)
    return {
        "workout_id": result.get("workout_id"),
        "scheduled_date": date,
        "sport": sport,
        "name": name,
        "estimated_duration_s": summary["estimated_duration_s"],
        "estimated_duration": summary["estimated_duration"],
    }


def delete_workout(workout_id: str) -> dict[str, Any]:
    """Удаляет тренировку из библиотеки Garmin по workout_id (см. list_workouts

    или workout_id, возвращённый create_workout). Действие необратимо.
    """
    client = get_client(interactive=False)
    client.delete_workout(workout_id)
    return {"deleted": True, "workout_id": workout_id}


def upload_activity_file(file_path: str) -> dict[str, Any]:
    """Загружает файл тренировки (.fit/.tcx/.gpx) в Garmin Connect как новую

    активность - используется, когда пользователь присылает файл в бот.
    file_path - абсолютный локальный путь к уже скачанному файлу (см.
    bot.py: файлы из Telegram сохраняются во временную папку перед вызовом
    этого инструмента). Если активность уже была синхронизирована с часов
    другим путём, Garmin молча отбросит дубликат - это нормальное поведение,
    не ошибка.
    """
    client = get_client(interactive=False)
    result = client.upload_activity(file_path)
    detail = (result or {}).get("detailedImportResult") or {}
    if not detail:
        # Неожиданная форма ответа - отдаём как есть, а не молчим.
        return {"raw_response": result}
    return {
        "upload_id": detail.get("uploadId"),
        "file_name": detail.get("fileName"),
        "successes": detail.get("successes"),
        "failures": detail.get("failures"),
    }

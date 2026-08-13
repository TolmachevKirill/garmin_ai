"""OpenAI-совместимые function-calling схемы поверх actions.py + диспетчер.

Используется агентным Telegram-ботом (bot.py) через llm_client.run_agentic().
Схемы написаны руками (не сгенерированы из type hints) - для 9 инструментов
это управляемо, а качество описаний прямо влияет на надёжность выбора
инструмента маленькой локальной моделью (см. README про qwen3:4b).

WRITE_TOOL_NAMES - подмножество инструментов, которые реально меняют
состояние в Garmin Connect. Именно на них run_agentic() останавливается и
просит подтверждение у пользователя, прежде чем выполнить (см. bot.py).
"""

from __future__ import annotations

import json
from typing import Any

from garmin_pipeline import actions

TOOL_FUNCTIONS: dict[str, Any] = {
    "get_daily_metrics": actions.get_daily_metrics,
    "get_activities": actions.get_activities,
    "find_activities": actions.find_activities,
    "get_activity_detail": actions.get_activity_detail,
    "sync_cache": actions.sync_cache,
    "build_shareable_range_report": actions.build_shareable_range_report,
    "list_workouts": actions.list_workouts,
    "create_workout": actions.create_workout,
    "delete_workout": actions.delete_workout,
    "upload_activity_file": actions.upload_activity_file,
}

WRITE_TOOL_NAMES: set[str] = {"create_workout", "delete_workout", "upload_activity_file"}

_DATE_DESC = "Дата в формате YYYY-MM-DD"

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_daily_metrics",
            "description": (
                "Дневные метрики (сон, HRV, RHR, стресс, Body Battery, шаги, дистанция) "
                "за период. Дособирает недостающие дни из Garmin автоматически."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": _DATE_DESC},
                    "date_to": {"type": "string", "description": _DATE_DESC},
                },
                "required": ["date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activities",
            "description": "Список тренировок за период (дистанция, время, пульс, темп/скорость, калории, ...).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": _DATE_DESC},
                    "date_to": {"type": "string", "description": _DATE_DESC},
                    "activity_type": {
                        "type": "string",
                        "description": "Опциональный фильтр по типу, напр. running/cycling/strength_training",
                    },
                },
                "required": ["date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_activities",
            "description": (
                "Найти конкретные тренировки без указания периода: 'последняя пробежка', "
                "'та тренировка в горах', тренировки конкретного дня/типа/по части названия. "
                "Возвращает activity_id для get_activity_detail."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": _DATE_DESC},
                    "date_from": {"type": "string", "description": _DATE_DESC},
                    "date_to": {"type": "string", "description": _DATE_DESC},
                    "activity_type": {"type": "string"},
                    "name_contains": {"type": "string", "description": "Подстрока в названии тренировки"},
                    "latest": {"type": "boolean", "description": "true - вернуть самую последнюю тренировку"},
                    "limit": {"type": "integer", "description": "Максимум результатов, по умолчанию 20"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_activity_detail",
            "description": (
                "Полная детализация одной тренировки по activity_id: сплиты по км, пульсовые зоны, "
                "а для силовых/кардио - подходы/повторы/вес/группы мышц."
            ),
            "parameters": {
                "type": "object",
                "properties": {"activity_id": {"type": "string"}},
                "required": ["activity_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_cache",
            "description": "Прогреть локальный кэш последними N днями из Garmin (обычно не нужно вызывать вручную).",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "По умолчанию 3"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_shareable_range_report",
            "description": (
                "Только если пользователь явно просит красивый отчёт/файл/страницу для публикации за период "
                "(не для обычных аналитических вопросов - для них get_daily_metrics/get_activities)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date_from": {"type": "string", "description": _DATE_DESC},
                    "date_to": {"type": "string", "description": _DATE_DESC},
                },
                "required": ["date_from", "date_to"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workouts",
            "description": "Список структурированных тренировок в библиотеке Garmin (с workout_id для delete_workout).",
            "parameters": {
                "type": "object",
                "properties": {"limit": {"type": "integer", "description": "По умолчанию 20"}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_workout",
            "description": (
                "[ИЗМЕНЯЕТ ДАННЫЕ, требует подтверждения пользователя] Создать структурированную "
                "тренировку в Garmin и, если указана дата, запланировать её. "
                "sport=running/cycling: шаги {kind: warmup|interval|recovery|cooldown, duration_s, "
                "hr_zone?: 1-5} и {kind: repeat, repeat: N, steps: [...]}. "
                "sport=strength_training/cardio_training/hiit: шаги {kind: exercise, category, "
                "exercise_name, reps|duration_s, weight_kg?} и {kind: rest, duration_s}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sport": {
                        "type": "string",
                        "enum": ["running", "cycling", "strength_training", "cardio_training", "hiit"],
                    },
                    "name": {"type": "string", "description": "Название тренировки"},
                    "steps_json": {
                        "type": "string",
                        "description": "JSON-строка со списком шагов (см. описание инструмента)",
                    },
                    "date": {"type": "string", "description": f"Опционально. {_DATE_DESC}"},
                },
                "required": ["sport", "name", "steps_json"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_workout",
            "description": "[ИЗМЕНЯЕТ ДАННЫЕ, требует подтверждения, необратимо] Удалить тренировку из библиотеки Garmin по workout_id.",
            "parameters": {
                "type": "object",
                "properties": {"workout_id": {"type": "string"}},
                "required": ["workout_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "upload_activity_file",
            "description": (
                "[ИЗМЕНЯЕТ ДАННЫЕ, требует подтверждения] Загрузить .fit/.tcx/.gpx файл в Garmin Connect "
                "как новую активность. file_path - путь, который тебе сообщили после того, как "
                "пользователь прислал файл в чат."
            ),
            "parameters": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}},
                "required": ["file_path"],
            },
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Вызывает инструмент по имени, оборачивая ошибки в понятную строку -

    чтобы модель увидела причину сбоя в tool-результате и могла отреагировать
    (переспросить/попробовать иначе), а не оборвала диалог исключением."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return {"error": f"Неизвестный инструмент: {name}"}
    try:
        return fn(**arguments)
    except Exception as exc:  # noqa: BLE001 - любая ошибка инструмента должна дойти до модели как текст
        return {"error": f"{type(exc).__name__}: {exc}"}


def stringify_tool_result(result: Any) -> str:
    """Tool-сообщения в OpenAI API должны быть строкой - сериализуем как есть."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return str(result)


_SPORT_RU = {
    "running": "бег", "cycling": "велосипед", "strength_training": "силовая",
    "cardio_training": "кардио", "hiit": "HIIT",
}


def describe_call(name: str, arguments: dict[str, Any]) -> str:
    """Человекочитаемое (по-русски) описание write-действия для сообщения-

    подтверждения перед выполнением в боте (см. bot.py)."""
    if name == "create_workout":
        sport = _SPORT_RU.get(arguments.get("sport", ""), arguments.get("sport", "?"))
        title = arguments.get("name", "без названия")
        date = arguments.get("date")
        n_steps = 0
        try:
            n_steps = len(json.loads(arguments.get("steps_json") or "[]"))
        except (json.JSONDecodeError, TypeError):
            pass
        when = f" на {date}" if date else " (без даты - в библиотеку)"
        return f"Создать тренировку «{title}» ({sport}, {n_steps} шаг(ов)){when}?"
    if name == "delete_workout":
        return f"Удалить тренировку id={arguments.get('workout_id')} из библиотеки Garmin? Это необратимо."
    if name == "upload_activity_file":
        return f"Загрузить файл в Garmin Connect как новую активность: {arguments.get('file_path')}?"
    return f"Выполнить {name}({arguments})?"

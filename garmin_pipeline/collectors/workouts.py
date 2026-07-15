"""Создание и планирование структурированных тренировок в Garmin Connect.

Разведка (Фаза 6 плана): python-garminconnect поддерживает upload/schedule
структурированных workout "из коробки" - см. garminconnect.workout
(RunningWorkout/CyclingWorkout + create_warmup_step/create_interval_step/...
+ Garmin.schedule_workout). Это отдельный набор эндпоинтов (workout-service),
не связанный с чтением активностей - т.е. можно не просто анализировать
тренировки, но и планировать их пользователю прямо в Garmin Connect (и они
появятся на часах через штатную синхронизацию).

Ограничение: типизированные модели требуют pydantic (уже есть как зависимость
`garminconnect[typed]`), поэтому здесь без дополнительной установки.

Здесь - тонкая обёртка: описываешь тренировку списком шагов (kind + duration_s
[+ target/iterations]), а не строишь Pydantic-модели вручную.
"""

from __future__ import annotations

from typing import Any

from garminconnect import Garmin

try:
    from garminconnect.workout import (
        CyclingWorkout,
        ExecutableStep,
        RepeatGroup,
        RunningWorkout,
        WorkoutSegment,
        create_cooldown_step,
        create_interval_step,
        create_recovery_step,
        create_repeat_group,
        create_warmup_step,
    )

    WORKOUT_SUPPORT = True
except ImportError:
    WORKOUT_SUPPORT = False

_STEP_BUILDERS = {
    "warmup": create_warmup_step,
    "interval": create_interval_step,
    "recovery": create_recovery_step,
    "cooldown": create_cooldown_step,
} if WORKOUT_SUPPORT else {}

_SPORT_TYPES = {
    "running": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    "cycling": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
}


class _StepOrderCounter:
    """Garmin нумерует шаги (stepOrder) сквозно по всей тренировке, включая

    шаги внутри repeat-групп - поэтому счётчик общий, а не свой на каждый
    уровень вложенности."""

    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def _build_step(spec: dict[str, Any], counter: _StepOrderCounter) -> "ExecutableStep | RepeatGroup":
    kind = spec.get("kind")
    order = counter.next()
    if kind == "repeat":
        nested = [_build_step(s, counter) for s in spec["steps"]]
        return create_repeat_group(spec["iterations"], nested, order)
    builder = _STEP_BUILDERS.get(kind)
    if builder is None:
        raise ValueError(f"Неизвестный тип шага: {kind!r} (ожидались warmup/interval/recovery/cooldown/repeat)")
    return builder(spec["duration_s"], order, spec.get("target"))


def _estimate_duration_s(steps: list[dict[str, Any]]) -> int:
    total = 0.0
    for s in steps:
        if s.get("kind") == "repeat":
            total += s["iterations"] * _estimate_duration_s(s["steps"])
        else:
            total += s.get("duration_s", 0)
    return int(total)


def build_workout(
    *,
    sport: str,
    name: str,
    steps: list[dict[str, Any]],
    estimated_duration_s: int | None = None,
) -> "RunningWorkout | CyclingWorkout":
    """Собирает типизированную модель тренировки из простого описания шагов.

    steps - список dict вида {"kind": "warmup"|"interval"|"recovery"|"cooldown",
    "duration_s": 300} или {"kind": "repeat", "iterations": 5, "steps": [...]}
    (вложенные шаги того же вида, без "repeat" внутри "repeat").
    """
    if not WORKOUT_SUPPORT:
        raise RuntimeError(
            "Для создания тренировок нужен pydantic (обычно уже установлен как "
            "часть garminconnect[typed]); если нет - pip install pydantic"
        )
    if sport not in _SPORT_TYPES:
        raise ValueError(f"Поддерживаются только sport='running' или 'cycling', получено: {sport!r}")

    counter = _StepOrderCounter()
    built_steps = [_build_step(s, counter) for s in steps]

    segment = WorkoutSegment(segmentOrder=1, sportType=_SPORT_TYPES[sport], workoutSteps=built_steps)
    workout_cls = RunningWorkout if sport == "running" else CyclingWorkout
    return workout_cls(
        workoutName=name,
        estimatedDurationInSecs=estimated_duration_s or _estimate_duration_s(steps),
        workoutSegments=[segment],
    )


def upload_workout(client: Garmin, workout: "RunningWorkout | CyclingWorkout") -> dict[str, Any]:
    if isinstance(workout, RunningWorkout):
        return client.upload_running_workout(workout)
    return client.upload_cycling_workout(workout)


def create_and_schedule(
    client: Garmin,
    *,
    sport: str,
    name: str,
    steps: list[dict[str, Any]],
    schedule_date: str | None = None,
) -> dict[str, Any]:
    """Создаёт тренировку в библиотеке Garmin и, если указана дата, планирует её.

    Запланированная тренировка появится в календаре Garmin Connect и на часах
    пользователя (после обычной синхронизации устройства) - без нашего участия
    после этого шага.
    """
    workout = build_workout(sport=sport, name=name, steps=steps)
    uploaded = upload_workout(client, workout)
    workout_id = uploaded.get("workoutId") or uploaded.get("workoutID") or uploaded.get("id")

    result: dict[str, Any] = {"workout": uploaded, "workout_id": workout_id}
    if schedule_date:
        if not workout_id:
            raise RuntimeError(f"Garmin не вернул workout_id при загрузке - ответ: {uploaded}")
        result["scheduled"] = client.schedule_workout(workout_id, schedule_date)
    return result

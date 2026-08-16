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

Силовые тренировки (kind="exercise"/"rest", sport="strength_training" и т.п.):
готовых Strength-хелперов в garminconnect.workout нет (только create_warmup_
step/create_interval_step/... - все с TIME end condition, без exerciseName/
category/весов), поэтому шаг с упражнением собирается здесь вручную через
ExecutableStep(..., extra="allow") - см. _build_exercise_step. Список
категорий/названий упражнений - это встроенный справочник Garmin (тот же FIT
SDK exercise_category enum, что и в activity.py::_CATEGORY_MUSCLE_GROUPS);
если exercise_name не входит в справочник, Garmin просто покажет шаг как
безымянное "Упражнение" (реквизиты/вес всё равно сохранятся).
"""

from __future__ import annotations

from typing import Any

from garminconnect import Garmin

try:
    from garminconnect.workout import (
        BaseWorkout,
        ConditionType,
        CyclingWorkout,
        ExecutableStep,
        RepeatGroup,
        RunningWorkout,
        StepType,
        TargetType,
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
    "strength_training": {"sportTypeId": 5, "sportTypeKey": "strength_training", "displayOrder": 5},
    "cardio_training": {"sportTypeId": 6, "sportTypeKey": "cardio_training", "displayOrder": 6},
    "hiit": {"sportTypeId": 9, "sportTypeKey": "hiit", "displayOrder": 9},
}

# HR-зона как таргет шага (см. spec["hr_zone"] в _build_step) - часы дают
# оповещение (вибро/сигнал), когда пульс выходит за пределы этой зоны во
# время шага. ВАЖНО: сама граница/значение зоны (bpm) не передаётся - Garmin
# использует "zoneNumber" (1-5), а не targetValueOne/targetValueTwo (те поля
# зарезервированы под абсолютные диапазоны - темп в м/с, мощность в ваттах;
# если положить туда bpm, часы трактуют их как темп и получается мусор вида
# "11 сек/милю" - см. https://github.com/cyberjunky/python-garminconnect/issues/333).
# Реальные границы зоны 1-5 в bpm/% ЧСС берутся из личного профиля пользователя
# в Garmin Connect (Настройки -> Пульс -> Зоны ЧСС) - шаг просто ссылается на
# номер зоны, а не задаёт число ударов сам.
_HR_ZONE_TARGET_TYPE: dict[str, Any] = {
    "workoutTargetTypeId": TargetType.HEART_RATE_ZONE,
    "workoutTargetTypeKey": "heart.rate.zone",
    "displayOrder": 4,
} if WORKOUT_SUPPORT else {}


class _StepOrderCounter:
    """Garmin нумерует шаги (stepOrder) сквозно по всей тренировке, включая

    шаги внутри repeat-групп - поэтому счётчик общий, а не свой на каждый
    уровень вложенности."""

    def __init__(self) -> None:
        self.value = 0

    def next(self) -> int:
        self.value += 1
        return self.value


def _build_rest_step(duration_s: float, order: int) -> "ExecutableStep":
    """Шаг отдыха между подходами (силовые/cardio) - фиксированное время."""
    return ExecutableStep(
        stepOrder=order,
        stepType={"stepTypeId": StepType.REST, "stepTypeKey": "rest", "displayOrder": 5},
        endCondition={
            "conditionTypeId": ConditionType.TIME,
            "conditionTypeKey": "time",
            "displayOrder": 2,
            "displayable": True,
        },
        endConditionValue=float(duration_s),
        targetType={
            "workoutTargetTypeId": TargetType.NO_TARGET,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": 1,
        },
    )


def _build_exercise_step(spec: dict[str, Any], order: int) -> "ExecutableStep":
    """Один подход упражнения (силовые/cardio) - по повторам или по времени.

    spec: {"kind": "exercise", "category": "HIP_STABILITY", "exercise_name":
    "DEAD_BUG", "reps": 20} ИЛИ {..., "duration_s": 20} (взаимоисключающие -
    reps -> endCondition REPS, duration_s -> endCondition TIME, как удержание
    планки). "weight_kg": опционально - фиксированный целевой вес подхода;
    если не указан (в т.ч. когда вес по факту переменный/подбирается на
    месте) - поле просто не выставляется, а реальный использованный вес всё
    равно попадёт в завершённую активность (см. activity.get_exercise_sets) -
    Garmin запросит его на часах по ходу подхода независимо от плана.

    category/exercise_name - строки из справочника Garmin (FIT SDK
    exercise_category enum, см. модуль docstring) - лучше в верхнем регистре,
    напр. category="PLANK", exercise_name="SIDE_PLANK".
    """
    reps = spec.get("reps")
    duration_s = spec.get("duration_s")
    if reps is not None:
        end_condition = {
            "conditionTypeId": ConditionType.REPS,
            "conditionTypeKey": "reps",
            "displayOrder": 10,
            "displayable": True,
        }
        end_condition_value = float(reps)
    elif duration_s is not None:
        end_condition = {
            "conditionTypeId": ConditionType.TIME,
            "conditionTypeKey": "time",
            "displayOrder": 2,
            "displayable": True,
        }
        end_condition_value = float(duration_s)
    else:
        raise ValueError("У шага exercise должно быть 'reps' или 'duration_s'")

    extra: dict[str, Any] = {}
    if spec.get("category"):
        extra["category"] = str(spec["category"]).upper()
    if spec.get("exercise_name"):
        extra["exerciseName"] = str(spec["exercise_name"]).upper()
    weight_kg = spec.get("weight_kg")
    if weight_kg is not None:
        extra["weightValue"] = round(float(weight_kg), 1)
        extra["weightUnit"] = {"unitId": 8, "unitKey": "kilogram", "factor": 1000.0}

    return ExecutableStep(
        stepOrder=order,
        stepType={"stepTypeId": StepType.INTERVAL, "stepTypeKey": "interval", "displayOrder": 3},
        endCondition=end_condition,
        endConditionValue=end_condition_value,
        targetType={
            "workoutTargetTypeId": TargetType.NO_TARGET,
            "workoutTargetTypeKey": "no.target",
            "displayOrder": 1,
        },
        **extra,
    )


def _build_step(spec: dict[str, Any], counter: _StepOrderCounter) -> "ExecutableStep | RepeatGroup":
    kind = spec.get("kind")
    order = counter.next()
    if kind == "repeat":
        nested = [_build_step(s, counter) for s in spec["steps"]]
        # "repeat" - частый алиас, которым модели (особенно локальные) иногда
        # называют то же поле вместо документированного "iterations".
        iterations = spec.get("iterations", spec.get("repeat"))
        if iterations is None:
            raise ValueError("У шага repeat должно быть указано 'iterations' (число повторов)")
        return create_repeat_group(iterations, nested, order)
    if kind == "rest":
        return _build_rest_step(spec["duration_s"], order)
    if kind == "exercise":
        return _build_exercise_step(spec, order)

    builder = _STEP_BUILDERS.get(kind)
    if builder is None:
        raise ValueError(
            f"Неизвестный тип шага: {kind!r} "
            "(ожидались warmup/interval/recovery/cooldown/repeat/exercise/rest)"
        )

    hr_zone = spec.get("hr_zone")
    target_type = _HR_ZONE_TARGET_TYPE if hr_zone is not None else spec.get("target")
    step = builder(spec["duration_s"], order, target_type)
    if hr_zone is not None:
        # zoneNumber - extra-поле у ExecutableStep (model_config extra="allow"),
        # само по себе оно не сериализуется через конструктор builder'ов выше -
        # выставляем отдельно, см. _HR_ZONE_TARGET_TYPE.
        step.zoneNumber = int(hr_zone)
    return step


def _estimate_duration_s(steps: list[dict[str, Any]]) -> int:
    total = 0.0
    for s in steps:
        if s.get("kind") == "repeat":
            total += s.get("iterations", s.get("repeat", 1)) * _estimate_duration_s(s["steps"])
        elif s.get("duration_s") is not None:
            total += s["duration_s"]
        elif s.get("kind") == "exercise" and s.get("reps") is not None:
            total += s["reps"] * 3  # грубая оценка ~3с/повтор - только для estimatedDurationInSecs
    return int(total)


def build_workout(
    *,
    sport: str,
    name: str,
    steps: list[dict[str, Any]],
    estimated_duration_s: int | None = None,
) -> "RunningWorkout | CyclingWorkout | BaseWorkout":
    """Собирает типизированную модель тренировки из простого описания шагов.

    Поддерживаемые sport: "running", "cycling", "strength_training",
    "cardio_training", "hiit" (см. _SPORT_TYPES).

    steps - список dict вида {"kind": "warmup"|"interval"|"recovery"|"cooldown",
    "duration_s": 300} (кардио-шаги, TIME-based) или силовые шаги:
        {"kind": "exercise", "category": "PLANK", "exercise_name": "SIDE_PLANK",
         "reps": 20}                                    # по повторам
        {"kind": "exercise", "category": "PLANK", "exercise_name": "SIDE_PLANK",
         "duration_s": 20}                               # по времени (удержание)
        {"kind": "rest", "duration_s": 30}                # отдых между подходами
    - "weight_kg" опционально у "exercise" (фиксированный целевой вес; если не
    указан - вес на этом подходе свободный/подбирается на месте, но фактически
    использованный всё равно попадёт в завершённую активность - см.
    activity.get_exercise_sets).
    Список категорий/названий - справочник Garmin (FIT SDK exercise_category,
    см. модуль docstring); если название не из справочника, шаг покажется как
    безымянное "Упражнение" (вес/повторы всё равно сохранятся).

    Либо {"kind": "repeat", "iterations": N, "steps": [...]} - для силовых так
    обычно оборачивают один подход+отдых на N сетов, напр.:
        {"kind": "repeat", "iterations": 2, "steps": [
            {"kind": "exercise", "category": "HIP_STABILITY",
             "exercise_name": "DEAD_BUG", "reps": 20},
            {"kind": "rest", "duration_s": 30},
        ]}
    (вложенные шаги того же вида, без "repeat" внутри "repeat").

    Опционально можно добавить "hr_zone": 1-5 к кардио-шагу (кроме repeat) -
    часы дадут оповещение (вибро/сигнал), если пульс во время этого шага
    выйдет за пределы указанной зоны (границы зоны в bpm берутся из личного
    профиля пользователя в Garmin Connect, а не задаются здесь - см.
    _HR_ZONE_TARGET_TYPE). Пример - разминка с оповещением о выходе выше Z2:
    {"kind": "warmup", "duration_s": 1680, "hr_zone": 2}
    """
    if not WORKOUT_SUPPORT:
        raise RuntimeError(
            "Для создания тренировок нужен pydantic (обычно уже установлен как "
            "часть garminconnect[typed]); если нет - pip install pydantic"
        )
    if sport not in _SPORT_TYPES:
        raise ValueError(
            f"Поддерживаются sport={sorted(_SPORT_TYPES)}, получено: {sport!r}"
        )

    counter = _StepOrderCounter()
    built_steps = [_build_step(s, counter) for s in steps]

    segment = WorkoutSegment(segmentOrder=1, sportType=_SPORT_TYPES[sport], workoutSteps=built_steps)
    kwargs: dict[str, Any] = {
        "workoutName": name,
        "estimatedDurationInSecs": estimated_duration_s or _estimate_duration_s(steps),
        "workoutSegments": [segment],
    }
    if sport == "running":
        return RunningWorkout(**kwargs)
    if sport == "cycling":
        return CyclingWorkout(**kwargs)
    # Остальные спорты (strength_training/cardio_training/hiit) - без
    # выделенного typed-класса в garminconnect.workout, используем базовый
    # BaseWorkout с явным sportType.
    return BaseWorkout(sportType=_SPORT_TYPES[sport], **kwargs)


def upload_workout(
    client: Garmin, workout: "RunningWorkout | CyclingWorkout | BaseWorkout"
) -> dict[str, Any]:
    if isinstance(workout, RunningWorkout):
        return client.upload_running_workout(workout)
    if isinstance(workout, CyclingWorkout):
        return client.upload_cycling_workout(workout)
    # Общий эндпоинт workout-service принимает произвольный JSON тренировки -
    # используется для спортов без typed-класса (strength_training/...).
    return client.upload_workout(workout.to_dict())


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

"""Быстрый прогон логики без реального логина в Garmin (моки вместо API).

Не является pytest-сьютом в полном смысле - просто ручная проверка того, что
формирование markdown, запись в библиотеку, кэш и rollup не падают на
правдоподобных данных. Настоящую интеграцию с Garmin можно проверить только
с реальным аккаунтом (см. README: `python -m garmin_pipeline.cli login`).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TEST_DATA_DIR = Path(__file__).resolve().parent / "_tmp_data"
import os

os.environ["LIBRARY_ROOT"] = str(TEST_DATA_DIR / "library")
os.environ["CACHE_DB_PATH"] = str(TEST_DATA_DIR / "cache.sqlite3")
os.environ["GARMIN_TOKENSTORE"] = str(TEST_DATA_DIR / "tokens")
os.environ["CONFIG_JSON_PATH"] = str(TEST_DATA_DIR / "config.json")

shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)

from garmin_pipeline.cache import (  # noqa: E402
    ActivitySummary,
    DailyMetrics,
    get_connection,
    get_raw_payload,
    raw_payload_keys,
    save_raw_payload,
    upsert_activity,
    upsert_daily_metrics,
)
from garmin_pipeline.collectors.activity import (  # noqa: E402
    compute_km_splits,
    get_exercise_sets,
    is_set_based_activity,
)
from garmin_pipeline.collectors.daily import DailyBundle  # noqa: E402
from garmin_pipeline.collectors.weekly import _aggregate_activities, _mean  # noqa: E402
from garmin_pipeline.collectors.range_report import (  # noqa: E402
    _aggregate_by_type,
    build_range_report,
    range_report_from_cache,
)
from garmin_pipeline.collectors.sync import ensure_range_synced, sync_days, sync_recent_days  # noqa: E402
from garmin_pipeline.collectors.export import export_raw_range  # noqa: E402
from garmin_pipeline.formatting import (  # noqa: E402
    activity_icon,
    activity_label_ru,
    fmt_duration,
    fmt_exercise_sets_lines,
    render_activity_md,
    render_context_md,
    render_daily_md,
    render_range_report_md,
    render_weekly_md,
)
from garmin_pipeline.library import (  # noqa: E402
    activity_file_stem,
    update_index,
    write_activity_md,
    write_context,
    write_daily,
    write_weekly,
)
from garmin_pipeline.analyze import activities_frame, coverage, daily_frame  # noqa: E402
from garmin_pipeline.collectors.fit import compute_km_splits_from_fit, fit_records_to_points  # noqa: E402
from garmin_pipeline.collectors.workouts import build_workout  # noqa: E402
from garmin_pipeline import config as garmin_config  # noqa: E402
from garmin_pipeline import llm_client  # noqa: E402
from garmin_pipeline import bot as garmin_bot  # noqa: E402
from garmin_pipeline import agent_tools  # noqa: E402
from garmin_pipeline import ollama_setup  # noqa: E402
import desktop_app  # noqa: E402
from garmin_pipeline.rollup import build_monthly_rollup  # noqa: E402
from garmin_pipeline.webapp import templates as webapp_templates  # noqa: E402


def test_daily_render_and_write() -> None:
    bundle = DailyBundle(
        date="2026-07-12",
        sleep_hours=6.7,
        sleep_deep_hours=1.2,
        sleep_score=74,
        hrv_ms=42.0,
        hrv_status="BALANCED",
        rhr=54,
        stress_avg=28,
        body_battery_high=85,
        body_battery_low=20,
        training_readiness_score=68,
        training_readiness_feedback="Хорошая готовность",
        total_steps=9450,
        activities=[
            {
                "activity_id": "123456789",
                "date": "2026-07-12",
                "type": "running",
                "name": "Утренний бег",
                "distance_m": 8200,
                "duration_s": 2535,
                "avg_hr": 148,
                "max_hr": 168,
                "elevation_gain_m": 45,
                "training_effect_aerobic": 3.2,
                "avg_pace_s_per_km": 309.1,
                "splits_pace": ["5:20", "5:10", "5:05", "5:02", "5:00", "5:04", "5:08", "5:15"],
            }
        ],
    )
    content = render_daily_md(bundle.as_render_dict())
    assert "Дайджест" in content
    assert "148" in content
    path = write_daily(bundle.date, content)
    assert path.exists()
    print("OK: daily render + write")
    print(content)


def test_weekly_render_and_write() -> None:
    with get_connection() as conn:
        upsert_daily_metrics(conn, DailyMetrics(date="2026-07-05", sleep_hours=7.0, hrv_ms=40, rhr=55, stress_avg=30))
        upsert_activity(
            conn,
            ActivitySummary(
                activity_id="1", date="2026-07-05", activity_type="running",
                name="Прошлый забег", distance_km=6.0, duration_s=1800,
            ),
        )

    week = {
        "week_label": "2026-W28",
        "date_from": "2026-07-06",
        "date_to": "2026-07-12",
        "activities": {
            "count": 4, "by_type": {"running": 3, "strength_training": 1},
            "total_distance_m": 32000.0, "total_duration_s": 15300.0,
            "prev_total_distance_m": 6000.0,
        },
        "sleep_avg_hours": 6.97, "prev_sleep_avg_hours": 7.0,
        "hrv_avg_ms": 44.0, "prev_hrv_avg_ms": 43.0,
        "rhr_avg": 53.0, "prev_rhr_avg": 55.0,
        "stress_avg": 27.0, "prev_stress_avg": 30.0,
        "missing_days": [],
        "daily_table": [
            {"date": "2026-07-06", "sleep_hours": 7.1, "hrv_ms": 45, "rhr": 52, "stress_avg": 25, "steps": 8200, "activities_count": 1},
            {"date": "2026-07-07", "sleep_hours": 6.5, "hrv_ms": 43, "rhr": 54, "stress_avg": 30, "steps": 6100, "activities_count": 0},
        ],
    }
    content = render_weekly_md(week)
    assert "Недельный отчёт" in content
    assert "| Дата | Сон | HRV | RHR | Стресс | Шаги | Тренировок |" in content
    assert "2026-07-06" in content
    path = write_weekly(week["week_label"], content)
    assert path.exists()
    print("OK: weekly render + write")
    print(content)


def test_activity_export_render() -> None:
    act = {
        "activity_id": "123456789",
        "date": "2026-07-05",
        "type": "running",
        "name": "Трейл в горах",
        "distance_m": 15300,
        "duration_s": 5400,
        "avg_hr": 152,
        "max_hr": 178,
        "elevation_gain_m": 480,
        "avg_power": 250,
        "max_power": 410,
        "training_effect_aerobic": 4.1,
        "training_effect_anaerobic": 1.2,
        "avg_pace_s_per_km": 353.0,
        "splits": [
            {"index": 1, "pace_s_per_km": 340, "avg_hr": 145},
            {"index": 2, "pace_s_per_km": 360, "avg_hr": 155},
        ],
        "csv_filename": "2026-07-05_trail_v_gorah.csv",
    }
    content = render_activity_md(act)
    assert "Трейл в горах" in content
    stem = activity_file_stem(act["date"], act["type"], act["name"])
    path = write_activity_md(stem, content)
    assert path.exists()
    print("OK: activity render + write ->", path)
    print(content)


def test_context_render_and_write() -> None:
    context = {
        "date_from": "2026-07-01",
        "date_to": "2026-07-14",
        "days": 14,
        "daily_table": [
            {"date": "2026-07-13", "sleep_hours": 7.0, "hrv_ms": 44, "rhr": 53, "stress_avg": 26, "steps": 9000, "activities_count": 1},
            {"date": "2026-07-14", "sleep_hours": 6.8, "hrv_ms": 41, "rhr": 55, "stress_avg": 31, "steps": 4200, "activities_count": 0},
        ],
        "activities": [
            {
                "date": "2026-07-13", "type": "running", "name": "Лёгкий бег",
                "distance_m": 6000, "duration_s": 1800, "avg_hr": 140, "avg_pace_s_per_km": 300.0,
            }
        ],
    }
    content = render_context_md(context)
    assert "Снапшот" in content
    assert "2026-07-13" in content
    assert "Лёгкий бег" in content
    path = write_context(content)
    assert path.exists()
    print("OK: context render + write ->", path)
    print(content)


def test_fmt_duration() -> None:
    assert fmt_duration(58 * 60 + 57) == "58:57"
    assert fmt_duration(3600 + 2 * 60 + 15) == "1:02:15"
    assert fmt_duration(None) == "н/д"
    print("OK: fmt_duration")


def test_compute_km_splits_from_synthetic_track() -> None:
    """Имитация трека: одна device-лапа на всю тренировку (как у велосипеда без
    авто-лапа по дистанции), но точки трека идут плотно - синтетические сплиты
    по км должны получиться независимо от того, сколько device-лапов было."""
    records = []
    total_distance = 2300.0  # 2 полных км + 300м
    total_duration = 400.0  # секунд
    n_points = 50
    for i in range(n_points + 1):
        frac = i / n_points
        records.append(
            {
                "sumDistance": round(total_distance * frac, 1),
                "sumDuration": round(total_duration * frac, 1),
                "directHeartRate": 140 + (i % 5),
                "directElevation": 100 + frac * 10,
            }
        )

    splits = compute_km_splits(records)
    assert len(splits) == 3, f"Ожидалось 3 сплита (2 полных + 1 частичный), получили {len(splits)}"
    assert splits[0]["index"] == "1"
    assert splits[1]["index"] == "2"
    assert "частично" in splits[2]["index"]
    assert abs(splits[0]["distance_m"] - 1000.0) < 1
    assert abs(splits[2]["distance_m"] - 300.0) < 1
    # Равномерный темп -> все сплиты должны занимать примерно одинаковое время на км
    assert abs(splits[0]["pace_s_per_km"] - splits[1]["pace_s_per_km"]) < 5
    for s in splits:
        assert s["avg_hr"] is not None
    print("OK: compute_km_splits ->", splits)


def test_fit_records_to_splits() -> None:
    """Имитация FIT record-сообщений (как их отдаёт fitdecode: timestamp -

    datetime, distance - накопленные метры) - должны давать те же по смыслу
    сплиты, что и синтетические из time-series API."""
    from datetime import datetime, timedelta

    start = datetime(2026, 7, 10, 8, 0, 0)
    total_distance = 2300.0
    total_duration = 400.0
    n_points = 50
    records = []
    for i in range(n_points + 1):
        frac = i / n_points
        records.append(
            {
                "timestamp": start + timedelta(seconds=total_duration * frac),
                "distance": round(total_distance * frac, 1),
                "heart_rate": 140 + (i % 5),
                "enhanced_altitude": 100 + frac * 10,
            }
        )

    points = fit_records_to_points(records)
    assert len(points) == n_points + 1
    assert abs(points[-1]["elapsed_s"] - total_duration) < 0.01

    splits = compute_km_splits_from_fit(records)
    assert len(splits) == 3
    assert splits[0]["index"] == "1"
    assert "частично" in splits[2]["index"]
    print("OK: fit_records_to_points + compute_km_splits_from_fit ->", splits)

    # Регрессия: raw_payloads кэширует через json.dumps(default=str) и читает
    # обратно через json.loads - datetime не переживает этот раунд-трип как
    # объект, только как строка. fit_records_to_points должен справляться с
    # обоими вариантами (datetime сразу после парсинга FIT, str после кэша).
    import json

    cached_and_reloaded = json.loads(json.dumps(records, default=str))
    assert isinstance(cached_and_reloaded[0]["timestamp"], str)
    splits_from_cache = compute_km_splits_from_fit(cached_and_reloaded)
    assert splits_from_cache == splits, "Сплиты из 'кэшированной' (str-timestamp) версии должны совпадать"
    print("OK: fit records survive JSON cache round-trip (str timestamps)")


def test_build_workout() -> None:
    """Собираем интервальную тренировку (разминка + 3x(интервал+отдых) + заминка)

    и проверяем, что stepOrder идёт сквозно (включая шаги внутри repeat-группы),
    а суммарная длительность посчитана правильно."""
    steps = [
        {"kind": "warmup", "duration_s": 300},
        {
            "kind": "repeat",
            "iterations": 3,
            "steps": [
                {"kind": "interval", "duration_s": 60},
                {"kind": "recovery", "duration_s": 90},
            ],
        },
        {"kind": "cooldown", "duration_s": 300},
    ]
    workout = build_workout(sport="running", name="Интервалы 3x1мин", steps=steps)
    assert workout.workoutName == "Интервалы 3x1мин"
    assert workout.estimatedDurationInSecs == 300 + 3 * (60 + 90) + 300

    payload = workout.to_dict()
    assert payload["sportType"]["sportTypeKey"] == "running"
    top_steps = payload["workoutSegments"][0]["workoutSteps"]
    assert len(top_steps) == 3  # warmup, repeat-group, cooldown
    assert top_steps[0]["stepOrder"] == 1
    repeat_group = top_steps[1]
    assert repeat_group["numberOfIterations"] == 3
    nested = repeat_group["workoutSteps"]
    assert [s["stepOrder"] for s in nested] == [3, 4]  # сквозная нумерация после warmup(1) и repeat(2)
    assert top_steps[2]["stepOrder"] == 5
    print("OK: build_workout ->", payload["estimatedDurationInSecs"], "s,", len(top_steps), "top-level steps")


def test_build_workout_hr_zone_alert() -> None:
    """"hr_zone": N на шаге (warmup/interval/recovery/cooldown) должен дать

    targetType=heart.rate.zone + zoneNumber=N в итоговом JSON - см. пользовательский
    запрос "оповещение при переходе Z2 на разминке/заминке". zoneNumber - именно
    он, а не targetValueOne/Two (те поля для темпа м/с - Garmin интерпретирует
    их так независимо от targetType, см. cyberjunky/python-garminconnect#333)."""
    steps = [
        {"kind": "warmup", "duration_s": 1680, "hr_zone": 2},
        {"kind": "interval", "duration_s": 20},  # без hr_zone - обычный шаг без таргета
        {"kind": "cooldown", "duration_s": 960, "hr_zone": 2},
    ]
    workout = build_workout(sport="running", name="С оповещением Z2", steps=steps)
    payload = workout.to_dict()
    warmup, interval, cooldown = payload["workoutSegments"][0]["workoutSteps"]

    for step in (warmup, cooldown):
        assert step["targetType"]["workoutTargetTypeKey"] == "heart.rate.zone"
        assert step["targetType"]["workoutTargetTypeId"] == 4
        assert step["zoneNumber"] == 2
        assert "targetValueOne" not in step and "targetValueTwo" not in step

    assert interval.get("targetType", {}).get("workoutTargetTypeKey") == "no.target"
    assert "zoneNumber" not in interval
    print("OK: build_workout hr_zone -> warmup/cooldown zoneNumber=2, interval без таргета")


def test_build_workout_strength_exercise_and_rest_steps() -> None:
    """sport='strength_training' + kind='exercise'/'rest' (см. пользовательский

    запрос на кор-тренировку: дэд баг/скручивания/мост/... по подходам и
    повторам, с отдыхом между сетами и опциональным весом) - должен собираться
    через BaseWorkout (нет typed-класса под strength в garminconnect.workout),
    reps -> endCondition REPS(10), duration_s -> endCondition TIME(2), а
    category/exerciseName/weightValue - через extra="allow" на ExecutableStep."""
    steps = [
        {"kind": "exercise", "category": "hip_stability", "exercise_name": "dead_bug", "reps": 20},
        {"kind": "rest", "duration_s": 30},
        {"kind": "exercise", "category": "banded_exercises", "exercise_name": "glute_bridge",
         "reps": 20, "weight_kg": 10},
        {"kind": "exercise", "category": "plank", "exercise_name": "side_plank", "duration_s": 20},
    ]
    workout = build_workout(sport="strength_training", name="Кор и ягодицы", steps=steps)
    payload = workout.to_dict()
    assert payload["sportType"]["sportTypeKey"] == "strength_training"

    dead_bug, rest, glute_bridge, side_plank = payload["workoutSegments"][0]["workoutSteps"]

    assert dead_bug["endCondition"]["conditionTypeKey"] == "reps"
    assert dead_bug["endConditionValue"] == 20.0
    assert dead_bug["category"] == "HIP_STABILITY"
    assert dead_bug["exerciseName"] == "DEAD_BUG"
    assert "weightValue" not in dead_bug

    assert rest["stepType"]["stepTypeKey"] == "rest"
    assert rest["endCondition"]["conditionTypeKey"] == "time"
    assert rest["endConditionValue"] == 30.0

    assert glute_bridge["weightValue"] == 10.0
    assert glute_bridge["weightUnit"]["unitKey"] == "kilogram"

    assert side_plank["endCondition"]["conditionTypeKey"] == "time"
    assert side_plank["endConditionValue"] == 20.0
    assert side_plank["exerciseName"] == "SIDE_PLANK"
    print("OK: build_workout strength_training -> exercise (reps/duration_s/weight_kg) + rest steps")


def test_config_json_overlay_and_reload() -> None:
    """config.json должен иметь приоритет над .env и подхватываться без

    переимпорта модуля (через config.settings, читаемый в момент вызова)."""
    assert garmin_config.settings.llm_api_key is None
    assert not garmin_config.settings.is_llm_configured()

    garmin_config.save_config_json(
        {"llm_api_key": "sk-test-123", "llm_base_url": "http://localhost:11434/v1", "llm_model": "llama3"}
    )
    assert garmin_config.settings.is_llm_configured()
    assert garmin_config.settings.llm_base_url == "http://localhost:11434/v1"
    assert garmin_config.settings.llm_model == "llama3"

    try:
        llm_client.ask("system", "context", "question")
    except Exception as exc:
        # Без реального сервера на localhost:11434 ожидаем ошибку соединения,
        # а не LlmNotConfiguredError - то есть конфигурация подхватилась.
        assert not isinstance(exc, llm_client.LlmNotConfiguredError), (
            f"LLM должен быть 'настроен' после save_config_json, получили: {exc!r}"
        )

    print("OK: config.json overlay + reload + llm_client wiring")


def test_llm_not_configured_error() -> None:
    garmin_config.save_config_json({"llm_api_key": ""})
    # save_config_json игнорирует пустые строки - явно перезатрём файл сами,
    # чтобы проверить путь "LLM не настроен".
    path = garmin_config.config_json_path()
    path.write_text("{}", encoding="utf-8")
    garmin_config.reload_settings()
    assert not garmin_config.settings.is_llm_configured()
    try:
        llm_client.ask("system", "context", "question")
        raise AssertionError("Ожидалась LlmNotConfiguredError")
    except llm_client.LlmNotConfiguredError:
        pass
    print("OK: llm_client raises LlmNotConfiguredError when unset")


class _FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class _FakeUpdate:
    def __init__(self, user_id: int | None) -> None:
        self.effective_user = _FakeUser(user_id) if user_id is not None else None


def test_bot_chunks_and_authorization() -> None:
    long_text = "x" * (garmin_bot.MAX_MESSAGE_LEN * 2 + 10)
    chunks = garmin_bot._chunks(long_text)
    assert len(chunks) == 3
    assert all(len(c) <= garmin_bot.MAX_MESSAGE_LEN for c in chunks)
    assert "".join(chunks) == long_text
    assert garmin_bot._chunks("") == [""]

    # Без telegram_allowed_user_id - доступ открыт всем
    garmin_config.save_config_json({"telegram_allowed_user_id": ""})
    garmin_config.config_json_path().write_text("{}", encoding="utf-8")
    garmin_config.reload_settings()
    assert garmin_bot._is_authorized(_FakeUpdate(111)) is True

    # С telegram_allowed_user_id - доступ только этому id
    garmin_config.save_config_json({"telegram_allowed_user_id": "42"})
    assert garmin_bot._is_authorized(_FakeUpdate(42)) is True
    assert garmin_bot._is_authorized(_FakeUpdate(999)) is False
    print("OK: bot chunking + authorization logic")


def test_desktop_app_imports_cleanly() -> None:
    assert callable(desktop_app.main)
    assert callable(desktop_app._run_web_server)
    assert callable(desktop_app._run_bot_if_configured)
    assert callable(desktop_app._run_background_sync)
    print("OK: desktop_app imports cleanly and exposes main()")


def test_bot_requires_token() -> None:
    garmin_config.config_json_path().write_text("{}", encoding="utf-8")
    garmin_config.reload_settings()
    try:
        garmin_bot.build_application()
        raise AssertionError("Ожидалась RuntimeError без telegram_bot_token")
    except RuntimeError:
        pass
    print("OK: bot.build_application requires telegram_bot_token")


def test_aggregate_and_mean() -> None:
    rows = [
        {"activity_type": "running", "distance_km": 8.0, "duration_s": 2500},
        {"activity_type": "running", "distance_km": 6.0, "duration_s": 1900},
        {"activity_type": "strength_training", "distance_km": None, "duration_s": 3000},
    ]
    agg = _aggregate_activities(rows)
    assert agg["count"] == 3
    assert agg["by_type"]["running"] == 2
    assert agg["total_distance_m"] == 14000.0
    assert _mean([1.0, 2.0, None, 3.0]) == 2.0
    print("OK: aggregate_activities + mean ->", agg)


def test_aggregate_excludes_low_signal_types() -> None:
    rows = [
        {"activity_type": "running", "distance_km": 8.0, "duration_s": 2500},
        {"activity_type": "walking", "distance_km": 3.0, "duration_s": 1800},
    ]
    agg = _aggregate_activities(rows)
    assert agg["count"] == 1, "walking должен быть исключён из агрегата по умолчанию"
    assert "walking" not in agg["by_type"]
    assert agg["total_distance_m"] == 8000.0
    # exclude_types можно переопределить явно
    agg_all = _aggregate_activities(rows, exclude_types=set())
    assert agg_all["count"] == 2
    print("OK: aggregate excludes low-signal types ->", agg)


def test_analyze_surface() -> None:
    from datetime import date, timedelta

    recent_day = (date.today() - timedelta(days=1)).isoformat()
    with get_connection() as conn:
        upsert_daily_metrics(
            conn, DailyMetrics(date=recent_day, sleep_hours=7.5, hrv_ms=46, rhr=51, stress_avg=20)
        )
        upsert_activity(
            conn,
            ActivitySummary(
                activity_id="analyze-1", date=recent_day, activity_type="running",
                distance_km=5.0, duration_s=1500,
            ),
        )

    ddf = daily_frame(days=30)
    assert not ddf.empty
    assert recent_day in ddf["date"].dt.strftime("%Y-%m-%d").tolist()

    adf = activities_frame(days=30)
    assert not adf.empty
    assert "analyze-1" in adf["activity_id"].tolist()

    cov = coverage(days=30)
    row = cov[cov["date"] == recent_day].iloc[0]
    assert bool(row["has_data"]) is True
    assert int(row["activities"]) >= 1
    print("OK: analyze surface ->", len(ddf), "daily rows,", len(adf), "activities")


def test_monthly_rollup() -> None:
    label = build_monthly_rollup(2026, 7)
    path = TEST_DATA_DIR / "library" / "monthly" / f"{label}.md"
    assert path.exists()
    print("OK: monthly rollup ->", path)
    print(path.read_text(encoding="utf-8"))


def test_raw_payload_roundtrip() -> None:
    with get_connection() as conn:
        assert get_raw_payload(conn, "activity_details", "999") is None
        save_raw_payload(conn, "activity_details", "999", {"metricDescriptors": [], "activityDetailMetrics": []})
        save_raw_payload(conn, "activity_details", "998", {"foo": "bar"})

    with get_connection() as conn:
        payload = get_raw_payload(conn, "activity_details", "999")
        assert payload == {"metricDescriptors": [], "activityDetailMetrics": []}
        # Повторное сохранение того же ключа - перезаписывает, а не дублирует
        save_raw_payload(conn, "activity_details", "999", {"updated": True})
        assert get_raw_payload(conn, "activity_details", "999") == {"updated": True}
        keys = raw_payload_keys(conn, "activity_details")
        assert keys == {"999", "998"}
    print("OK: raw_payload roundtrip")


def test_activity_icon_and_label() -> None:
    assert activity_icon("running") == "🏃"
    assert activity_icon(None) == "🎯"
    assert activity_icon("some_unknown_type") == "🎯"
    assert activity_label_ru("jump_rope") == "Скакалка"
    assert activity_label_ru("totally_custom_type") == "Totally custom type"
    print("OK: activity_icon + activity_label_ru")


def test_exercise_sets_parsing_and_rendering() -> None:
    """get_exercise_sets агрегирует ACTIVE-сеты по упражнению (сеты/повторы/

    вес в кг), игнорирует REST, кэширует сырой ответ в raw_payloads и не
    дёргает Garmin API повторно - см. пользовательский вопрос 'а разве на
    силовой не должны учитываться веса/повторы для анализа'."""

    class _FakeStrengthClient:
        calls = 0

        def get_activity_exercise_sets(self, activity_id):
            self.calls += 1
            return {
                "activityId": int(activity_id),
                "exerciseSets": [
                    {
                        "exercises": [{"category": "SQUAT", "name": None, "probability": 66.4}],
                        "duration": 68.5, "repetitionCount": 20, "weight": 5000.0,
                        "setType": "ACTIVE",
                    },
                    {
                        "exercises": [], "duration": 63.5, "repetitionCount": None,
                        "weight": None, "setType": "REST",
                    },
                    {
                        "exercises": [{"category": "SQUAT", "name": None, "probability": 70.0}],
                        "duration": 71.6, "repetitionCount": 20, "weight": 7500.0,
                        "setType": "ACTIVE",
                    },
                    {
                        "exercises": [
                            {"category": "TRICEPS_EXTENSION", "name": None, "probability": 99.6},
                            {"category": "PULL_UP", "name": "EZ_BAR_PULLOVER", "probability": 20.0},
                        ],
                        "duration": 82.5, "repetitionCount": 22, "weight": None,
                        "setType": "ACTIVE",
                    },
                ],
            }

    assert is_set_based_activity("strength_training")
    assert is_set_based_activity("hiit")
    assert not is_set_based_activity("running")
    assert not is_set_based_activity(None)

    client = _FakeStrengthClient()
    with get_connection() as conn:
        sets = get_exercise_sets(client, "555555", conn=conn)
        assert client.calls == 1
        # Повторный вызов той же активности - из raw_payloads, без нового API-вызова
        sets_again = get_exercise_sets(client, "555555", conn=conn)
        assert client.calls == 1
        assert sets_again == sets

    assert sets["active_sets"] == 3
    assert sets["rest_sets"] == 1
    assert sets["total_rest_s"] == 63.5
    by_name = {e["name"]: e for e in sets["exercises"]}
    assert by_name["Squat"]["sets"] == 2
    assert by_name["Squat"]["reps_total"] == 40
    assert by_name["Squat"]["weight_kg"] == 7.5  # max(5.0, 7.5) кг - вес переведён из граммов
    # Лейбл берётся у экземпляра exercises[] с наибольшей probability в сете
    # (TRICEPS_EXTENSION 99.6% > PULL_UP/EZ_BAR_PULLOVER 20%) - имя (`name`)
    # добавляется в скобках, только если оно есть у *этого* экземпляра.
    assert by_name["Triceps Extension"]["sets"] == 1

    # Карта мышц: считаем сами по справочнику категорий (Garmin её через API не
    # отдаёт - см. _CATEGORY_MUSCLE_GROUPS). 2 приседания -> quadriceps+glutes,
    # 1 трицепс -> triceps => "Квадрицепс"/"Ягодицы" по 2 подхода, "Трицепс" - 1.
    by_muscle = {m["name"]: m["sets"] for m in sets["muscle_groups"]}
    assert by_muscle["Квадрицепс"] == 2
    assert by_muscle["Ягодицы"] == 2
    assert by_muscle["Трицепс"] == 1

    lines = fmt_exercise_sets_lines(sets)
    joined = "\n".join(lines)
    assert "Силовые сеты" in joined
    assert "Squat" in joined and "7.5 кг" in joined
    assert "Мышечные группы" in joined and "Квадрицепс" in joined

    # Пустой/отсутствующий exercise_sets не ломает рендер (бег и т.п.)
    assert fmt_exercise_sets_lines(None) == []
    assert fmt_exercise_sets_lines({"exercises": []}) == []

    md = render_activity_md(
        {
            "activity_id": "555555", "date": "2026-08-06", "type": "strength_training",
            "name": "Сил. трен.", "duration_s": 6060, "avg_hr": 105, "exercise_sets": sets,
        }
    )
    assert "Силовые сеты" in md and "Squat" in md
    print("OK: get_exercise_sets + fmt_exercise_sets_lines + render_activity_md ->", sets["exercises"])


def test_aggregate_by_type_live_dicts() -> None:
    """_aggregate_by_type должен одинаково работать и на 'живых' словарях

    активностей (ключи type/distance_m/...), и на строках кэша (activity_type/
    distance_km/...) - см. аналогичный приём в weekly._aggregate_activities."""
    activities = [
        {"type": "running", "distance_m": 8000, "duration_s": 2400, "avg_hr": 145, "avg_pace_s_per_km": 300, "calories": 500},
        {"type": "running", "distance_m": 6000, "duration_s": 1800, "avg_hr": 150, "avg_pace_s_per_km": 300, "calories": 380},
        {"type": "jump_rope", "distance_m": None, "duration_s": 600, "avg_hr": 130, "calories": 120},
    ]
    agg = _aggregate_by_type(activities)
    assert agg["running"]["count"] == 2
    assert agg["running"]["total_distance_m"] == 14000
    assert agg["running"]["avg_distance_m"] == 7000
    assert agg["running"]["total_duration_s"] == 4200
    assert agg["running"]["avg_hr"] == 148  # round(mean(145, 150))
    assert agg["running"]["total_calories"] == 880
    assert agg["jump_rope"]["count"] == 1
    assert agg["jump_rope"]["total_distance_m"] is None
    print("OK: _aggregate_by_type on live activity dicts ->", agg)


def test_range_report_from_cache_and_render() -> None:
    """Заполняем кэш дневными метриками (шаги + дистанция по шагам) и

    тренировками за диапазон дат, читаем через range_report_from_cache (без
    обращения к Garmin API) и рендерим markdown + HTML-страницу дашборда."""
    with get_connection() as conn:
        upsert_daily_metrics(
            conn, DailyMetrics(date="2026-07-18", steps=8000, distance_m=6200.0, sleep_hours=7.0, hrv_ms=44, rhr=52, stress_avg=22)
        )
        upsert_daily_metrics(
            conn, DailyMetrics(date="2026-07-19", steps=12000, distance_m=9100.0, sleep_hours=6.5, hrv_ms=41, rhr=55, stress_avg=28)
        )
        upsert_activity(
            conn,
            ActivitySummary(
                activity_id="range-1", date="2026-07-18", activity_type="running",
                name="Бег", distance_km=8.0, duration_s=2400, avg_hr=145,
                avg_pace_s_per_km=300, calories=500,
            ),
        )
        upsert_activity(
            conn,
            ActivitySummary(
                activity_id="range-2", date="2026-07-19", activity_type="jump_rope",
                name="Скакалка", distance_km=None, duration_s=600, avg_hr=130, calories=120,
            ),
        )

    report = range_report_from_cache("2026-07-18", "2026-07-19")
    assert report["days_total"] == 2
    assert report["steps_total"] == 20000
    assert report["steps_avg_per_day"] == 10000
    assert report["distance_total_m"] == 6200.0 + 9100.0
    assert report["activities_count"] == 2
    assert report["by_type"]["running"]["count"] == 1
    assert report["by_type"]["jump_rope"]["count"] == 1

    content = render_range_report_md(report)
    assert "Отчёт за период" in content
    assert "🏃" in content and "🪢" in content

    html_page = webapp_templates.range_report_page(report)
    assert "<html" in html_page
    assert "20000" in html_page or "20 000" in html_page  # суммарные шаги где-то на странице
    print("OK: range_report_from_cache + render_range_report_md + range_report_page")


class _PoisonClient:
    """Любое обращение к атрибуту 'падает' - используется, чтобы доказать, что

    для уже закэшированного периода build_range_report НЕ ходит в Garmin API
    (регрессия на баг, из-за которого period-отчёт всегда пересобирался
    заново, даже если данные уже были синхронизированы - см. sync.py)."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(
            f"Неожиданное обращение к Garmin API (client.{name}) для уже закэшированного прошедшего дня"
        )


def test_sync_module_wiring() -> None:
    assert callable(sync_days)
    assert callable(sync_recent_days)
    print("OK: sync.py экспортирует sync_days/sync_recent_days")


def test_build_range_report_skips_already_cached_past_days() -> None:
    """Прошедшие дни, уже засинканные в кэш (weekly/daily/sync/предыдущий

    range-запрос), не должны повторно тянуться из Garmin API - иначе отчёт
    за период никогда не станет "мгновенным", как у самого Garmin Connect."""
    from datetime import date, timedelta

    # Большой offset, чтобы гарантированно не пересечься с другими тестами
    # этого файла, которые используют фиксированные даты в июле 2026 и
    # date.today() - 1 (test_analyze_surface) - иначе activities_count может
    # случайно захватить чужую тестовую активность на той же дате.
    d1 = (date.today() - timedelta(days=200)).isoformat()
    d2 = (date.today() - timedelta(days=199)).isoformat()
    with get_connection() as conn:
        upsert_daily_metrics(conn, DailyMetrics(date=d1, steps=5000, distance_m=4000.0, sleep_hours=7.0))
        upsert_daily_metrics(conn, DailyMetrics(date=d2, steps=6000, distance_m=4500.0, sleep_hours=6.5))
        upsert_activity(
            conn,
            ActivitySummary(activity_id="cached-1", date=d1, activity_type="running", distance_km=5.0, duration_s=1500),
        )

    # _PoisonClient падает при любом обращении - если сюда дойдёт хоть один
    # вызов collect_daily/search_activities, тест упадёт с понятной ошибкой.
    report = build_range_report(_PoisonClient(), d1, d2)
    assert report["steps_total"] == 11000
    assert report["distance_total_m"] == 8500.0
    assert report["activities_count"] == 1
    print("OK: build_range_report не трогает Garmin API для уже закэшированного прошедшего периода ->", report["steps_total"])


def test_ensure_range_synced_skips_cached_days() -> None:
    """То же самое, но на уровне общего примитива sync.py::ensure_range_synced,

    которым пользуются и build_range_report, и export.py, и MCP-инструменты."""
    from datetime import date, timedelta

    d1 = (date.today() - timedelta(days=210)).isoformat()
    d2 = (date.today() - timedelta(days=209)).isoformat()
    with get_connection() as conn:
        upsert_daily_metrics(conn, DailyMetrics(date=d1, steps=1000))
        upsert_daily_metrics(conn, DailyMetrics(date=d2, steps=2000))

    missing = ensure_range_synced(_PoisonClient(), d1, d2)
    assert missing == [], f"Оба дня уже в кэше - не должно быть недостающих, получили {missing}"
    print("OK: ensure_range_synced не трогает Garmin API, если период уже в кэше")


def test_export_raw_range_generic_tool() -> None:
    """export_raw_range - generic-примитив для ad hoc вопросов (см. SKILL.md,

    'Ad hoc analytical questions'): отдаёт сырые дневные метрики и тренировки
    без какой-либо агрегации - считает ответ вызывающая модель, не Python."""
    from datetime import date, timedelta

    d1 = (date.today() - timedelta(days=220)).isoformat()
    d2 = (date.today() - timedelta(days=219)).isoformat()
    with get_connection() as conn:
        upsert_daily_metrics(conn, DailyMetrics(date=d1, steps=7000, distance_m=5500.0, hrv_ms=42.0))
        upsert_daily_metrics(conn, DailyMetrics(date=d2, steps=9000, distance_m=7200.0, hrv_ms=46.0))
        upsert_activity(
            conn,
            ActivitySummary(
                activity_id="export-1", date=d1, activity_type="cycling",
                distance_km=20.5, duration_s=3600, avg_hr=138, calories=650,
            ),
        )

    # Без client - только из кэша (не трогает Garmin API вообще)
    payload = export_raw_range(d1, d2, client=None)
    assert payload["date_from"] == d1 and payload["date_to"] == d2
    assert len(payload["daily"]) == 2
    assert payload["daily"][0]["steps"] == 7000
    assert payload["daily"][0]["distance_m"] == 5500.0
    assert "raw_json" not in payload["daily"][0], "Сырой Garmin-payload не должен утекать в generic-экспорт"
    assert len(payload["activities"]) == 1
    assert payload["activities"][0]["activity_type"] == "cycling"
    assert payload["activities"][0]["distance_km"] == 20.5
    print("OK: export_raw_range отдаёт чистые сырые данные без агрегации ->", payload["daily"])


def test_mcp_server_tools_registered() -> None:
    """Проверяем, что MCP-сервер (garmin_pipeline/mcp_server.py) поднимается и

    регистрирует ожидаемый набор generic-инструментов - без реального запуска
    stdio-транспорта (это делает клиент, см. README, раздел 'MCP-сервер')."""
    import asyncio

    from garmin_pipeline.mcp_server import mcp as mcp_app

    tool_names = {t.name for t in asyncio.run(mcp_app.list_tools())}
    expected = {
        "get_daily_metrics", "get_activities", "find_activities",
        "get_activity_detail", "sync_cache", "build_shareable_range_report",
    }
    assert expected.issubset(tool_names), f"Отсутствуют инструменты: {expected - tool_names}"
    print("OK: MCP-сервер регистрирует инструменты ->", sorted(tool_names))


def test_agent_tools_schema_and_dispatch() -> None:
    """agent_tools.py - схема + диспетчер для агентного Telegram-бота (bot.py):

    каждый инструмент из TOOLS_SCHEMA должен иметь реальную функцию в
    TOOL_FUNCTIONS, WRITE_TOOL_NAMES - подмножество (именно они требуют
    подтверждения перед выполнением, см. describe_call/run_agentic)."""
    names = {t["function"]["name"] for t in agent_tools.TOOLS_SCHEMA}
    assert names == set(agent_tools.TOOL_FUNCTIONS.keys()), "TOOLS_SCHEMA и TOOL_FUNCTIONS расходятся"
    assert agent_tools.WRITE_TOOL_NAMES.issubset(names)
    assert agent_tools.WRITE_TOOL_NAMES == {"create_workout", "delete_workout", "upload_activity_file"}
    for tool in agent_tools.TOOLS_SCHEMA:
        fn = tool["function"]
        assert fn["parameters"]["type"] == "object"
        assert "description" in fn and len(fn["description"]) > 10

    preview = agent_tools.describe_call(
        "create_workout",
        {"sport": "running", "name": "Лёгкий бег", "steps_json": '[{"kind":"warmup","duration_s":300}]'},
    )
    assert "Лёгкий бег" in preview and "бег" in preview

    preview_del = agent_tools.describe_call("delete_workout", {"workout_id": "999"})
    assert "999" in preview_del and "необратимо" in preview_del.lower()

    err = agent_tools.execute_tool("no_such_tool", {})
    assert "error" in err

    assert agent_tools.stringify_tool_result({"a": 1}) == '{"a": 1}'
    assert agent_tools.stringify_tool_result("plain text") == "plain text"
    print("OK: agent_tools schema/dispatch/describe_call ->", sorted(names))


def test_run_agentic_stops_on_write_tool_and_resumes() -> None:
    """Ядро агентного цикла (llm_client.run_agentic/resume_after_confirmation),

    проверенное через injectable chat_fn (без реального обращения к LLM/сети):
    read-инструмент выполняется автоматически и цикл продолжается, а на
    write-инструменте цикл останавливается и требует подтверждения - именно
    это отделяет "агент читает сам" от "агент делает что-то без спроса"
    (см. пользовательский запрос про human-in-the-loop в Telegram-боте)."""
    import json as _json

    tools = [
        {"type": "function", "function": {"name": "get_daily_metrics", "parameters": {}}},
        {"type": "function", "function": {"name": "delete_workout", "parameters": {}}},
    ]
    write_tools = {"delete_workout"}

    def fake_chat_fn(messages: list[dict], _tools: list[dict]) -> dict:
        n_tool_msgs = sum(1 for m in messages if m.get("role") == "tool")
        if n_tool_msgs == 0:
            return {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call_1", "type": "function",
                                 "function": {"name": "get_daily_metrics", "arguments": "{}"}}],
            }
        if n_tool_msgs == 1:
            return {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "call_2", "type": "function",
                                 "function": {"name": "delete_workout",
                                              "arguments": _json.dumps({"workout_id": "42"})}}],
            }
        return {"role": "assistant", "content": "Готово, тренировка удалена.", "tool_calls": None}

    def fake_execute_tool(name: str, args: dict) -> dict:
        if name == "get_daily_metrics":
            return {"steps": 1000}
        if name == "delete_workout":
            return {"deleted": True, "workout_id": args.get("workout_id")}
        raise AssertionError(f"unexpected tool {name}")

    history = [{"role": "system", "content": "sys"}, {"role": "user", "content": "удали тренировку 42"}]

    reply = llm_client.run_agentic(
        history, tools=tools, write_tool_names=write_tools, execute_tool=fake_execute_tool,
        stringify=_json.dumps, chat_fn=fake_chat_fn,
    )
    assert reply.kind == "confirm"
    assert reply.pending.name == "delete_workout"
    assert reply.pending.arguments == {"workout_id": "42"}

    final = llm_client.resume_after_confirmation(
        reply.pending, confirmed=True, tools=tools, write_tool_names=write_tools,
        execute_tool=fake_execute_tool, stringify=_json.dumps, chat_fn=fake_chat_fn,
    )
    assert final.kind == "final" and "удалена" in final.text

    reply2 = llm_client.run_agentic(
        history, tools=tools, write_tool_names=write_tools, execute_tool=fake_execute_tool,
        stringify=_json.dumps, chat_fn=fake_chat_fn,
    )
    cancelled = llm_client.resume_after_confirmation(
        reply2.pending, confirmed=False, tools=tools, write_tool_names=write_tools,
        execute_tool=fake_execute_tool, stringify=_json.dumps, chat_fn=fake_chat_fn,
    )
    tool_msgs = [m for m in cancelled.messages if m.get("role") == "tool"]
    assert any("отклонил" in m["content"] for m in tool_msgs), "Отказ должен попасть в tool-ответ, а не выполниться"
    print("OK: run_agentic останавливается на write-инструменте + resume_after_confirmation (confirm/cancel)")


def test_bot_trim_history_keeps_tool_pairs_intact() -> None:
    """_trim_history (bot.py) должна резать историю только по границе

    user-сообщения - иначе можно оторвать tool-ответ от вызвавшего его
    assistant tool_call и сломать следующий запрос к OpenAI-совместимому API."""
    system = {"role": "system", "content": "sys"}
    messages = [system]
    for i in range(10):
        messages.append({"role": "user", "content": f"q{i}"})
        messages.append({"role": "assistant", "content": None, "tool_calls": [{"id": f"c{i}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": "r"})
        messages.append({"role": "assistant", "content": f"a{i}"})

    trimmed = garmin_bot._trim_history(messages, keep=6)
    assert trimmed[0] == system
    assert trimmed[1]["role"] == "user", "Обрезка должна начинаться с user-сообщения, а не середины tool-пары"
    # Ни один tool-ответ не должен остаться без предшествующего assistant tool_call в этом же срезе
    for i, m in enumerate(trimmed):
        if m.get("role") == "tool":
            assert i > 0 and trimmed[i - 1]["role"] == "assistant"
    print("OK: bot._trim_history режет только по границе user-сообщения ->", len(trimmed), "сообщений")


def test_ollama_setup_status_does_not_crash_without_server() -> None:
    """ollama_setup.status()/list_models() не должны падать исключением, даже

    если Ollama не установлена/не запущена на машине - только это гарантирует
    безопасный вызов из /setup веб-формы у любого пользователя."""
    st = ollama_setup.status()
    assert set(st.keys()) == {"binary_found", "running", "models", "recommended_model", "recommended_pulled", "download_url"}
    assert st["recommended_model"] == "qwen3:4b"
    assert isinstance(st["models"], list)
    print("OK: ollama_setup.status() безопасен без установленной Ollama ->", st)


def test_index() -> None:
    path = update_index()
    assert path.exists()
    print("OK: index ->", path)
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    test_fmt_duration()
    test_compute_km_splits_from_synthetic_track()
    test_fit_records_to_splits()
    test_build_workout()
    test_build_workout_hr_zone_alert()
    test_build_workout_strength_exercise_and_rest_steps()
    test_config_json_overlay_and_reload()
    test_llm_not_configured_error()
    test_bot_chunks_and_authorization()
    test_desktop_app_imports_cleanly()
    test_bot_requires_token()
    test_daily_render_and_write()
    test_weekly_render_and_write()
    test_context_render_and_write()
    test_activity_export_render()
    test_aggregate_and_mean()
    test_aggregate_excludes_low_signal_types()
    test_activity_icon_and_label()
    test_exercise_sets_parsing_and_rendering()
    test_aggregate_by_type_live_dicts()
    test_range_report_from_cache_and_render()
    test_sync_module_wiring()
    test_build_range_report_skips_already_cached_past_days()
    test_ensure_range_synced_skips_cached_days()
    test_export_raw_range_generic_tool()
    test_mcp_server_tools_registered()
    test_raw_payload_roundtrip()
    test_analyze_surface()
    test_monthly_rollup()
    test_agent_tools_schema_and_dispatch()
    test_run_agentic_stops_on_write_tool_and_resumes()
    test_bot_trim_history_keeps_tool_pairs_intact()
    test_ollama_setup_status_does_not_crash_without_server()
    test_index()
    print("\nALL SMOKE TESTS PASSED")

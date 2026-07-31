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
from garmin_pipeline.collectors.activity import compute_km_splits  # noqa: E402
from garmin_pipeline.collectors.daily import DailyBundle  # noqa: E402
from garmin_pipeline.collectors.weekly import _aggregate_activities, _mean  # noqa: E402
from garmin_pipeline.collectors.range_report import _aggregate_by_type, range_report_from_cache  # noqa: E402
from garmin_pipeline.formatting import (  # noqa: E402
    activity_icon,
    activity_label_ru,
    fmt_duration,
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
    test_aggregate_by_type_live_dicts()
    test_range_report_from_cache_and_render()
    test_raw_payload_roundtrip()
    test_analyze_surface()
    test_monthly_rollup()
    test_index()
    print("\nALL SMOKE TESTS PASSED")

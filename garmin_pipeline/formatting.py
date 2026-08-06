"""Утилиты форматирования чисел + markdown-шаблоны для daily/weekly/activity.

Все шаблоны сознательно компактные: цель - минимум токенов на факт,
максимум пользы для модели, которая будет читать файл.
"""

from __future__ import annotations

from typing import Any


def fmt_hms(seconds: float | None) -> str:
    """'7ч30м' - для сна и других мест, где рядом нет значений в метрах/км."""
    if seconds is None:
        return "н/д"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, _s = divmod(rem, 60)
    if h:
        return f"{h}ч{m:02d}м"
    return f"{m}м"


def fmt_duration(seconds: float | None) -> str:
    """'58:57' / '1:02:15' - длительность тренировки в формате секундомера.

    Используется вместо fmt_hms там, где рядом выводится дистанция в км -
    '58м' легко спутать с метрами, а '58:57' однозначно читается как время.
    """
    if seconds is None:
        return "н/д"
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def fmt_pace_from_speed(speed_mps: float | None) -> str:
    """Темп мин/км из скорости в м/с."""
    if not speed_mps:
        return "н/д"
    sec_per_km = 1000.0 / speed_mps
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/км"


def fmt_pace_seconds(sec_per_km: float | None) -> str:
    if not sec_per_km:
        return "н/д"
    m, s = divmod(int(round(sec_per_km)), 60)
    return f"{m}:{s:02d}/км"


def fmt_speed_kmh(sec_per_km: float | None) -> str:
    if not sec_per_km:
        return "н/д"
    return f"{3600.0 / sec_per_km:.1f} км/ч"


def uses_speed_not_pace(activity_type: str | None) -> bool:
    """Велоактивности принято описывать скоростью (км/ч), а не темпом (мин/км)."""
    if not activity_type:
        return False
    t = activity_type.lower()
    return any(k in t for k in ("cycl", "biking", "_ride", "mountain_bik"))


def fmt_tempo(sec_per_km: float | None, activity_type: str | None) -> str:
    """Темп (мин/км) для бега/ходьбы или скорость (км/ч) для велоактивностей."""
    if uses_speed_not_pace(activity_type):
        return fmt_speed_kmh(sec_per_km)
    return fmt_pace_seconds(sec_per_km)


def fmt_km(meters: float | None) -> str:
    if meters is None:
        return "н/д"
    return f"{meters / 1000:.2f}км"


def fmt_num(value: float | int | None, unit: str = "", digits: int = 0) -> str:
    if value is None:
        return "н/д"
    if digits:
        return f"{value:.{digits}f}{unit}"
    return f"{int(round(value))}{unit}"


def fmt_exercise_sets_lines(exercise_sets: dict[str, Any] | None) -> list[str]:
    """Строки с разбивкой по упражнениям (сеты/повторы/вес) - для strength/

    cardio-тренировок, где Garmin распознал сеты (см. collectors.activity.
    get_exercise_sets). Пустой список, если данных нет."""
    exercises = (exercise_sets or {}).get("exercises") or []
    if not exercises:
        return []
    lines = [
        f"Силовые сеты: {exercise_sets['active_sets']} подходов "
        f"(актив {fmt_duration(exercise_sets['total_active_s'])}, "
        f"отдых {fmt_duration(exercise_sets['total_rest_s'])}):"
    ]
    for ex in sorted(exercises, key=lambda e: e["sets"], reverse=True):
        weight_part = f", вес до {ex['weight_kg']:.1f} кг" if ex.get("weight_kg") else ""
        lines.append(f"- {ex['name']}: {ex['sets']} подх., {ex['reps_total']} повт.{weight_part}")
    return lines


_ACTIVITY_ICONS: dict[str, str] = {
    "running": "🏃", "trail_running": "🏃", "treadmill_running": "🏃", "track_running": "🏃",
    "walking": "🚶", "casual_walking": "🚶", "speed_walking": "🚶", "hiking": "🥾",
    "cycling": "🚴", "road_biking": "🚴", "gravel_cycling": "🚴", "indoor_cycling": "🚴",
    "virtual_ride": "🚴", "mountain_biking": "🚵",
    "swimming": "🏊", "lap_swimming": "🏊", "open_water_swimming": "🏊",
    "strength_training": "🏋️", "cardio_training": "❤️", "indoor_cardio": "❤️", "hiit": "🔥",
    "elliptical": "🌀", "rowing": "🚣",
    "yoga": "🧘", "meditation": "🧘", "breathwork": "🌬️", "pilates": "🤸",
    "jump_rope": "🪢",
    "badminton": "🏸", "tennis": "🎾", "table_tennis": "🏓", "volleyball": "🏐",
    "basketball": "🏀", "soccer": "⚽", "golf": "⛳", "boxing": "🥊",
}

_ACTIVITY_LABELS_RU: dict[str, str] = {
    "running": "Бег", "trail_running": "Трейл", "treadmill_running": "Бег на дорожке",
    "track_running": "Бег на стадионе",
    "walking": "Ходьба", "casual_walking": "Ходьба", "speed_walking": "Спортивная ходьба", "hiking": "Поход",
    "cycling": "Велосипед", "road_biking": "Шоссейный велосипед", "gravel_cycling": "Гравийный велосипед",
    "indoor_cycling": "Велотренажёр", "virtual_ride": "Велосипед (виртуально)", "mountain_biking": "Маунтинбайк",
    "swimming": "Плавание", "lap_swimming": "Плавание в бассейне", "open_water_swimming": "Плавание в открытой воде",
    "strength_training": "Силовая", "cardio_training": "Кардио", "indoor_cardio": "Кардио",
    "hiit": "HIIT", "elliptical": "Эллипс",
    "rowing": "Гребля", "yoga": "Йога", "meditation": "Медитация", "breathwork": "Дыхательные практики",
    "pilates": "Пилатес", "jump_rope": "Скакалка", "other": "Другое",
    "badminton": "Бадминтон", "tennis": "Теннис", "table_tennis": "Настольный теннис",
    "volleyball": "Волейбол", "basketball": "Баскетбол", "soccer": "Футбол", "golf": "Гольф", "boxing": "Бокс",
}


def activity_icon(activity_type: str | None) -> str:
    if not activity_type:
        return "🎯"
    return _ACTIVITY_ICONS.get(activity_type.lower(), "🎯")


def activity_label_ru(activity_type: str | None) -> str:
    """Дружелюбное русское название типа активности - для отчёта за период

    и веб-дашборда. Для неизвестных типов - просто заменяем подчёркивания
    пробелами и делаем первую букву заглавной, а не показываем 'н/д'."""
    if not activity_type:
        return "Другое"
    known = _ACTIVITY_LABELS_RU.get(activity_type.lower())
    if known:
        return known
    return activity_type.replace("_", " ").capitalize()


def fmt_delta(current: float | None, previous: float | None, unit: str = "", digits: int = 0) -> str:
    """Компактная запись 'было -> стало (дельта)' для трендов в weekly."""
    if current is None or previous is None:
        return ""
    delta = current - previous
    sign = "+" if delta >= 0 else ""
    if digits:
        return f" ({sign}{delta:.{digits}f}{unit} к пред. неделе)"
    return f" ({sign}{int(round(delta))}{unit} к пред. неделе)"


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------

def render_daily_md(day: dict[str, Any]) -> str:
    """day - результат collectors.daily.collect_daily(...).as_render_dict()."""
    lines: list[str] = []
    lines.append("---")
    lines.append(f"date: {day['date']}")
    lines.append(f"sleep_h: {day.get('sleep_hours')}")
    lines.append(f"hrv_ms: {day.get('hrv_ms')}")
    lines.append(f"rhr: {day.get('rhr')}")
    lines.append(f"stress_avg: {day.get('stress_avg')}")
    if day.get("activities"):
        lines.append(f"activities: {len(day['activities'])}")
    lines.append("---")
    lines.append("")
    lines.append(f"## Дайджест — {day['date']}")
    lines.append("")

    sleep_h = day.get("sleep_hours")
    deep_h = day.get("sleep_deep_hours")
    sleep_score = day.get("sleep_score")
    sleep_line = f"Сон: {fmt_hms((sleep_h or 0) * 3600) if sleep_h is not None else 'н/д'}"
    if deep_h is not None:
        sleep_line += f" (глубокий {fmt_hms(deep_h * 3600)})"
    if sleep_score is not None:
        sleep_line += f", качество: {sleep_score}/100"
    lines.append(sleep_line)

    hrv = day.get("hrv_ms")
    hrv_status = day.get("hrv_status")
    if hrv is not None:
        line = f"HRV: {fmt_num(hrv, ' мс')}"
        if hrv_status:
            line += f" ({hrv_status})"
        lines.append(line)

    stress = day.get("stress_avg")
    if stress is not None:
        lines.append(f"Стресс за день (средний): {fmt_num(stress)}")

    rhr = day.get("rhr")
    if rhr is not None:
        lines.append(f"RHR: {fmt_num(rhr, ' уд/мин')}")

    bb_high, bb_low = day.get("body_battery_high"), day.get("body_battery_low")
    if bb_high is not None or bb_low is not None:
        lines.append(f"Body Battery: {fmt_num(bb_high)} -> {fmt_num(bb_low)}")

    readiness = day.get("training_readiness_score")
    if readiness is not None:
        line = f"Training Readiness: {fmt_num(readiness)}/100"
        feedback = day.get("training_readiness_feedback")
        if feedback:
            line += f" ({feedback})"
        lines.append(line)

    steps = day.get("total_steps")
    if steps is not None:
        lines.append(f"Шаги: {fmt_num(steps)}")

    total_cal, active_cal = day.get("total_calories"), day.get("active_calories")
    if total_cal is not None:
        line = f"Калории: {fmt_num(total_cal, ' ккал')}"
        if active_cal is not None:
            line += f" (активные: {fmt_num(active_cal, ' ккал')})"
        lines.append(line)

    activities = day.get("activities") or []
    if activities:
        lines.append("")
        for act in activities:
            lines.append(f"### Тренировка: {act.get('name') or act.get('type', 'активность')}")
            tempo_label = "скорость" if uses_speed_not_pace(act.get("type")) else "темп"
            lines.append(
                f"{act.get('type', 'н/д')}, {fmt_km(act.get('distance_m'))}, "
                f"{fmt_duration(act.get('duration_s'))}, "
                f"{tempo_label} {fmt_tempo(act.get('avg_pace_s_per_km'), act.get('type'))}, "
                f"avg HR {fmt_num(act.get('avg_hr'))}, "
                f"TE {fmt_num(act.get('training_effect_aerobic'), digits=1)}, "
                f"{fmt_num(act.get('calories'), ' ккал')}"
            )
            splits = act.get("splits_pace")
            if splits:
                lines.append(f"Сплиты по км: {', '.join(splits)}")
            lines.extend(fmt_exercise_sets_lines(act.get("exercise_sets")))
    else:
        lines.append("")
        lines.append("Тренировок в этот день не было.")

    return "\n".join(lines) + "\n"


def render_daily_table(rows: list[dict[str, Any]]) -> list[str]:
    """Таблица 'день - сон - HRV - RHR - стресс - шаги - тренировок' - общая

    для weekly-отчёта и context-снапшота (см. collect_daily().as_summary_row()).
    """
    if not rows:
        return []
    lines = [
        "",
        "| Дата | Сон | HRV | RHR | Стресс | Шаги | Тренировок |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        sleep_h = r.get("sleep_hours")
        sleep_str = fmt_hms(sleep_h * 3600) if sleep_h is not None else "-"
        hrv_str = fmt_num(r["hrv_ms"], digits=0) if r.get("hrv_ms") is not None else "-"
        rhr_str = fmt_num(r["rhr"]) if r.get("rhr") is not None else "-"
        stress_str = fmt_num(r["stress_avg"]) if r.get("stress_avg") is not None else "-"
        steps_str = fmt_num(r["steps"]) if r.get("steps") is not None else "-"
        lines.append(
            f"| {r['date']} | {sleep_str} | {hrv_str} | {rhr_str} | {stress_str} | "
            f"{steps_str} | {r.get('activities_count') or 0} |"
        )
    return lines


# ---------------------------------------------------------------------------
# Weekly
# ---------------------------------------------------------------------------

def render_weekly_md(week: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append(f"week: {week['week_label']}")
    lines.append(f"date_from: {week['date_from']}")
    lines.append(f"date_to: {week['date_to']}")
    lines.append("---")
    lines.append("")
    lines.append(f"## Недельный отчёт — {week['date_from']} – {week['date_to']}")
    lines.append("")

    act = week["activities"]
    distance_km = act["total_distance_m"] / 1000.0 if act.get("total_distance_m") else None
    prev_distance_km = act["prev_total_distance_m"] / 1000.0 if act.get("prev_total_distance_m") else None
    lines.append(
        f"Тренировки: {act['count']} "
        f"({', '.join(f'{v} {k}' for k, v in act['by_type'].items()) or 'нет'}), "
        f"суммарно {fmt_km(act['total_distance_m'])} / {fmt_duration(act['total_duration_s'])}"
        f"{fmt_delta(distance_km, prev_distance_km, ' км', digits=1)}"
    )

    sleep = week["sleep_avg_hours"]
    prev_sleep = week.get("prev_sleep_avg_hours")
    sleep_line = f"Сон в среднем: {fmt_hms((sleep or 0) * 3600) if sleep is not None else 'н/д'}"
    if sleep is not None and prev_sleep is not None:
        delta_min = round((sleep - prev_sleep) * 60)
        sign = "+" if delta_min >= 0 else ""
        sleep_line += f" ({sign}{delta_min} мин к пред. неделе)"
    lines.append(sleep_line)

    hrv = week["hrv_avg_ms"]
    lines.append(
        f"HRV в среднем: {fmt_num(hrv, ' мс', digits=1)}"
        f"{fmt_delta(hrv, week.get('prev_hrv_avg_ms'), ' мс', digits=1)}"
    )

    rhr = week["rhr_avg"]
    lines.append(
        f"RHR в среднем: {fmt_num(rhr, digits=1)}"
        f"{fmt_delta(rhr, week.get('prev_rhr_avg'), digits=1)}"
    )

    stress = week["stress_avg"]
    if stress is not None:
        lines.append(
            f"Стресс в среднем: {fmt_num(stress, digits=1)}"
            f"{fmt_delta(stress, week.get('prev_stress_avg'), digits=1)}"
        )

    missing = week.get("missing_days")
    if missing:
        lines.append("")
        lines.append(f"_Нет данных за: {', '.join(missing)}_")

    lines.extend(render_daily_table(week.get("daily_table") or []))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Context (агрегированный снапшот по запросу)
# ---------------------------------------------------------------------------

def render_context_md(context: dict[str, Any]) -> str:
    """context - результат collectors.context.build_context(...)."""
    lines: list[str] = []
    lines.append("---")
    lines.append(f"date_from: {context['date_from']}")
    lines.append(f"date_to: {context['date_to']}")
    lines.append(f"days: {context['days']}")
    lines.append("---")
    lines.append("")
    lines.append(f"## Снапшот — {context['date_from']} – {context['date_to']}")
    lines.append("")
    lines.append(f"Дней в окне: {context['days']}. Тренировок: {len(context.get('activities') or [])}.")
    lines.extend(render_daily_table(context.get("daily_table") or []))

    activities = context.get("activities") or []
    if activities:
        lines.append("")
        lines.append("### Тренировки за период")
        for act in sorted(activities, key=lambda a: a.get("date") or ""):
            tempo = fmt_tempo(act.get("avg_pace_s_per_km"), act.get("type"))
            lines.append(
                f"- {act.get('date')} — {act.get('name') or act.get('type', 'активность')}: "
                f"{act.get('type', 'н/д')}, {fmt_km(act.get('distance_m'))}, "
                f"{fmt_duration(act.get('duration_s'))}, {tempo}, "
                f"avg HR {fmt_num(act.get('avg_hr'))}"
            )
            for set_line in fmt_exercise_sets_lines(act.get("exercise_sets")):
                lines.append(f"  {set_line}")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Activity (по запросу)
# ---------------------------------------------------------------------------

def render_activity_md(act: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("---")
    lines.append(f"activity_id: {act['activity_id']}")
    lines.append(f"date: {act['date']}")
    lines.append(f"type: {act.get('type')}")
    lines.append("---")
    lines.append("")
    lines.append(f"## Тренировка — {act.get('name') or act.get('type')} ({act['date']})")
    lines.append("")
    is_speed = uses_speed_not_pace(act.get("type"))
    tempo_label = "средняя скорость" if is_speed else "средний темп"
    lines.append(
        f"{act.get('type', 'н/д')}, {fmt_km(act.get('distance_m'))}, "
        f"{fmt_duration(act.get('duration_s'))}, "
        f"{tempo_label} {fmt_tempo(act.get('avg_pace_s_per_km'), act.get('type'))}"
    )
    lines.append(
        f"HR: avg {fmt_num(act.get('avg_hr'))}, max {fmt_num(act.get('max_hr'))}. "
        f"Набор высоты: {fmt_num(act.get('elevation_gain_m'), ' м')}"
    )
    if act.get("calories") is not None:
        lines.append(f"Калории: {fmt_num(act.get('calories'), ' ккал')}")
    if act.get("avg_power") is not None:
        lines.append(f"Мощность: avg {fmt_num(act.get('avg_power'), ' Вт')}, max {fmt_num(act.get('max_power'), ' Вт')}")
    te_a, te_an = act.get("training_effect_aerobic"), act.get("training_effect_anaerobic")
    if te_a is not None:
        lines.append(f"Training Effect: аэробный {fmt_num(te_a, digits=1)}, анаэробный {fmt_num(te_an, digits=1)}")

    # Сплиты по км осмысленны только для дистанционных активностей - лапы без
    # дистанции (например, у медитации/силовой) отфильтровываем.
    splits = [s for s in (act.get("splits") or []) if s.get("distance_m")]
    if splits:
        lines.append("")
        lines.append("Сплиты по км:")
        for s in splits:
            lines.append(
                f"- {s.get('index')}: {fmt_tempo(s.get('pace_s_per_km'), act.get('type'))}, "
                f"HR {fmt_num(s.get('avg_hr'))}"
            )

    exercise_set_lines = fmt_exercise_sets_lines(act.get("exercise_sets"))
    if exercise_set_lines:
        lines.append("")
        lines.extend(exercise_set_lines)

    hr_zones = [z for z in (act.get("hr_zones") or []) if z.get("seconds")]
    if hr_zones:
        lines.append("")
        lines.append("Пульсовые зоны:")
        for z in hr_zones:
            lines.append(
                f"- Зона {z.get('zone')} (от {fmt_num(z.get('low_bpm'))} bpm): "
                f"{fmt_duration(z.get('seconds'))}, {fmt_num(z.get('percent'), '%', digits=0)}"
            )

    if act.get("csv_filename"):
        lines.append("")
        lines.append(
            f"Точки трека с переменным интервалом записи (время/HR/темп/высота): "
            f"см. `{act['csv_filename']}` в той же папке."
        )

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Range report (произвольный период - для веб-дашборда/публикации)
# ---------------------------------------------------------------------------

def render_range_report_md(report: dict[str, Any]) -> str:
    """report - результат collectors.range_report.build_range_report(...)

    или range_report_from_cache(...)."""
    lines: list[str] = []
    lines.append("---")
    lines.append(f"date_from: {report['date_from']}")
    lines.append(f"date_to: {report['date_to']}")
    lines.append(f"days: {report['days_total']}")
    lines.append("---")
    lines.append("")
    lines.append(f"## Отчёт за период — {report['date_from']} – {report['date_to']}")
    lines.append("")
    lines.append(
        f"Дней в периоде: {report['days_total']}. Тренировок: {report['activities_count']}."
    )
    lines.append("")
    lines.append(
        f"Шаги: суммарно {fmt_num(report.get('steps_total'))}, "
        f"в среднем {fmt_num(report.get('steps_avg_per_day'))}/день"
    )
    lines.append(
        f"Пройдено (по шагам): суммарно {fmt_km(report.get('distance_total_m'))}, "
        f"в среднем {fmt_km(report.get('distance_avg_m_per_day'))}/день"
    )

    by_type = report.get("by_type") or {}
    if by_type:
        lines.append("")
        lines.append("### По типам активности")
        for activity_type, agg in sorted(by_type.items(), key=lambda kv: -kv[1]["count"]):
            icon = activity_icon(activity_type)
            label = activity_label_ru(activity_type)
            tempo = fmt_tempo(agg.get("avg_pace_s_per_km"), activity_type)
            lines.append(
                f"- {icon} **{label}** — {agg['count']} шт., "
                f"суммарно {fmt_km(agg.get('total_distance_m'))} / {fmt_duration(agg.get('total_duration_s'))}, "
                f"в среднем {fmt_km(agg.get('avg_distance_m'))} / {fmt_duration(agg.get('avg_duration_s'))}, "
                f"темп/скорость {tempo}, avg HR {fmt_num(agg.get('avg_hr'))}"
            )

    lines.extend(render_daily_table(report.get("daily_table") or []))

    return "\n".join(lines) + "\n"

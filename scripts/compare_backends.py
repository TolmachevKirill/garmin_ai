"""Сверка двух источников данных: официальный Personal API vs неофициальный
python-garminconnect - одни и те же даты, одни и те же коллекторы.

Нужны оба доступа: GARMIN_PERSONAL_API_KEY (.env/config.json) и сохранённая
сессия/логин-пароль для неофициального клиента (`cli login`). Кэш и библиотека
пишутся во временную папку - боевые data/ не трогаются. Ключи не печатаются.

    .venv\\Scripts\\python.exe scripts\\compare_backends.py [--days 7] [--splits]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = tempfile.mkdtemp(prefix="gp_compare_")
os.environ["CACHE_DB_PATH"] = str(Path(_tmp) / "cache.sqlite3")
os.environ["LIBRARY_ROOT"] = str(Path(_tmp) / "library")

from garmin_pipeline import config  # noqa: E402
from garmin_pipeline.client import login_unofficial  # noqa: E402
from garmin_pipeline.collectors.activity import get_hr_zones, search_activities  # noqa: E402
from garmin_pipeline.collectors.daily import collect_daily  # noqa: E402
from garmin_pipeline.collectors.fit import compute_km_splits_with_fallback  # noqa: E402
from garmin_pipeline.collectors.activity import fetch_activity_records  # noqa: E402
from garmin_pipeline.personal_api import PersonalApiClient  # noqa: E402

FIELDS = [
    "sleep_hours", "sleep_deep_hours", "sleep_score", "hrv_ms", "hrv_status", "rhr", "stress_avg",
    "body_battery_high", "body_battery_low", "total_steps", "total_distance_m", "total_calories", "active_calories",
    "training_readiness_score", "training_readiness_feedback",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--splits", action="store_true", help="сверить сплиты и HR-зоны по последним активностям")
    args = parser.parse_args()

    key = config.settings.personal_api_key
    if not key:
        print("Нет GARMIN_PERSONAL_API_KEY")
        return 1
    personal = PersonalApiClient(key)
    unofficial = login_unofficial(interactive=False)

    mismatches = 0
    today = date.today()
    print(f"{'дата':<11}" + "".join(f"{f[:11]:>12}" for f in FIELDS[:0]) + "поле: personal | unofficial")
    for offset in range(args.days):
        d = (today - timedelta(days=offset)).isoformat()
        a = collect_daily(personal, d, with_activity_splits=False)
        b = collect_daily(unofficial, d, with_activity_splits=False)
        diffs = []
        for f in FIELDS:
            va, vb = getattr(a, f), getattr(b, f)
            same = va == vb or (
                isinstance(va, (int, float)) and isinstance(vb, (int, float)) and abs(va - vb) <= max(0.02, abs(vb) * 0.005)
            )
            if not same:
                diffs.append(f"{f}: {va} | {vb}")
        ids_a = sorted(x["activity_id"] for x in a.activities)
        ids_b = sorted(x["activity_id"] for x in b.activities)
        if ids_a != ids_b:
            diffs.append(f"activities: {ids_a} | {ids_b}")
        status = "OK " if not diffs else "DIFF"
        print(f"{d} {status} (активностей: {len(ids_a)})")
        for line in diffs:
            print("      ", line)
        mismatches += len(diffs)

    if args.splits:
        acts = search_activities(personal, date_from=(today - timedelta(days=args.days)).isoformat(), date_to=today.isoformat())
        # сначала активности с дистанцией (велосипед/бег) - у них есть сплиты
        acts.sort(key=lambda a: a.get("distance_m") or 0, reverse=True)
        for act in acts[:5]:
            aid = act["activity_id"]
            za, zb = get_hr_zones(personal, aid), get_hr_zones(unofficial, aid)
            za_c = [(z["zone"], round(z["seconds"]), z["low_bpm"]) for z in za]
            zb_c = [(z["zone"], round(z["seconds"]), z["low_bpm"]) for z in zb]
            ra = fetch_activity_records(personal, aid)
            rb = fetch_activity_records(unofficial, aid)
            sa = compute_km_splits_with_fallback(personal, aid, ra)
            sb = compute_km_splits_with_fallback(unofficial, aid, rb)
            ok_z = za_c == zb_c
            ok_s = len(sa) == len(sb) and all(
                abs((x.get("pace_s_per_km") or 0) - (y.get("pace_s_per_km") or 0)) < 2 for x, y in zip(sa, sb)
            )
            print(f"{aid} {act['type']:<18} зоны: {'OK' if ok_z else 'DIFF'}  сплиты: {'OK' if ok_s else 'DIFF'} "
                  f"(км: {len(sa)} | {len(sb)}, точек: {len(ra)} | {len(rb)})")
            if not ok_z:
                print("      зоны:", za_c, "|", zb_c)
            mismatches += (not ok_z) + (not ok_s)

    print(f"\nИтого расхождений: {mismatches}")
    return 0 if mismatches == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())

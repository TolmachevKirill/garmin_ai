"""Проверка: какие эндпоинты Garmin Personal API реально отвечают на личный ключ.

Ключ читается из переменной GARMIN_PERSONAL_API_KEY (.env в корне проекта).
Ключ и токен никогда не печатаются. Запуск:

    .venv\\Scripts\\python.exe scripts\\probe_personal_api.py

Результат - таблица "эндпоинт -> HTTP-статус, размер, ключи верхнего уровня"
и сохранённые сырые ответы в data/probe/ (для разработки адаптера).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

BASE = "https://personal.connectapi.garmin.com"
TOKEN_URL = f"{BASE}/personalapitoken-service/personal-api/personal-api-key/token"
OUT_DIR = ROOT / "data" / "probe"  # data/ в .gitignore


def get_token(api_key: str) -> str:
    r = requests.post(TOKEN_URL, headers={"Authorization": f"ApiKey {api_key}"}, timeout=30)
    if r.status_code != 200:
        print(f"Токен не получен: HTTP {r.status_code}")
        sys.exit(1)
    # Garmin отдаёт токен как text/plain (JWT), не JSON; на всякий случай
    # поддерживаем и JSON-вариант.
    text = r.text.strip()
    if text.startswith("{"):
        data = r.json()
        text = data.get("access_token") or data.get("accessToken") or data.get("token") or ""
    if not text:
        print("Пустой токен в ответе")
        sys.exit(1)
    return text


def shape(obj) -> str:
    if isinstance(obj, dict):
        return "dict: " + ", ".join(list(obj)[:8]) + (" ..." if len(obj) > 8 else "")
    if isinstance(obj, list):
        return f"list[{len(obj)}]" + (f" of {shape(obj[0])}" if obj else "")
    return type(obj).__name__


def main() -> int:
    api_key = os.getenv("GARMIN_PERSONAL_API_KEY", "").strip()
    if not api_key:
        print("Нет GARMIN_PERSONAL_API_KEY в .env")
        return 1

    token = get_token(api_key)
    headers = {"Authorization": f"Bearer {token}"}
    today = date.today()
    d = today.isoformat()
    d7 = (today - timedelta(days=7)).isoformat()
    d400 = (today - timedelta(days=400)).isoformat()
    d90 = (today - timedelta(days=90)).isoformat()

    # {activity_id} подставим из списка активностей
    probes: list[tuple[str, str]] = [
        ("activities (последние 5)", "/activitylist-service/activities/search/activities?start=0&limit=5"),
        ("activities (за 90 дней назад, глубина истории)",
         f"/activitylist-service/activities/search/activities?start=0&limit=5&startDate={d90}&endDate={d90}"),
        ("dailysummaries 7 дней", f"/usersummary-service/v2/dailysummaries?startDate={d7}&endDate={d}"),
        ("dailysummaries 400 дней назад (глубина истории)",
         f"/usersummary-service/v2/dailysummaries?startDate={d400}&endDate={d400}"),
        ("sleep (сегодня)", f"/sleep-service/sleep/dailySleep?date={d}"),
        ("hrv (сегодня)", f"/hrv-service/hrv/{d}"),
        ("hrv summaries", f"/hrv-service/hrv/daily/{d7}/{d}"),
        ("heart rate zones", "/biometric-service/heartRateZones/v2"),
        ("body battery", f"/wellness-service/wellness/bodyBattery/reports/daily?startDate={d7}&endDate={d}"),
        ("steps", f"/usersummary-service/stats/steps/daily/{d7}/{d}"),
        ("training readiness (может не быть)", f"/metrics-service/metrics/trainingreadiness/{d}"),
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    first_activity_id = None

    def run(name: str, path: str) -> dict | list | None:
        nonlocal first_activity_id
        r = requests.get(BASE + path, headers=headers, timeout=60)
        body = None
        try:
            body = r.json()
        except ValueError:
            pass
        info = shape(body) if body is not None else f"не JSON, {len(r.content)} байт"
        print(f"[{r.status_code}] {name}\n      {path.split('?')[0]}\n      {info}")
        if body is not None and r.status_code == 200:
            fname = "".join(c if c.isalnum() else "_" for c in name)[:60] + ".json"
            (OUT_DIR / fname).write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        return body

    for name, path in probes:
        body = run(name, path)
        if name.startswith("activities (последние") and isinstance(body, list) and body:
            first_activity_id = body[0].get("activityId")

    if first_activity_id:
        aid = first_activity_id
        for name, path in [
            ("activity detail", f"/activity-service/activity/{aid}"),
            ("activity hr zones", f"/activity-service/activity/{aid}/hrTimeInZones"),
            ("activity splits", f"/activity-service/activity/{aid}/splits"),
            ("activity details (time series)", f"/activity-service/activity/{aid}/details"),
            ("activity exercise sets", f"/activity-service/activity/{aid}/exerciseSets"),
        ]:
            run(name, path)
        # скачивание оригинала (ZIP с FIT) - проверяем только статус и размер
        for dl in (f"/download-service/files/activity/{aid}",):
            r = requests.get(BASE + dl, headers=headers, timeout=120)
            print(f"[{r.status_code}] FIT download\n      {dl}\n      {len(r.content)} байт, "
                  f"content-type={r.headers.get('content-type')}")
    else:
        print("Нет активностей - пропускаю проверку деталей/FIT")

    print(f"\nСырые ответы сохранены в {OUT_DIR} (gitignored).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

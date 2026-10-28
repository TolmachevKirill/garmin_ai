"""Клиент официального Garmin Connect Personal API (только чтение).

С октября 2026 Garmin даёт каждому пользователю создать на сайте Garmin Connect
личный API-ключ (страница "Personal API Key") и читать свои данные официально -
без пароля/MFA и без неофициальной эмуляции мобильного приложения:
https://developer.garmin.com/gc-developer-program/personal/personal-faq/

Ключ меняется на access-токен (живёт 24 часа, refresh-токенов нет), поэтому
токен тут получается лениво и обновляется сам. Ключ и токен никогда не
логируются.

Класс PersonalApiClient повторяет ровно те методы `garminconnect.Garmin`,
которыми пользуются коллекторы (get_activities, get_activities_by_date,
get_activity_details, get_activity_hr_in_timezones, download_activity и
`typed.get_stats/get_sleep_data/get_hrv_data/get_training_readiness`), так что
остальной код (кэш, отчёты, бот, MCP) не знает, откуда пришли данные.

Что Personal API НЕ умеет (проверено на реальном ключе, октябрь 2026):
- запись (создание тренировок, загрузка FIT) - он read-only;
- training readiness (/metrics-service/.../trainingreadiness -> 404);
- отдельные /hrTimeInZones и /splits (зоны берём из строки активности -
  там есть hrTimeInZone_1..5, сплиты считаем сами по FIT/time-series).
Для этого есть "запасной" неофициальный клиент (fallback_factory): любой
метод, которого нет у этого класса, прозрачно делегируется ему (`__getattr__`),
а readiness сначала пробуется через Personal API (вдруг Garmin добавит
эндпоинт) и после 404 уходит в fallback. Если fallback недоступен (нет
логина/пароля) - читающие вызовы возвращают пустой результат, а запись падает
с понятной PersonalApiUnavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import httpx
from garminconnect import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"

# Токен живёт 24 часа (или до истечения ключа); обновляем с запасом.
_TOKEN_TTL_S = 23 * 3600
# Garmin отдаёт максимум 200 активностей за запрос (на 1000 - HTTP 500).
_MAX_PAGE = 200
_BY_DATE_PAGE = 100
_RETRIES = 3

# Сообщение, по которому collectors/activity.py::_is_subtype_error узнаёт
# "фильтр по подтипу не поддерживается" и откатывается на клиентскую фильтрацию.
_SUBTYPE_MESSAGE = "Activity type cannot be an activity sub type"


class PersonalApiUnavailable(RuntimeError):
    """Операция недоступна через Personal API и нет запасного (неофициального) клиента."""


class _NotFound(GarminConnectConnectionError):
    """HTTP 404 - эндпоинт/данные отсутствуют (не путать с сетевой ошибкой)."""


class _Obj:
    """Лёгкий аналог pydantic-модели из garminconnect[typed].

    Атрибуты - то, что читают коллекторы; отсутствующие дают None (как Optional-
    поля у настоящих моделей). model_dump() отдаёт сырой dict для raw_payloads.
    """

    def __init__(self, raw: Any, **attrs: Any) -> None:
        self._raw = raw
        self.__dict__.update(attrs)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return None

    def model_dump(self, **_kwargs: Any) -> Any:
        return self._raw


def _num(value: Any) -> Any:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class _TypedFacade:
    """Аналог `Garmin.typed` - только методы, нужные пайплайну."""

    def __init__(self, client: "PersonalApiClient") -> None:
        self._c = client

    def get_stats(self, date_str: str) -> _Obj | None:
        # Основной путь: тот же ответ "дневной сводки", что у неофициального
        # клиента (в т.ч. totalDistanceMeters со всеми активностями).
        try:
            full = self._c._get_json("/usersummary-service/usersummary/daily", {"calendarDate": date_str})
        except _NotFound:
            full = None
        if isinstance(full, dict) and full.get("totalSteps") is not None:
            return _Obj(
                full,
                resting_heart_rate=_num(full.get("restingHeartRate")),
                average_stress_level=_num(full.get("averageStressLevel")),
                body_battery_highest_value=_num(full.get("bodyBatteryHighestValue")),
                body_battery_lowest_value=_num(full.get("bodyBatteryLowestValue")),
                total_steps=_num(full.get("totalSteps")),
                total_distance_meters=_num(full.get("totalDistanceMeters")),
                total_kilocalories=_num(full.get("totalKilocalories")),
                active_kilocalories=_num(full.get("activeKilocalories")),
            )
        return self._stats_from_dailysummaries(date_str)

    def _stats_from_dailysummaries(self, date_str: str) -> _Obj | None:
        """Запасной путь, если /usersummary/daily недоступен: v2/dailysummaries
        (шаги/дистанция там - только ходьба, без дистанции тренировок)."""
        data = self._c._get_json(
            "/usersummary-service/v2/dailysummaries", {"startDate": date_str, "endDate": date_str}
        )
        days = (data or {}).get("data") or []
        day = next((d for d in days if d.get("calendarDate") == date_str), None)
        if not day:
            return None

        heart = day.get("heartRate") or {}
        stress = day.get("stress") or {}
        battery = day.get("bodyBattery") or {}
        calories = day.get("calories") or {}
        steps = (day.get("movement") or {}).get("steps") or {}

        attrs = {
            "resting_heart_rate": _num(heart.get("restingValue")),
            "average_stress_level": _num(stress.get("avgLevel")),
            "body_battery_highest_value": _num(battery.get("maxValue")),
            "body_battery_lowest_value": _num(battery.get("minValue")),
            "total_steps": _num(steps.get("value")),
            "total_distance_meters": _num(steps.get("distanceInMeters")),
            "total_kilocalories": _num(calories.get("burnedTotal")),
            "active_kilocalories": _num(calories.get("burnedActive")),
        }
        raw = {
            "calendarDate": date_str,
            "restingHeartRate": attrs["resting_heart_rate"],
            "averageStressLevel": attrs["average_stress_level"],
            "bodyBatteryHighestValue": attrs["body_battery_highest_value"],
            "bodyBatteryLowestValue": attrs["body_battery_lowest_value"],
            "totalSteps": attrs["total_steps"],
            "totalDistanceMeters": attrs["total_distance_meters"],
            "totalKilocalories": attrs["total_kilocalories"],
            "activeKilocalories": attrs["active_kilocalories"],
            "personalApiDailySummary": day,
        }
        return _Obj(raw, **attrs)

    def get_sleep_data(self, date_str: str) -> _Obj | None:
        try:
            data = self._c._get_json("/sleep-service/sleep/dailySleep", {"date": date_str})
        except _NotFound:
            return None
        if not isinstance(data, dict) or not data:
            return None
        scores = data.get("sleepScores") or {}
        overall = scores.get("overall") or {}
        dto = _Obj(
            data,
            sleep_time_seconds=_num(data.get("sleepTimeSeconds")),
            deep_sleep_seconds=_num(data.get("deepSleepSeconds")),
            sleep_scores=_Obj(scores, overall=_Obj(overall, value=_num(overall.get("value")))),
        )
        # Форма сырого ответа как у неофициального API ({"dailySleepDTO": {...}}),
        # чтобы raw_payloads не зависел от того, откуда пришли данные.
        return _Obj({"dailySleepDTO": data}, daily_sleep_dto=dto)

    def get_hrv_data(self, date_str: str) -> _Obj | None:
        try:
            data = self._c._get_json(f"/hrv-service/hrv/{date_str}")
        except _NotFound:
            return None
        if not isinstance(data, dict) or not data.get("hrvSummary"):
            return None
        summary = data["hrvSummary"]
        return _Obj(
            data,
            hrv_summary=_Obj(summary, last_night_avg=_num(summary.get("lastNightAvg")), status=summary.get("status")),
        )

    def get_training_readiness(self, date_str: str) -> list[Any]:
        # Эндпоинта в Personal API на сегодня нет (404) - пробуем один раз за
        # жизнь клиента, дальше сразу fallback (если он есть).
        path = f"/metrics-service/metrics/trainingreadiness/{date_str}"
        if "readiness" not in self._c._unsupported:
            try:
                data = self._c._get_json(path)
                items = data if isinstance(data, list) else ([data] if data else [])
                return [
                    _Obj(
                        item,
                        timestamp=item.get("timestamp") or item.get("timestampLocal"),
                        score=_num(item.get("score")),
                        feedback_short=item.get("feedbackShort"),
                        level=item.get("level"),
                    )
                    for item in items
                    if isinstance(item, dict)
                ]
            except _NotFound:
                self._c._unsupported.add("readiness")
        fb = self._c._fallback_or_none()
        if fb is None:
            return []
        return fb.typed.get_training_readiness(date_str)


class PersonalApiClient:
    """Drop-in замена `garminconnect.Garmin` для чтения данных (см. docstring модуля)."""

    def __init__(
        self,
        api_key: str,
        *,
        fallback_factory: Callable[[], Any] | None = None,
        transport: httpx.BaseTransport | None = None,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = api_key.strip()
        self._fallback_factory = fallback_factory
        self._fallback_client: Any = None
        self._fallback_failed: str | None = None
        self._http = httpx.Client(base_url=BASE_URL, timeout=60.0, transport=transport)
        self._sleep = retry_sleep
        self._token: str | None = None
        self._token_at = 0.0
        self._unsupported: set[str] = set()
        self._activity_index: dict[str, dict[str, Any]] = {}
        self._zone_floors: list[int] | None = None
        self.typed = _TypedFacade(self)

    # ---------------------------------------------------------------- auth/http

    def ensure_token(self) -> str:
        """Токен из ключа; кэшируется на ~23 ч. Бросает GarminConnectAuthenticationError
        при неверном/просроченном/отозванном ключе."""
        if self._token and time.time() - self._token_at < _TOKEN_TTL_S:
            return self._token
        try:
            resp = self._http.post(TOKEN_PATH, headers={"Authorization": f"ApiKey {self._api_key}"})
        except httpx.HTTPError as err:
            raise GarminConnectConnectionError(f"Не удалось связаться с Garmin Personal API: {err}") from err
        if resp.status_code in (400, 401, 403):
            raise GarminConnectAuthenticationError(
                "Garmin Personal API отклонил ключ (неверный, просрочен или отозван). "
                "Создай новый на странице Personal API Key в Garmin Connect."
            )
        if resp.status_code == 429:
            raise GarminConnectTooManyRequestsError("Garmin ограничил количество запросов (token)")
        if resp.status_code != 200:
            raise GarminConnectConnectionError(f"Garmin Personal API: токен не получен, HTTP {resp.status_code}")
        text = resp.text.strip()
        if text.startswith("{"):  # на случай, если Garmin сменит text/plain на JSON
            payload = resp.json()
            text = payload.get("access_token") or payload.get("accessToken") or payload.get("token") or ""
        if not text:
            raise GarminConnectConnectionError("Garmin Personal API вернул пустой токен")
        self._token, self._token_at = text, time.time()
        return text

    def _request(self, path: str, params: dict[str, Any] | None) -> httpx.Response:
        refreshed = False
        last_err: Exception | None = None
        for attempt in range(_RETRIES):
            token = self.ensure_token()
            try:
                resp = self._http.get(path, params=params, headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as err:
                last_err = GarminConnectConnectionError(f"Ошибка сети при запросе {path.split('?')[0]}: {err}")
                self._sleep(2**attempt)
                continue
            if resp.status_code == 401 and not refreshed:
                self._token = None  # токен мог протухнуть раньше срока - берём новый один раз
                refreshed = True
                continue
            if resp.status_code in (401, 403):
                raise GarminConnectAuthenticationError(f"Garmin Personal API: нет доступа к {path.split('?')[0]}")
            if resp.status_code == 404:
                raise _NotFound(f"404 {path.split('?')[0]}")
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = (
                    GarminConnectTooManyRequestsError("Garmin ограничил количество запросов")
                    if resp.status_code == 429
                    else GarminConnectConnectionError(f"HTTP {resp.status_code} {path.split('?')[0]}")
                )
                self._sleep(2**attempt)
                continue
            if resp.status_code >= 400:
                raise GarminConnectConnectionError(f"HTTP {resp.status_code} {path.split('?')[0]}: {resp.text[:200]}")
            return resp
        raise last_err or GarminConnectConnectionError(f"Не удалось выполнить запрос {path.split('?')[0]}")

    def _get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        resp = self._request(path, params)
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError as err:
            raise GarminConnectConnectionError(f"Не-JSON ответ от {path.split('?')[0]}") from err

    # ------------------------------------------------------------------ fallback

    def _fallback_or_none(self) -> Any | None:
        if self._fallback_client is not None:
            return self._fallback_client
        if self._fallback_factory is None or self._fallback_failed is not None:
            return None
        try:
            self._fallback_client = self._fallback_factory()
        except Exception as err:  # noqa: BLE001 - любая причина "нет логина" = нет fallback
            self._fallback_failed = str(err)
            logger.info("Запасной клиент Garmin недоступен: %s", err)
            return None
        return self._fallback_client

    def _require_fallback(self, what: str) -> Any:
        fb = self._fallback_or_none()
        if fb is None:
            reason = f" ({self._fallback_failed})" if self._fallback_failed else ""
            raise PersonalApiUnavailable(
                f"«{what}» недоступно через Garmin Personal API (он только для чтения) — "
                "для этого нужен вход по логину/паролю Garmin: задай email/пароль в /setup "
                f"или выполни `cli login`.{reason}"
            )
        return fb

    def __getattr__(self, name: str) -> Any:
        # Вызывается только для атрибутов, которых нет у самого класса -
        # то есть для всего, что Personal API не умеет (запись, upload_*, get_workouts...).
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._require_fallback(name), name)

    # ---------------------------------------------------------------- activities

    def _remember(self, items: Any) -> list[dict[str, Any]]:
        page = items if isinstance(items, list) else []
        for item in page:
            if isinstance(item, dict) and item.get("activityId") is not None:
                self._activity_index[str(item["activityId"])] = item
        return page

    def _activities_page(self, params: dict[str, Any], activity_type: str | None) -> list[dict[str, Any]]:
        try:
            data = self._get_json("/activitylist-service/activities/search/activities", params)
        except GarminConnectConnectionError as err:
            # Garmin на фильтр по подтипу (virtual_ride, yoga, ...) отвечает 400 без
            # тела - подставляем текст, по которому activity.py откатится на
            # клиентскую фильтрацию (как и с неофициальным API).
            if activity_type and "HTTP 400" in str(err):
                raise GarminConnectConnectionError(f"400: {_SUBTYPE_MESSAGE}") from err
            raise
        return self._remember(data)

    def get_activities(self, start: int = 0, limit: int = 20, activitytype: str | None = None, **_ignored: Any):
        out: list[dict[str, Any]] = []
        while len(out) < limit:
            page_limit = min(_MAX_PAGE, limit - len(out))
            params: dict[str, Any] = {"start": start + len(out), "limit": page_limit}
            if activitytype:
                params["activityType"] = activitytype
            page = self._activities_page(params, activitytype)
            out.extend(page)
            if len(page) < page_limit:
                break
        return out

    def get_activities_by_date(
        self,
        startdate: str,
        enddate: str | None = None,
        activitytype: str | None = None,
        sortorder: str | None = None,
    ):
        out: list[dict[str, Any]] = []
        start = 0
        while True:
            params: dict[str, Any] = {"startDate": startdate, "start": start, "limit": _BY_DATE_PAGE}
            if enddate:
                params["endDate"] = enddate
            if activitytype:
                params["activityType"] = activitytype
            if sortorder:
                params["sortOrder"] = sortorder
            page = self._activities_page(params, activitytype)
            out.extend(page)
            if len(page) < _BY_DATE_PAGE:
                return out
            start += _BY_DATE_PAGE

    def get_activity_details(self, activity_id: Any, maxchart: int = 2000, maxpoly: int = 4000):
        return self._get_json(
            f"/activity-service/activity/{activity_id}/details",
            {"maxChartSize": maxchart, "maxPolylineSize": maxpoly},
        )

    def _heart_rate_zone_floors(self) -> list[int]:
        if self._zone_floors is None:
            data = self._get_json("/biometric-service/heartRateZones/v2")
            profiles = data if isinstance(data, list) else []
            profile = next((p for p in profiles if p.get("sport") == "DEFAULT"), profiles[0] if profiles else {})
            self._zone_floors = [int(profile.get(f"zone{i}Floor") or 0) for i in range(1, 6)]
        return self._zone_floors

    def _find_activity_summary(self, activity_id: str) -> dict[str, Any] | None:
        """Строка активности из списка (в ней есть hrTimeInZone_1..5). Если её ещё
        не видели - берём дату из деталей и ищем в списке за этот день."""
        item = self._activity_index.get(str(activity_id))
        if item is not None:
            return item
        try:
            detail = self._get_json(f"/activity-service/activity/{activity_id}")
        except GarminConnectConnectionError:
            return None
        summary = (detail or {}).get("summaryDTO") or {}
        day = (summary.get("startTimeLocal") or "")[:10]
        if not day:
            return None
        self.get_activities_by_date(day, day)
        return self._activity_index.get(str(activity_id))

    def get_activity_hr_in_timezones(self, activity_id: Any):
        """Время в пульсовых зонах в формате неофициального API:
        [{"zoneNumber", "secsInZone", "zoneLowBoundary"}, ...]."""
        item = self._find_activity_summary(str(activity_id))
        if item is None:
            return []
        floors = self._heart_rate_zone_floors()
        zones = []
        for n in range(1, 6):
            secs = item.get(f"hrTimeInZone_{n}")
            if secs is None:
                continue
            zones.append({"zoneNumber": n, "secsInZone": secs, "zoneLowBoundary": floors[n - 1]})
        return zones

    def get_activity_exercise_sets(self, activity_id: Any):
        try:
            return self._get_json(f"/activity-service/activity/{activity_id}/exerciseSets")
        except _NotFound:
            # Эндпоинт в Personal API работает, но для активностей без
            # распознанных подходов (бег/вело/свежая запись) отвечает 404 -
            # это "подходов нет", а не "эндпоинта нет" (неофициальный API
            # в этом случае отдаёт exerciseSets: null).
            return {"activityId": int(activity_id), "exerciseSets": None}

    def download_activity(self, activity_id: Any, dl_fmt: Any = None) -> bytes:
        """Оригинальный FIT (в zip). dl_fmt оставлен для совместимости сигнатуры -
        Personal API отдаёт только оригинал."""
        return self._request(f"/download-service/files/activity/{activity_id}", None).content

    def close(self) -> None:
        self._http.close()

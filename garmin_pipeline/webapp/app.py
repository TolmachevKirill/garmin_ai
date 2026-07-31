"""Локальное веб-приложение: страница настройки (/setup) + дашборд (/dashboard).

FastAPI + Uvicorn - лёгкие, асинхронные, дружелюбны к PyInstaller (см. Фазу 10
плана). Однопользовательский локальный инструмент - без сессий/аутентификации,
предполагается, что сервер слушает только localhost (см. desktop_app.py).
"""

from __future__ import annotations

from datetime import date as date_cls
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from garmin_pipeline import config
from garmin_pipeline.cache import get_connection, upsert_activity, upsert_daily_metrics
from garmin_pipeline.client import get_client
from garmin_pipeline.collectors.context import build_context
from garmin_pipeline.collectors.daily import collect_daily
from garmin_pipeline.collectors.range_report import build_range_report, range_report_from_cache
from garmin_pipeline.collectors.weekly import _activity_to_summary, build_weekly_report  # noqa: F401 (переиспользуем агрегатор)
from garmin_pipeline.formatting import render_context_md, render_daily_md, render_range_report_md, render_weekly_md
from garmin_pipeline.library import (
    library_summary,
    read_library_file,
    update_index,
    write_context,
    write_daily,
    write_range_report,
    write_weekly,
)
from garmin_pipeline.webapp import templates

_KNOWN_CATEGORIES = {"daily", "weekly", "monthly", "activities", "context", "range"}


def create_app() -> FastAPI:
    app = FastAPI(title="Garmin Health Pipeline")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        target = "/dashboard" if config.settings.email else "/setup"
        return RedirectResponse(url=target)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        # Иконка вкладки задаётся data-URI в <head> (см. templates._FAVICON) -
        # этот роут просто убирает шумный 404 в логах от дефолтного запроса браузера.
        return Response(status_code=204)

    @app.get("/setup", response_class=HTMLResponse)
    def setup_get(request: Request) -> HTMLResponse:
        flash = request.query_params.get("flash")
        return HTMLResponse(templates.setup_page(config.settings, flash=flash))

    @app.post("/setup")
    def setup_post(
        garmin_email: str = Form(""),
        garmin_password: str = Form(""),
        llm_base_url: str = Form(""),
        llm_api_key: str = Form(""),
        llm_model: str = Form(""),
        telegram_bot_token: str = Form(""),
        telegram_allowed_user_id: str = Form(""),
    ) -> RedirectResponse:
        config.save_config_json(
            {
                "garmin_email": garmin_email.strip(),
                "garmin_password": garmin_password,  # без .strip() - пароль как есть
                "llm_base_url": llm_base_url.strip(),
                "llm_api_key": llm_api_key.strip(),
                "llm_model": llm_model.strip(),
                "telegram_bot_token": telegram_bot_token.strip(),
                "telegram_allowed_user_id": telegram_allowed_user_id.strip(),
            }
        )
        return RedirectResponse(url=f"/dashboard?flash={quote('Настройки сохранены')}", status_code=303)

    @app.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        flash = request.query_params.get("flash")
        summary = library_summary()
        return HTMLResponse(templates.dashboard_page(summary, config.settings, flash=flash))

    @app.post("/dashboard/run/context")
    def run_context() -> RedirectResponse:
        client = get_client(interactive=False)
        ctx = build_context(client, days=14)
        write_context(render_context_md(ctx))
        update_index()
        return RedirectResponse(url=f"/dashboard?flash={quote('Снапшот обновлён')}", status_code=303)

    @app.post("/dashboard/run/daily")
    def run_daily() -> RedirectResponse:
        client = get_client(interactive=False)
        today = date_cls.today().isoformat()
        with get_connection() as conn:
            bundle = collect_daily(client, today, conn=conn)
            upsert_daily_metrics(conn, bundle.to_cache_metrics())
            for act in bundle.activities:
                upsert_activity(conn, _activity_to_summary(act))
        write_daily(today, render_daily_md(bundle.as_render_dict()))
        update_index()
        return RedirectResponse(url=f"/dashboard?flash={quote('Дневной отчёт собран')}", status_code=303)

    @app.post("/dashboard/run/weekly")
    def run_weekly() -> RedirectResponse:
        client = get_client(interactive=False)
        week = build_weekly_report(client)
        write_weekly(week["week_label"], render_weekly_md(week))
        update_index()
        return RedirectResponse(url=f"/dashboard?flash={quote('Недельный отчёт собран')}", status_code=303)

    @app.post("/dashboard/run/range")
    def run_range(date_from: str = Form(...), date_to: str = Form(...)) -> RedirectResponse:
        client = get_client(interactive=False)
        report = build_range_report(client, date_from, date_to)
        write_range_report(date_from, date_to, render_range_report_md(report))
        update_index()
        return RedirectResponse(url=f"/range?from={date_from}&to={date_to}", status_code=303)

    @app.get("/range", response_class=HTMLResponse)
    def range_view(request: Request) -> HTMLResponse:
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")
        if not date_from or not date_to:
            return HTMLResponse(templates.view_page("Ошибка", "Не указан период (from/to)."), status_code=400)
        # Читаем из кэша (см. range_report.py) - без похода в Garmin API, так
        # что страницу можно спокойно перезагружать/расшаривать без лимитов.
        report = range_report_from_cache(date_from, date_to)
        return HTMLResponse(templates.range_report_page(report))

    @app.get("/view", response_class=HTMLResponse)
    def view(category: str, name: str) -> HTMLResponse:
        if category not in _KNOWN_CATEGORIES or "/" in name or ".." in name:
            return HTMLResponse(templates.view_page("Ошибка", "Некорректный путь."), status_code=400)
        relative = "context.md" if category == "context" else f"{category}/{name}"
        content = read_library_file(relative)
        if content is None:
            return HTMLResponse(templates.view_page(name, "Файл не найден."), status_code=404)
        return HTMLResponse(templates.view_page(name, content))

    return app

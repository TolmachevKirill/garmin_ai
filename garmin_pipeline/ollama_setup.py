"""Инфраструктура "легко подтянуть Ollama и модель" - сама Ollama/модель НЕ

часть репозитория (см. README) - это внешний рантайм (~700 МБ бинарник) и
веса модели (~2.5 ГБ для рекомендованной qwen3:4b), которые пользователь
ставит один раз сам. Этот модуль убирает ручную работу с консолью до
минимума: проверка статуса, best-effort автоустановка через системный пакетный
менеджер (winget/brew/install.sh) и скачивание модели с прогрессом - для CLI
(`cli.py ollama ...`) и для кнопки в веб-форме `/setup` (см. webapp/app.py).

Общение с Ollama - только через её локальный HTTP API (localhost:11434), а не
через CLI-бинарник `ollama` в PATH: это работает, даже если PATH не обновился
после установки, потому что сам сервис (то, что реально нужно для tool-calling
из бота) - это фоновый процесс/трей-иконка, а не переменная окружения.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import Any

import httpx

OLLAMA_BASE_URL = "http://localhost:11434"

# qwen3:4b - см. обсуждение в чате: лучший баланс надёжности function-calling
# (Qwen3 держит большинство верхних строк Berkeley Function-Calling Leaderboard
# среди open-моделей) и размера (Q4_K_M ~2.5 ГБ на диске, ~3.8-4 ГБ в памяти
# GPU при обычном контексте) - тянет любой современный ноутбук с GPU 4-6 ГБ
# или Apple Silicon Mac с 8+ ГБ unified memory, и терпимо работает даже на CPU.
RECOMMENDED_MODEL = "qwen3:4b"

DOWNLOAD_URL = "https://ollama.com/download"


def is_running(timeout: float = 1.5) -> bool:
    """Отвечает ли локальный сервис Ollama (фоновый процесс/трей-иконка) на localhost:11434."""
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=timeout)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def list_models() -> list[str]:
    """Имена уже скачанных локально моделей (пусто, если сервис не отвечает)."""
    try:
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3.0)
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    return [m.get("name", "") for m in (r.json().get("models") or [])]


def find_binary() -> str | None:
    """Путь к CLI-бинарнику `ollama`, если он есть в PATH (не обязателен для

    работы через HTTP API, но пригождается для install()/диагностики)."""
    return shutil.which("ollama")


def status() -> dict[str, Any]:
    """Сводный статус для карточки в /setup и `cli.py ollama status`."""
    running = is_running()
    models = list_models() if running else []
    recommended_pulled = any(m.split(":")[0] == RECOMMENDED_MODEL.split(":")[0] for m in models)
    return {
        "binary_found": find_binary() is not None,
        "running": running,
        "models": models,
        "recommended_model": RECOMMENDED_MODEL,
        "recommended_pulled": recommended_pulled,
        "download_url": DOWNLOAD_URL,
    }


def install() -> tuple[bool, str]:
    """Best-effort автоустановка через системный пакетный менеджер.

    Не гарантирует успех (нужны права/сеть/наличие менеджера) - в любом
    случае возвращает понятное сообщение, что делать руками, если не вышло.
    Устанавливает сам рантайм Ollama, НЕ модель - за моделью отдельно
    pull_model().
    """
    system = platform.system()

    if system == "Windows":
        if shutil.which("winget") is None:
            return False, (
                f"winget не найден - скачай установщик вручную: {DOWNLOAD_URL} "
                "(обычный .exe, пара кликов)."
            )
        try:
            subprocess.run(
                ["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-package-agreements",
                 "--accept-source-agreements"],
                timeout=600, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"winget install не удался ({exc}) - скачай вручную: {DOWNLOAD_URL}"
        return (True, "Установка через winget запущена/завершена - проверь статус через минуту.") \
            if is_running() or find_binary() else \
            (False, f"winget отработал, но Ollama пока не отвечает - возможно, нужен перезапуск/PATH. "
                     f"Если не поможет - установщик вручную: {DOWNLOAD_URL}")

    if system == "Darwin":
        if shutil.which("brew") is None:
            return False, (
                f"Homebrew не найден - скачай .dmg вручную: {DOWNLOAD_URL} "
                "(или установи brew: https://brew.sh)."
            )
        try:
            subprocess.run(["brew", "install", "ollama"], timeout=600, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"brew install не удался ({exc}) - скачай вручную: {DOWNLOAD_URL}"
        return (True, "Установлено через Homebrew - запусти `ollama serve` или приложение Ollama.") \
            if find_binary() else (False, f"brew отработал, но бинарник не нашёлся - попробуй вручную: {DOWNLOAD_URL}")

    if system == "Linux":
        try:
            subprocess.run(
                ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                timeout=600, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return False, f"Автоустановка не удалась ({exc}) - команда вручную: curl -fsSL https://ollama.com/install.sh | sh"
        return (True, "Установлено официальным install.sh.") if find_binary() else \
            (False, "install.sh отработал, но бинарник не нашёлся - см. https://ollama.com/download")

    return False, f"Неизвестная платформа ({system}) - скачай вручную: {DOWNLOAD_URL}"


def pull_model(
    model: str = RECOMMENDED_MODEL,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    *,
    timeout: float = 3600.0,
) -> None:
    """Скачивает модель через потоковый Ollama HTTP API (/api/pull).

    on_progress получает каждую JSON-строку статуса как есть от Ollama, напр.
    {"status": "downloading digestname", "digest": "...", "total": N,
    "completed": M} - вызывающий код (CLI/веб-эндпоинт) сам решает, как это
    показать (текстом или процентом/прогресс-баром).

    Требует, чтобы сервис Ollama уже был запущен (см. is_running()) - если
    его вообще нет на машине, сначала install().
    """
    if not is_running(timeout=3.0):
        raise RuntimeError(
            "Ollama не отвечает на localhost:11434 - убедись, что она установлена и запущена "
            f"(см. ollama_setup.install() или {DOWNLOAD_URL})."
        )
    with httpx.Client(timeout=timeout) as http:
        with http.stream("POST", f"{OLLAMA_BASE_URL}/api/pull", json={"name": model, "stream": True}) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                import json as _json

                try:
                    payload = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                if payload.get("error"):
                    raise RuntimeError(f"Ollama вернула ошибку при скачивании {model!r}: {payload['error']}")
                if on_progress:
                    on_progress(payload)


def _cli_progress(payload: dict[str, Any]) -> None:
    status_text = payload.get("status", "")
    total = payload.get("total")
    completed = payload.get("completed")
    if total and completed is not None:
        pct = 100 * completed / total
        sys.stdout.write(f"\r{status_text}: {pct:5.1f}% ({completed / 1e9:.2f}/{total / 1e9:.2f} ГБ)")
        sys.stdout.flush()
    else:
        print(status_text)


def pull_model_cli(model: str = RECOMMENDED_MODEL) -> None:
    """Обёртка pull_model() с прогрессом, напечатанным в консоль (для CLI)."""
    print(f"Скачиваю модель {model} через Ollama...")
    pull_model(model, on_progress=_cli_progress)
    print(f"\nГотово: {model} скачана.")

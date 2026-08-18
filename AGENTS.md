# AGENTS.md — Garmin Health Pipeline

Local pipeline that pulls the user's Garmin Connect data (sleep, HRV, stress,
Body Battery, RHR, steps, workouts) into markdown/CSV files, plus an optional
agentic Telegram bot and MCP server on top. Python 3.13, uses
`cyberjunky/python-garminconnect`.

## Setup / running commands

Always use the project venv, from the repo root:

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli <command> [options]
```

Don't create a new venv or reinstall dependencies unless `.venv` is missing —
if it's missing, `pip install -r requirements.txt` into a fresh `.venv`.

Credentials/config live in `data/config.json` (created by the `/setup` web
form or written directly) or `.env` — **never** commit either file, print
their contents in full, or paste API keys/tokens into commit messages or PR
descriptions (`data/config.json`, `.env`, `data/tokens/`, `data/cache.sqlite3`
are all gitignored; keep it that way).

## Testing

There's no pytest config — run the smoke test directly after any change to
`garmin_pipeline/`:

```powershell
.venv\Scripts\python.exe tests\smoke_test.py
```

It exercises formatting, FIT parsing, workout building, the agentic
tool-calling loop, and cache/report logic against mock data (no real Garmin
API calls). It prints `ALL SMOKE TESTS PASSED` at the end on success and
raises `AssertionError`/prints a traceback on failure — treat any output
other than that final line as a failure to investigate, not just noise.

## CLI decision guide (same commands the Telegram bot/MCP server wrap)

| User asks for... | Run |
|---|---|
| "today's data" / "yesterday" / a specific date's health metrics | `daily --date YYYY-MM-DD` (or `--today`) |
| A specific workout ("yesterday's run", "that trail run last week") | `activity export` with filters (see below) |
| Just "what workouts did I do" without exporting | `activity search` with the same filters |
| Weekly summary / "how was my week" | `weekly` (optionally `--date` for a past week) |
| "overview of the last N days" / snapshot to paste into an LLM | `context --days N` (default 14) |
| A polished, shareable file/page for a date range (totals/averages, for publication) | `range --from YYYY-MM-DD --to YYYY-MM-DD` (also at `/range?from=...&to=...` via `cli web`) |
| Any other one-off question about a date range (a number, comparison, filter) | `export --from ... --to ...` + compute it yourself — see below |
| Old month cleanup | `rollup --month YYYY-MM` |
| Whether cached data has gaps for a date range | `cache coverage --days N` |
| Warm up the local cache without generating a report | `sync --days N` (default 3) |
| Creating/scheduling a structured workout in Garmin | `workout create` (see below) |

Every report command writes to `data/library/` and prints the file path(s) —
read that file back and summarize it in your response, don't just say "done".
If a workout request is ambiguous, run `activity search` first and ask the
user to confirm from the candidate list rather than guessing `--id`.

### Ad hoc analytical questions (no exact report matches)

For anything that doesn't cleanly match a fixed report format — "how many km
did I run in May", "compare average HR this week vs last week" — don't write
new Python. Instead:

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli export --from 2026-05-01 --to 2026-05-31
```

This prints raw JSON (`daily`: steps/distance_m/sleep_hours/hrv_ms/rhr/
stress_avg/body_battery_high|low/sleep_score per day; `activities`:
activity_type/distance_km/duration_s/avg_hr/avg_pace_s_per_km/
elevation_gain_m/calories per workout). It auto-syncs missing days from
Garmin first (slow only the first time over a new period, instant on
overlapping repeats). Compute the answer yourself from that JSON. Units:
`distance_m`/`distance_km` = meters/km, `duration_s` = seconds,
`avg_pace_s_per_km` = seconds/km (cycling: convert to km/h via
`3600 / avg_pace_s_per_km`). `null` means no data, not zero.

### Creating/scheduling a workout in Garmin

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli workout create --sport running --name "Easy run" `
    --steps-json '[{"kind":"warmup","duration_s":300},{"kind":"interval","duration_s":1200},{"kind":"cooldown","duration_s":300}]' `
    --date 2026-07-20
```

`--sport` is `running`/`cycling`/`strength_training`/`cardio_training`/`hiit`.
Add `"hr_zone": 1-5` to a warmup/interval/recovery/cooldown step for a
heart-rate-zone alert on the watch. For strength/cardio workouts use
`{"kind": "exercise", "category": ..., "exercise_name": ..., "reps": N}` (or
`duration_s` for a timed hold, optional `weight_kg`) and `{"kind": "rest",
"duration_s": N}` steps instead — `category`/`exercise_name` must come from
Garmin's built-in exercise catalog (see `_CATEGORY_MUSCLE_GROUPS` in
`garmin_pipeline/collectors/activity.py`). There's no in-place update —
delete the old workout and recreate it to change one. Full details and more
step examples: `.cursor/skills/garmin-health/SKILL.md` (same CLI, written for
a skill-matching agent, but the command reference is agent-agnostic).

## Architecture notes for code changes

- `garmin_pipeline/actions.py` is the single source of truth for read/write
  Garmin operations — both `mcp_server.py` (thin `@mcp.tool()` wrappers,
  read-only) and `agent_tools.py` (OpenAI tool schema for the Telegram bot,
  read + write) call into it. Add new capabilities there, not by duplicating
  logic in the wrappers.
- Write actions (`create_workout`, `delete_workout`, `upload_activity_file`)
  are intentionally **not** exposed via the MCP server — only via the
  Telegram bot, where `llm_client.run_agentic`/`resume_after_confirmation`
  enforce human-in-the-loop confirmation (inline Confirm/Cancel buttons)
  before they execute. Don't add write tools to `mcp_server.py`.
- `config.settings` is a frozen dataclass read from `data/config.json`
  (overlay) merged with `.env` (fallback) — read it via `config.settings.xxx`
  at call time, not `from garmin_pipeline.config import settings` at import
  time, so changes made through the web form take effect without a process
  restart (`config.save_config_json` calls `reload_settings()`).
- SQLite cache (`data/cache.sqlite3`) stores raw Garmin API payloads
  (`raw_payloads` table), not just derived fields — this lets new report
  fields be backfilled from cache without re-hitting the Garmin API. Prefer
  adding a new accessor over that raw data before adding a new network call.
- `build_range_report`/`export_raw_range` are incremental: they check the
  cache first and only fetch missing/stale days from Garmin. Keep new
  range-style aggregations incremental too — don't reintroduce a "refetch
  everything every time" pattern.

## GitHub releases

GitHub has no language toggle on the Releases page. Every release title and
body must be bilingual: Russian first (`## Что нового` / `### Обновление`),
then a `---` and English (`## What's new` / `### Upgrading`). Title pattern:
`vX.Y.Z — краткое по-русски / short English`.

---
name: garmin-health
description: >-
  Fetches and reports the user's Garmin Connect health and workout data
  (sleep, HRV, stress, Body Battery, resting HR, steps, calories, HR zones,
  per-km splits, strength-training exercise sets with reps/weight) via the
  local garmin_pipeline CLI, writing markdown/CSV
  files into data/library/. Use when the user asks to pull, export, show, or
  summarize their Garmin data, sleep, HRV, stress, steps, a specific workout
  or activity (by date, type, or description like "yesterday's run" or "that
  trail run last week"), a weekly/daily health report, or wants a
  multi-day context snapshot for LLM analysis.
---

# Garmin Health Pipeline

Wraps the `garmin_pipeline` CLI in this repo. Run all commands from the repo
root with the project venv:

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli <command> [options]
```

Every command writes to `data/library/` and prints the file path(s) it
wrote — after running a command, read that file back and summarize/show its
content to the user rather than just reporting "done".

## Decision guide

| User asks for... | Run |
|---|---|
| "today's data" / "yesterday" / a specific date's health metrics | `daily --date YYYY-MM-DD` (or `--today`) |
| A specific workout ("yesterday's run", "that trail run last week", "the 20k ride on Sunday") | `activity export` with filters (see below) |
| Just "what workouts did I do" without exporting | `activity search` with the same filters |
| Weekly summary / "how was my week" | `weekly` (optionally `--date` for a past week) |
| "give me an overview of the last N days" / preparing a broad snapshot to paste into an LLM | `context --days N` (default 14) |
| A polished, shareable file/page for a specific date range (steps + distance + per-activity-type totals/averages, explicitly for publication/sharing) | `range --from YYYY-MM-DD --to YYYY-MM-DD` (also viewable as a share-ready page at `/range?from=...&to=...` in the web dashboard - see `web` command) |
| Any other one-off question about a date range (a specific number, a comparison, a filter — not asking for a shareable file) | `export --from ... --to ...` + compute it yourself — see "Ad hoc analytical questions" below |
| Old month cleanup | `rollup --month YYYY-MM` |
| Whether cached data has gaps for a date range | `cache coverage --days N` |
| "warm up"/"sync" the local cache without generating a report | `sync --days N` (default 3; no files written, just fills SQLite) |
| Creating/scheduling a structured workout in Garmin | `workout create` (see below) |

If the user's request is ambiguous about which workout they mean, run
`activity search` first, show the short candidate list (date/type/distance/
name), and ask them to confirm — don't guess an `--id`.

## Ad hoc analytical questions (no exact report matches)

`daily`/`weekly`/`context`/`range` are fixed, pre-built formats. For anything
that doesn't cleanly match one of them — "how many km did I run in May",
"compare average HR this week vs last week", "how many strength sessions did
I do last month", any one-off aggregation/comparison/filter the user invents
on the spot — do **not** write new Python. Instead:

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli export --from 2026-05-01 --to 2026-05-31
```

This prints raw JSON: `daily` (one row per day — steps, distance_m, sleep_hours,
hrv_ms, rhr, stress_avg, body_battery_high/low, sleep_score) and `activities`
(one row per workout — activity_type, distance_km, duration_s, avg_hr,
avg_pace_s_per_km, elevation_gain_m, calories). It auto-syncs any missing days
from Garmin first, so it's slow only the first time over a brand-new period —
repeat/overlapping requests are instant (reads the local cache).

Read that JSON and compute whatever the user asked for yourself, in your
response — sums, averages, filtering by type, comparing two periods, etc.
Units: `distance_m`/`distance_km` = meters/km, `duration_s` = seconds,
`avg_pace_s_per_km` = seconds per km (for cycling, convert to km/h via
`3600 / avg_pace_s_per_km`), `sleep_hours` = hours, `hrv_ms` = milliseconds.
`null` means no data for that day/field, not zero.

Only reach for `range` (see below) when the user explicitly wants a
polished, shareable file/page — not for a quick numeric answer in chat.

## Daily report

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli daily --today
.venv\Scripts\python.exe -m garmin_pipeline.cli daily --date 2026-07-12
```

Writes `data/library/daily/YYYY-MM-DD.md`: sleep, HRV, stress, Body Battery,
resting HR, steps, calories, plus any activities that day with splits and HR
zones.

## Weekly report

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli weekly
.venv\Scripts\python.exe -m garmin_pipeline.cli weekly --date 2026-07-05
```

Writes `data/library/weekly/{ISO-week}.md`: per-day table (sleep/HRV/stress/
steps), averages, deltas vs. previous week, aggregated activity totals
(walking is excluded from aggregates by default as low-signal).

## Context snapshot (multi-day, for LLM analysis)

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli context --days 14
```

Writes `data/library/context/{date}.md`: aggregated daily metrics + recent
activities in one file. Use this instead of several `daily` calls when the
user wants a broad recent-history overview.

## Range report (custom period, for publication/sharing)

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli range --from 2026-07-18 --to 2026-07-31
```

Writes `data/library/range/{date_from}_{date_to}.md`: total + average daily
steps, total + average distance covered (from steps), and per-activity-type
aggregates (count, total/average distance, total/average duration, average
pace or speed, average HR) for every activity type recorded in that window.
Unlike `weekly`/`context`, this takes explicit `--from/--to` dates, not a
fixed week or "last N days". Past days already in the local cache are not
re-fetched from Garmin (only missing days + today are) — the first run over
a brand-new period can take a while, repeat runs over the same/overlapping
period are near-instant. The same data renders as a share-ready page (hero
stats + per-type cards, print/PDF-friendly) at `/range?from=...&to=...` once
the web server is running (`cli web`).

## Finding/exporting a specific activity

Common filters (combine as needed): `--date YYYY-MM-DD`, `--from/--to`,
`--type running|cycling|swimming|...`, `--name <substring>`, `--latest`,
`--id <activity_id>` (to disambiguate after a search).

```powershell
# List candidates only
.venv\Scripts\python.exe -m garmin_pipeline.cli activity search --latest
.venv\Scripts\python.exe -m garmin_pipeline.cli activity search --from 2026-07-05 --to 2026-07-11 --type running

# Export (markdown + CSV of track points, exact one match required)
.venv\Scripts\python.exe -m garmin_pipeline.cli activity export --latest
.venv\Scripts\python.exe -m garmin_pipeline.cli activity export --date 2026-07-05 --id 123456789
```

`export` exits with code `3` and prints a candidate list if more than one
activity matches — rerun with `--id` from that list. It writes
`data/library/activities/{stem}.md` (+ `.csv` with variable-interval track
points) with duration (`h:mm:ss`), distance, pace or speed (speed in km/h
for cycling, pace for running/other), calories, HR zone distribution, and
per-km splits (from the original FIT file when available, else computed
from time-series data). For strength/cardio-type activities
(`strength_training`, `hiit`, `cardio_training`, ...) it also includes an
exercise-sets breakdown when the device detected it: per-exercise set count,
total reps, max weight (kg), and a muscle-group summary (chest/back/biceps/
quads/etc., computed locally from Garmin's own exercise-category taxonomy —
Garmin's "muscle map" diagram is a client-side visual only, not an API field)
— this is also included automatically in `daily`/`context` output and
Telegram free-text answers for those activity types, so you don't need a
separate call for it.

## Creating/scheduling a workout in Garmin

```powershell
.venv\Scripts\python.exe -m garmin_pipeline.cli workout create --sport running --name "Easy run" `
    --steps-json '[{"kind":"warmup","duration_s":300},{"kind":"interval","duration_s":1200},{"kind":"cooldown","duration_s":300}]' `
    --date 2026-07-20
```

`--sport` is `running`, `cycling`, `strength_training`, `cardio_training`, or
`hiit`. Omit `--date` to create without scheduling. Use `--steps-file
path.json` instead of `--steps-json` for longer step lists.

Add `"hr_zone": 1-5` to any cardio step (warmup/interval/recovery/cooldown,
not `repeat`) to make the watch alert (vibrate/beep) when heart rate leaves
that zone during the step — useful for keeping warmup/cooldown in Z2, for
example. Garmin's zone boundaries (bpm) come from the user's own Garmin
Connect profile, not from this call. There is no way to update a workout in
place — recreating one means `client.delete_workout(old_id)` then re-running
`workout create`.

### Strength/core workouts (sets of reps or a timed hold, optional weight)

For `sport strength_training`/`cardio_training`/`hiit`, use `"kind":
"exercise"` steps instead of warmup/interval/cooldown:

```json
{"kind": "exercise", "category": "HIP_STABILITY", "exercise_name": "DEAD_BUG", "reps": 20}
{"kind": "exercise", "category": "PLANK", "exercise_name": "SIDE_PLANK", "duration_s": 20}
{"kind": "exercise", "category": "BANDED_EXERCISES", "exercise_name": "GLUTE_BRIDGE", "reps": 20, "weight_kg": 10}
{"kind": "rest", "duration_s": 30}
```

- Exactly one of `reps` (→ rep-counted set) or `duration_s` (→ timed hold, e.g.
  planks) is required per exercise step.
- `category`/`exercise_name` must come from Garmin's built-in exercise catalog
  (same FIT SDK `exercise_category` enum used to read back exercise sets/
  muscle groups — see `_CATEGORY_MUSCLE_GROUPS` in `activity.py`). If unsure
  of the exact name, web-search "Garmin exercise reference <movement>" or
  check the Terra Garmin exercise reference — an unmatched name just shows as
  a generic unnamed strength step on the watch (weight/reps still get logged).
- `weight_kg` is optional — omit it when the user wants the load to stay
  freely adjustable per session; the actual weight used still gets recorded on
  the completed activity and is readable later via `activity export`
  (exercise sets/muscle groups section).
- Wrap `[exercise, rest]` in `{"kind": "repeat", "iterations": N, "steps": [...]}`
  for N identical sets, or write them out explicitly if sets differ (e.g. no
  trailing rest after the very last set of the workout).

## Note: this is the same pipeline behind the Telegram bot

Everything above is also exposed to end users of the distributed app via an
agentic Telegram bot (`garmin_pipeline/bot.py`, tools defined in
`actions.py`/`agent_tools.py`) — free-text messages there go through a
tool-calling loop instead of a single command, and any data-changing action
(`workout create`/delete/uploading a file) requires the *user's* explicit
confirmation via inline buttons before it runs. In this chat, you already
have the user's confirmation implicitly (they're asking you directly), so
just run the CLI command — no extra confirmation step needed here.
`cli.py ollama status|install|pull` manages the optional local model (Ollama)
that powers that bot when no cloud API key is configured; unrelated to
running commands in this skill.

## After running any command

1. Read the file path printed by the CLI.
2. Summarize the relevant parts in the chat (don't just say "exported") —
   the user typically wants the numbers discussed, not just a file pointer.
3. Mention the file path so the user can drag it into a ChatGPT Project if
   they want deeper analysis there.

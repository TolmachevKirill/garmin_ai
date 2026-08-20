---
name: release-garmin-pipeline
description: >-
  Cut a new GitHub release of the Garmin Health Pipeline (Windows .exe +
  macOS .app via GitHub Actions), with bilingual RU/EN release notes. Use
  when the user asks to release, ship, publish a new version, or says
  "коммит, пуш, релиз" / "новый релиз" for this project.
---

# Releasing Garmin Health Pipeline

## Quick start

```
Task Progress:
- [ ] 1. Run smoke tests
- [ ] 2. Commit + push code changes (if not already pushed)
- [ ] 3. Pick next version number (semver)
- [ ] 4. Rebuild the Windows .exe and zip it
- [ ] 5. Write bilingual release notes (RU first, then EN)
- [ ] 6. Create the GitHub release with `gh release create` + the Windows zip
- [ ] 7. Confirm the macOS workflow auto-triggered and attached its zips
```

### 1. Smoke tests

```powershell
.venv\Scripts\python.exe tests\smoke_test.py
```

Must print `ALL SMOKE TESTS PASSED`. Fix any failure before releasing.

### 2. Commit + push

Standard git workflow (see repo-wide git rules) - stage only the relevant
files, write a commit message explaining *why*, push to `master`.

### 3. Version number

```powershell
gh release list --limit 5
```

Bump patch (`vX.Y.Z+1`) for fixes, minor (`vX.Y+1.0`) for new user-facing
features. This repo is at v1.0.x as of 2026-08.

### 4. Rebuild the Windows exe

Always use `scripts/build_exe.ps1`, not a bare `pyinstaller` call - it
preserves any local `dist/GarminHealthPipeline/data` across the rebuild
(PyInstaller's COLLECT step wipes that folder on every build).

```powershell
.\scripts\build_exe.ps1
Compress-Archive -Path "dist\GarminHealthPipeline\*" -DestinationPath "dist\GarminHealthPipeline-vX.Y.Z-windows.zip" -Force
```

macOS `.app` builds are **not** built locally (no Mac available) - see step 7.

### 5. Bilingual release notes

Per `AGENTS.md`: every release title and body must be bilingual, Russian
first, then a `---`, then English. Title pattern:
`vX.Y.Z — краткое по-русски / short English`.

Write notes to a temp file (PowerShell heredoc-via-`Set-Content` avoids quoting
issues) with this shape:

```markdown
## Что нового

<1-3 bullet points or short paragraphs, RU>

### Обновление

<upgrade instructions if relevant, e.g. "просто замени .exe в той же папке">

---

## What's new

<same content, EN>

### Upgrading

<same upgrade instructions, EN>
```

### 6. Create the release

```powershell
gh release create vX.Y.Z "dist\GarminHealthPipeline-vX.Y.Z-windows.zip" --title "vX.Y.Z — русское название / English name" --notes-file "_release_notes.md"
Remove-Item "_release_notes.md"
```

`gh release create` with a not-yet-existing tag creates and pushes the tag
too - this is what triggers step 7 automatically, no separate `git tag` push
needed.

### 7. Confirm the macOS build attached itself

Creating the `vX.Y.Z` tag fires `.github/workflows/build-macos.yml` (`on: push:
tags: v*`), which builds both `macos-arm64` and `macos-x64` zips and uploads
them to the same release via `gh release upload --clobber`. This takes a few
minutes - poll it and verify before telling the user the release is fully done:

```powershell
gh run list --workflow=build-macos.yml --limit 3
# wait for the run matching the new tag to show "completed  success"

gh release view vX.Y.Z --json assets --jq '.assets[] | {name, size}'
# expect 3 assets: -windows.zip, -macos-arm64.zip, -macos-x64.zip
```

If the macOS run fails or is stuck queued, check for GitHub Actions runner
deprecations first (this bit us once with `macos-13`, see git history) before
assuming it's a code problem.

## Cleanup

Remove any scratch files created for the release (`_release_notes.md`,
temp zips already uploaded) and any test config left in
`dist\GarminHealthPipeline\data` from local testing before/after the build.

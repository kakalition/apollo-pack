---
name: habit-tracker
description: Track flexible-cadence habits with daily check-ins, neutral skips, and streak and adherence reports.
version: 1.0.0
author: kakalition (GitHub)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Habits, Streaks, Tracking, Scheduling, Local-First]
    category: productivity
    related_skills: []
---

# Habit Tracker Skill

Track habits that do not fit a single daily checkbox. A habit is `daily`, a
`weekly` quota, or a fixed `interval` of days, and every day you log `done`,
`skip`, or `fail`. `skip` is neutral: it breaks neither a streak nor
adherence. The skill owns every streak, adherence, and due calculation in a
local SQLite file; the host agent only runs a script and renders the JSON it
returns.

## When to Use

- The user wants to start, track, or review a habit.
- The user asks for a streak, a completion rate, what is due today, or what
  they have been skipping.
- The user wants a neutral way to excuse a day ("I did not do it, but it does
  not count against me").
- The user wants a quiet daily reminder of what is due.

Skip it for one-off to-dos, for projects with subtasks, and for anything that
needs a shared server: this skill is a local single-user log.

## Prerequisites

- Python 3.9+. The scripts are standard library only; no network access.
- A writable location for the database (default
  `~/.local/share/habit-tracker/habits.db`).
- Optional: choose a timezone and week start once with `settings.py set`, so
  "today" and weekly grouping match the user's calendar.

## How to Run

Resolve the directory that contains this `SKILL.md`, then call a script
through `terminal`:

```
python3 <skill-dir>/scripts/<domain>.py <verb> [flags]
```

- `<domain>` is one of `init`, `settings`, `habits`, `checkins`, `reports`.
- Every script accepts `--db PATH`, `--format json|table`, `--tz ZONE`, and
  `--quiet`.
- Read the JSON envelope from the terminal result. If `ok` is false, read
  `error.message` and fix the call instead of guessing.
- Open `references/commands.md` with `read_file` for every flag.

First run:

```
python3 <skill-dir>/scripts/init.py init
python3 <skill-dir>/scripts/settings.py set --tz Asia/Jakarta --week-start mon
python3 <skill-dir>/scripts/settings.py show
```

## Quick Reference

| The user wants to... | Run |
|---|---|
| set up the database | `init.py init` |
| see or change timezone, week start, default view | `settings.py show\|get\|set` |
| add, list, show, edit, rename a habit | `habits.py add\|list\|show\|edit\|rename` |
| pause, resume, or archive a habit | `habits.py pause\|resume\|archive` |
| delete a habit and its check-ins | `habits.py delete NAME --yes` |
| log progress | `checkins.py done\|skip\|fail NAME [--date]` |
| fix a check-in | `checkins.py undo NAME [--date]` |
| see what is due now or soon | `reports.py today\|due` |
| see streaks and completion | `reports.py streaks\|adherence` |
| see history or totals | `reports.py history\|stats` |
| emit a scheduler artifact | `reports.py schedule-hint` |

Run `--help` on any domain for every flag, or read
`references/commands.md`.

## Procedure

① **Initialize once.** Run `init.py init`, then ask for the timezone and week
start and persist them with `settings.py set`. "Today" and weekly grouping
depend on both.

② **Add habits.** Use `habits.py add --name N --cadence daily|weekly|interval`.
For `weekly` pass `--count` as times per week; for `interval` pass `--count` as
days between occurrences. `--count` is rejected for `daily`. Start the habit
today or back-date it with `--start`.

③ **Log check-ins.** Use `checkins.py done NAME`, `skip NAME`, or `fail NAME`.
Use `skip` only for a day the user explicitly wants excused; it is neutral by
design. Each `(habit, date)` accepts one check-in; use `undo` to change it.

④ **Report.** Run `reports.py today` or `reports.py due` to see what is
outstanding, and `reports.py streaks` or `adherence` for progress. Read the
numbers from the JSON; never compute a streak or percentage yourself.

⑤ **Automate only when asked.** Run `reports.py schedule-hint --target ...`
and hand the emitted artifact to the host. The skill installs nothing and the
emitted command is read-only.

## Pitfalls

- **Never compute a streak or percentage.** `counts`, `adherence_pct`,
  `current_streak`, and `longest_streak` come from the scripts; reciting your
  own arithmetic will drift from the stored history.
- **`skip` is not `done`.** It neither increments nor breaks a streak. Do not
  treat a skipped day as success or as failure.
- **Do not double log.** A second check-in for the same date returns
  `conflict`; call `undo` first.
- **Deleting is destructive.** `habits.py delete` cascades to every check-in
  and requires `--yes`. Prefer `pause` or `archive`.
- **Paused hides, it does not erase.** A paused or archived habit disappears
  from `today` and `due` but keeps its history and shows zeroed streaks.
- **Respect the timezone.** Pass `--tz` or store it; otherwise the default is
  `UTC` and "today" may be wrong.

## Verification

```bash
python3 <skill-dir>/scripts/reports.py stats
python3 <skill-dir>/scripts/reports.py due
```

Green means the envelope has `ok: true` and `due` reports `read_only: true`
with a `habits` list. Run the emitted scheduling command twice and confirm the
second call changes nothing, because the report never writes.

# Command reference

Run every script as `python3 <skill-dir>/scripts/<domain>.py <verb> [flags]`.

Shared flags (accepted by all verbs):

- `--db PATH` — database file (default: `$HABIT_TRACKER_DB` or
  `~/.local/share/habit-tracker/habits.db`)
- `--format json|table` — output format (default `json`)
- `--tz ZONE` — override the timezone for this call
- `--quiet` — suppress success output; errors still print

Every script auto-creates the database, parent directories, and schema on
first use.

## init.py

| Verb | Flags |
|---|---|
| `init` | — |

Creates the database if needed. Idempotent. Returns `already_initialized`,
`schema_version`, `db`, the effective `settings`, and a `hint`.

## settings.py

| Verb | Flags |
|---|---|
| `show` | — |
| `get` | `--key NAME` (omit for the whole settings map) |
| `set` | `--tz ZONE` and/or `--week-start mon\|sun` and/or `--default-view today\|streaks` |

`show` returns `settings` (effective), `stored`, `env_overrides`, row `counts`,
and the database path. A set environment variable
(`HABIT_TRACKER_TZ`, `HABIT_TRACKER_WEEK_START`,
`HABIT_TRACKER_DEFAULT_VIEW`) wins over the stored value for that call.

## habits.py

| Verb | Flags |
|---|---|
| `add` | `--name N --cadence daily\|weekly\|interval [--count N] [--start DATE] [--end DATE] [--notes T]` |
| `list` | `[--include-inactive]` |
| `show` | `<habit>` |
| `edit` | `<habit> [--cadence K] [--count N] [--start DATE] [--end DATE] [--notes T]` |
| `rename` | `<habit> --name NAME` |
| `pause` | `<habit>` |
| `resume` | `<habit>` |
| `archive` | `<habit>` |
| `delete` | `<habit> --yes` |

`<habit>` accepts an id or a name. `--count` means times-per-week for `weekly`
and days-between for `interval`; it defaults to `1` and is rejected for
`daily` with `invalid_cadence`. `pause`, `resume`, and `archive` are
non-destructive: they flip `active` and keep every check-in. `delete` cascades
and therefore requires `--yes`.

## checkins.py

| Verb | Flags |
|---|---|
| `done` | `<habit> [--date DATE] [--note T]` |
| `skip` | `<habit> [--date DATE] [--note T]` |
| `fail` | `<habit> [--date DATE] [--note T]` |
| `undo` | `<habit> [--date DATE]` |
| `list` | `[--habit H] [--from DATE] [--to DATE] [--status done\|skip\|fail] [--limit N]` |

One check-in per `(habit, date)`. A second one returns `conflict`; use `undo`
first. `skip` is neutral and never breaks a streak or lowers adherence. `done`
and `fail` are stored unchanged; `undo` removes the row for that date.

## reports.py

| Verb | Flags |
|---|---|
| `today` | `[--as-of DATE]` |
| `due` | `[--as-of DATE] [--within N]` (read-only) |
| `streaks` | `[--habit H] [--as-of DATE]` |
| `adherence` | `--from DATE --to DATE [--habit H]` |
| `history` | `--habit H [--from DATE] [--to DATE] [--limit N]` |
| `stats` | — |
| `schedule-hint` | `--target TARGET [--action add\|enable\|disable\|remove\|list] [--job JOB] [--path-mode abs\|relative\|skill] [--at-time HH:MM] [--tz ZONE] [--name JOB]` (see `references/scheduling.md`) |

Every verb here is read-only. `today` and `due` return `read_only: true`.
`due` also lists interval habits whose next due date falls inside `--within`
days (default 7). `streaks` returns `counts`, `adherence_pct`,
`current_streak`, `longest_streak`, `last_done`, and `pending` for each habit.
`adherence` returns the same `counts` and `adherence_pct` for the requested
range. All of these numbers come from the scripts, never from prose.

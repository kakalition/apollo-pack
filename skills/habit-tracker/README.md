# habit-tracker

A portable [Agent Skill](https://skills.sh) for tracking flexible-cadence
habits in a local SQLite file. It works with any Agent Skills host (nanobot,
Claude Code, Codex, Kilo, OpenClaw, and others).

Source: <https://github.com/kakalition/apollo-pack/tree/main/skills/habit-tracker>

Everything executable lives in focused Python scripts under
`habit-tracker/scripts/`. The agent runs a script and reads its JSON output.
There is no server, no network access, and no third-party dependency: the
standard library only (Python 3.9+).

## What it does

- Habits with three cadences: `daily`, `weekly` quota, or a fixed `interval`
- One check-in per habit per day: `done`, `skip` (neutral), or `fail`
- Per-check-in notes
- Streaks (current and longest), adherence, due today, and history reports
- Non-destructive `pause` and `archive`; `delete` is confirmed and cascades
- All configuration read from the host environment (`HABIT_TRACKER_*`)

A `skip` breaks neither a streak nor adherence: it excuses the day. All
streak, adherence, and due arithmetic is computed by the scripts, never by the
model.

## Install

With the skills.sh CLI:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill habit-tracker --agent <your-agent> --copy --yes
```

For nanobot specifically, `--agent openclaw` is the marketplace agent id:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill habit-tracker --agent openclaw --copy --yes
```

Manual install: copy the `habit-tracker/` folder into your host's skills
directory so that `habit-tracker/SKILL.md` is discoverable. The folder name
must stay `habit-tracker`.

## Quick start

```bash
SKILL=./habit-tracker
python3 "$SKILL/scripts/init.py" init
python3 "$SKILL/scripts/settings.py" set --tz Asia/Jakarta --week-start mon
python3 "$SKILL/scripts/habits.py" add --name "Read" --cadence daily --start 2026-01-01
python3 "$SKILL/scripts/checkins.py" done Read --date 2026-01-01
python3 "$SKILL/scripts/reports.py" streaks --habit Read
```

A weekly habit takes a quota with `--count N`; an interval habit takes days
between occurrences:

```bash
python3 "$SKILL/scripts/habits.py" add --name "Gym" --cadence weekly --count 3
python3 "$SKILL/scripts/habits.py" add --name "Water" --cadence interval --count 2
```

Log a neutral day with `checkins.py skip NAME`; it does not break the streak.

## Requirements

- Python 3.9 or newer, standard library only
- A writable location for the database (default
  `~/.local/share/habit-tracker/habits.db`)

## Where the data lives

Resolved in order: `--db PATH`, `$HABIT_TRACKER_DB`, then
`~/.local/share/habit-tracker/habits.db`. Back up by copying that one file. No
personal data is stored in this repository.

## Cadences and streaks

| Cadence | `--count` means | Streak unit |
|---|---|---|
| `daily` | not allowed (always 1) | days |
| `weekly` | times per week | weeks satisfied |
| `interval` | days between occurrences | due instances |

`skip` is neutral everywhere. See `habit-tracker/references/schema.md` for the
exact rules, including weekly excused-versus-missed weeks.

## Automate a daily reminder

```bash
python3 "$SKILL/scripts/reports.py" due
python3 "$SKILL/scripts/reports.py" schedule-hint --target generic
```

`due` and `schedule-hint` are read-only. `schedule-hint` emits an artifact for
the target and installs nothing. See
`habit-tracker/references/scheduling.md`.

## Layout

```
skills/habit-tracker/
├── SKILL.md
├── README.md
├── LICENSE
├── .gitignore
├── tests/smoke.sh
├── scripts/       # _lib.py + one script per domain
└── references/    # commands.md, schema.md, scheduling.md
```

## Test

```bash
bash tests/smoke.sh
```

The harness runs the scripts end to end against a throwaway database and
checks hand-computed streaks and adherence, weekly quota edges under Monday
and Sunday week starts, interval due dates, scheduling artifacts, and error
handling.

## License

MIT. See `LICENSE`.

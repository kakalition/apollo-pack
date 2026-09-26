# Schema and conventions

## Storage

A single SQLite database (WAL mode, foreign keys on, `busy_timeout=5000`).
Path precedence: `--db PATH`, `$HABIT_TRACKER_DB`, then
`~/.local/share/habit-tracker/habits.db`. The database is created on first run.
Back up by copying the file. `PRAGMA user_version` is `1`.

## Tables

```
meta(key PK, value)

habits(
  id PK,
  name TEXT NOT NULL UNIQUE,
  cadence_kind TEXT NOT NULL CHECK (cadence_kind IN ('daily','weekly','interval')),
  cadence_count INTEGER NOT NULL DEFAULT 1
    CHECK (cadence_count >= 1),
  start_date TEXT NOT NULL,
  end_date TEXT NULL,
  notes TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')))

checkins(
  id PK,
  habit_id INTEGER NOT NULL REFERENCES habits(id) ON DELETE CASCADE,
  date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('done','skip','fail')),
  note TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (habit_id, date))
  -- indexes: checkins(habit_id), checkins(date)
```

All dates are `YYYY-MM-DD`. `cadence_count` means: `1` for `daily`, times per
week for `weekly`, and days between occurrences for `interval`.

## Cadence and streak rules

These rules are the definition of record; the scripts implement them and the
prose never recomputes a number.

- **daily:** expected every active day. Day outcomes: `done` increments the
  streak; `skip` is neutral (excused — it does not break and does not
  increment); `fail` or no check-in breaks the run. The current streak is the
  count of consecutive satisfying days ending at the most recent expected day;
  "today with no check-in" is pending, not a break.
- **weekly:** quota of `cadence_count` `done` per week (week start per the
  `week_start` setting, default Monday). A week is satisfied when its
  done-count is at least the quota. A week with a `skip` and done below quota
  is *excused* (neutral). A week with neither is a miss. The streak counts
  consecutive satisfied weeks.
- **interval:** due every `cadence_count` days after the later of `start_date`
  or the last `done`. An on-time `done` extends the streak; `skip` excuses
  that due date (neutral); a due date passed with no `done` and no `skip` is a
  miss.
- Expectations are bounded by `start_date` and `end_date`. A habit with
  `active = 0` (paused or archived) is excluded from `today` and `due` and
  reports zeroed streaks.
- Ratios: `adherence_pct = done / (done + fail + miss) * 100`; skips are
  excluded from the denominator. Reports return both the raw `counts` and the
  rounded percentage.

## Streaks, units, and last done

`counts` are measured in the natural unit of the cadence: days for `daily`,
weeks for `weekly`, and due instances for `interval`. For `weekly` only whole
weeks are grouped, so `fail` counts are always `0` at the week level (a week
with fails but below quota is a miss). `pending` is true when the most recent
expected unit has not been completed and has not failed — the current day or
week. `last_done` is the most recent `done` date for the habit.

## Destructive operations

`habits.py delete` removes the habit and, by the `ON DELETE CASCADE` foreign
key, every one of its check-ins. It requires `--yes`. Prefer `pause` or
`archive`, which keep history.

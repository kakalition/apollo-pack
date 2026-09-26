# Command reference

Run every script as `python3 <skill-dir>/scripts/<domain>.py <verb> [flags]`.

Shared flags (accepted by all verbs):

- `--db PATH` — database file (default: `$JOURNAL_DB` or
  `~/.local/share/journal/journal.db`)
- `--format json|table` — output format (default `json`)
- `--tz ZONE` — override the timezone for this call
- `--quiet` — suppress success output; errors still print

Every script auto-creates the database, parent directories, and schema on
first use.

## init.py

| Verb | Flags |
|---|---|
| `init` | `[--no-fts]` |

Creates the schema and the full-text index when the SQLite build supports
FTS5. `--no-fts` forces the plain search fallback and drops any existing
index. Idempotent. Returns `already_initialized`, `fts_enabled`,
`schema_version`, and `db`.

## settings.py

| Verb | Flags |
|---|---|
| `show` | — |
| `get` | `--key NAME` (omit for the whole settings map) |
| `set` | `--tz ZONE` and/or `--week-start mon\|sun` and/or `--default-limit N` and/or `--review-prompt TEXT` |

`show` returns `settings` (effective), `stored`, `env_overrides`,
`fts_enabled`, and row `counts`. A set environment variable (`JOURNAL_TZ`,
`JOURNAL_WEEK_START`, `JOURNAL_DEFAULT_LIMIT`, `JOURNAL_REVIEW_PROMPT`) wins
over the stored value for that call.

## entries.py

| Verb | Flags |
|---|---|
| `add` | `[--body T \| --file PATH \| piped stdin] [--title T] [--date DATE] [--source S]` |
| `list` | `[--from DATE] [--to DATE] [--limit N] [--order asc\|desc]` |
| `show` | `<entry_id>` |
| `edit` | `<entry_id> [--body T] [--title T] [--date DATE]` |
| `delete` | `<entry_id>` |
| `search` | `QUERY [--from DATE] [--to DATE] [--limit N]` |

Many entries per day are allowed. The body comes from `--body`, `--file`, or
piped stdin, in that order. `word_count` is computed by the script. `edit`
sets `updated_at` and reindexes the full-text index. `search` uses FTS5 when
`fts_enabled` is true and a `LIKE` scan otherwise; the response carries an
`fts` boolean so the caller knows which path ran.

## reports.py

| Verb | Flags |
|---|---|
| `week` | `[--week YYYY-Www \| --from DATE --to DATE]` |
| `stats` | `[--week YYYY-Www \| --from DATE --to DATE]` |
| `schedule-hint` | `--target TARGET [--action add\|enable\|disable\|remove\|list] [--job JOB] [--path-mode abs\|relative\|skill] [--at-time HH:MM] [--tz ZONE] [--name JOB]` (see `references/scheduling.md`) |

Both report verbs are read-only and return `read_only: true`. `week` returns
the review brief (`range`, `entry_count`, `days_with_entries`, `days_missing`,
`total_words`, `by_day`, `notable_lines`, `top_terms`, `prompt`) for the host
model to compose from. With no range flags it uses the current week per the
`week_start` setting. `stats` returns totals plus the `current_run` and
`longest_run` of consecutive days with at least one entry. All counts come
from the scripts, never from prose.

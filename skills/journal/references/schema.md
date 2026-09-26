# Schema and conventions

## Storage

A single SQLite database (WAL mode, foreign keys on, `busy_timeout=5000`).
Path precedence: `--db PATH`, `$JOURNAL_DB`, then
`~/.local/share/journal/journal.db`. The database is created on first run.
Back up by copying the file. `PRAGMA user_version` is `1`.

## Tables

```
meta(key PK, value)

entries(
  id PK,
  entry_date TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT,
  title TEXT,
  body TEXT NOT NULL,
  word_count INTEGER NOT NULL DEFAULT 0,
  source TEXT)
  -- index: entries(entry_date)

entries_fts USING fts5(body, title, content='entries', content_rowid='id',
                       tokenize='unicode61')
  -- external-content FTS5, kept in sync by AFTER INSERT/UPDATE/DELETE triggers
```

Many entries per day are allowed; there is no uniqueness constraint, so the
skill has no `conflict` error code. All dates are `YYYY-MM-DD`.

## Full-text search and fallback

`init` attempts to create the external-content FTS5 table and its three sync
triggers. If the SQLite build has no FTS5 module, it catches the error, sets
`meta.fts_enabled=0`, and `entries.py search` falls back to
`body LIKE ? OR title LIKE ?`. `init --no-fts` forces the fallback on purpose,
and a later plain `init` re-enables FTS5 when it is available. `settings.py
show` and `init` both report `fts_enabled`, and every `search` response carries
an `fts` boolean. With FTS5, the query is tokenized and each term is quoted and
implicitly ANDed; the fallback matches the raw query as a substring.

## Word counts and brief analysis

- `word_count` is `len(body.split())` and is stored on every add or body edit.
  The scripts own it; prose must not recompute it.
- `notable_lines` is up to five of the longest non-empty sentences in the
  range, split on `.`, `!`, and `?` followed by whitespace, newest ties broken
  by date then text.
- `top_terms` counts tokens after lowercasing, dropping stopwords and tokens
  shorter than two characters or without a letter, then sorts by descending
  count and ascending term (top ten).
- `stats` computes `current_run` (consecutive days with at least one entry
  ending on the range end) and `longest_run` (the longest such run) from the
  distinct `entry_date` values.

## Weekly review brief

`reports.py week` is read-only and never calls a model. It returns a brief the
host model turns into prose:

- `range` — `{week, from, to}`; `--week YYYY-Www` uses the ISO week.
- `entry_count`, `days_with_entries`, `days_missing`, `total_words`.
- `by_day` — `{date, entries, words}` per day that has entries.
- `notable_lines` — `{date, text}`.
- `top_terms` — `{term, count}`.
- `prompt` — the stored `review_prompt`, telling the model to name nothing that
  is not in the entries.

`days_missing` only covers days up to today, so a current week does not list
its future days as missing.

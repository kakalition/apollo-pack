# Command reference

Run every script as `python3 <skill-dir>/scripts/<domain>.py <verb> [flags]`.

Shared flags (accepted by all verbs):

- `--home DIR` — data root (default `$DAILY_INSIGHT_HOME` or
  `~/.local/share/daily-insight`)
- `--format json|table` — output format (default `json`)
- `--tz ZONE` — override the timezone for this call
- `--quiet` — suppress success output; errors still print

Every script prints exactly one JSON envelope. Success is
`{"ok": true, "command": "<domain>.<verb>", "data": ...}` with exit 0; failure
is `{"ok": false, "error": {"code": ..., "message": ...}}` with exit 1; bad
flags are an argparse usage error with exit 2. The data root contains
`daily-insight.db` (SQLite), `chroma/` (the vector store), and `outbox/`.

## init.py

| Verb | Flags |
|---|---|
| `init` | — |

Creates the data root, schema, and vector collection, and reports which
optional dependencies are present. Idempotent.

## settings.py

| Verb | Flags |
|---|---|
| `show` | — |
| `get` | `--key NAME` (omit for the whole snapshot) |
| `set` | `--budget N`, `--wake HH:MM-HH:MM`, `--strategy coverage\|similarity\|random`, `--tz ZONE`, `--embed-mode hash\|remote`, `--embed-provider openai`, `--embed-base-url URL`, `--embed-model NAME`, `--embed-api-key-env VAR`, `--embed-dim N`, `--chat-provider openai\|anthropic`, `--chat-base-url URL`, `--chat-model NAME`, `--chat-api-key-env VAR`, `--cooldown-days N`, `--chunk-size N`, `--chunk-overlap N`, `--dedup-threshold F` |

`embed_provider` is OpenAI-compatible only (OpenAI, OpenRouter, vLLM, ...):
Anthropic has no embeddings endpoint. `chat_provider` accepts `openai`
(chat/completions) or `anthropic` (the Messages API). When a base URL is empty
the provider's default is used (`https://api.openai.com/v1` or
`https://api.anthropic.com/v1`).

API-key settings store the *name of an environment variable*, never the key.
Key material is read from the host environment at call time.

### Host environment overrides

Every setting can be supplied by the process environment, namespaced with the
skill name. A set variable wins over the stored value for that call; `show`
reports the active overrides as `env_overrides`. No `.env` file is read and no
other application's config is consulted.

| Setting | Environment variable |
|---|---|
| budget | `DAILY_INSIGHT_BUDGET` |
| wake | `DAILY_INSIGHT_WAKE` |
| tz | `DAILY_INSIGHT_TZ` |
| strategy | `DAILY_INSIGHT_STRATEGY` |
| cooldown_days | `DAILY_INSIGHT_COOLDOWN_DAYS` |
| chunk_size / chunk_overlap | `DAILY_INSIGHT_CHUNK_SIZE` / `DAILY_INSIGHT_CHUNK_OVERLAP` |
| dedup_threshold | `DAILY_INSIGHT_DEDUP_THRESHOLD` |
| embed_mode | `DAILY_INSIGHT_EMBED_MODE` |
| embed_provider | `DAILY_INSIGHT_EMBED_PROVIDER` |
| embed_base_url / embed_model | `DAILY_INSIGHT_EMBED_BASE_URL` / `DAILY_INSIGHT_EMBED_MODEL` |
| embed_api_key_env | `DAILY_INSIGHT_EMBED_API_KEY_ENV` |
| embed_dim | `DAILY_INSIGHT_EMBED_DIM` |
| chat_provider | `DAILY_INSIGHT_CHAT_PROVIDER` |
| chat_base_url / chat_model | `DAILY_INSIGHT_CHAT_BASE_URL` / `DAILY_INSIGHT_CHAT_MODEL` |
| chat_api_key_env | `DAILY_INSIGHT_CHAT_API_KEY_ENV` |
| data root | `DAILY_INSIGHT_HOME` |

The embedding key is read from the variable named by `embed_api_key_env`
(default `DAILY_INSIGHT_EMBED_API_KEY`); the chat key from `chat_api_key_env`
(default `DAILY_INSIGHT_CHAT_API_KEY`).

## materials.py

| Verb | Flags |
|---|---|
| `add` | `--name NAME [--cadence-count N] [--cadence-period day\|week] [--priority N] [--source PATH]` |
| `list` | `[--include-archived]` |
| `show` | `<material>` |
| `cadence` | `<material> [--count N] [--period day\|week]` |
| `priority` | `<material> --value N` |
| `rename` | `<material> --name NAME` |
| `archive` | `<material> [--unarchive]` |
| `delete` | `<material> [--dry-run]` |

`<material>` accepts an id or a name. Lower `priority` is served first when the
day is over budget. `delete` removes the material's chunks from both SQLite and
the vector store.

## ingest.py

| Verb | Flags |
|---|---|
| `ingest` | `[FILE ...] [--text TEXT] --material NAME \| --title NAME [--chunk-size N] [--chunk-overlap N] [--replace] [--dry-run]` |

Accepts `.txt`, `.md`, `.rst`, `.csv`, `.json`, `.html`, `.docx`, `.pdf`, raw
`--text`, or piped stdin. Chunks are embedded and written to SQLite and the
vector store together. Chunks whose text hash already exists in the material
are skipped; `--replace` clears the material's chunks first. `--dry-run`
computes everything and writes nothing.

## insights.py

| Verb | Flags |
|---|---|
| `due` | `[--date DATE] [--days N]` |
| `next` | `[--date DATE] [--strategy S] [--query TOPIC] [--cooldown-days N] [--dedup-threshold F] [--generate] [--outbox]` |
| `run` | same as `next` plus `[--until HH:MM\|DATE\|ISO]` |
| `schedule-hint` | `--target TARGET [--action add\|enable\|disable\|remove\|list] [--job JOB] [--path-mode abs\|relative\|skill] [--at-time HH:MM] [--budget N] [--wake HH:MM-HH:MM] [--name JOB] [--generate] [--outbox]` |

- `due` persists and previews the deterministic day plan (slots, drops,
  remaining, upcoming) and delivers nothing.
- `next` delivers exactly one planned slot and returns the brief. Once the day's
  budget is delivered it returns `{"status": "nothing_due"}`. It is idempotent
  per `(date, slot_index)`.
- `run` delivers every planned slot due by `--until` (default now) and is safe
  to trigger repeatedly; reruns deliver nothing.
- `schedule-hint` emits an installable artifact for the chosen target and
  installs nothing. See `references/scheduling.md` for the target matrix.

The brief is meant to be written up by the host agent, which already has a
model, so no chat endpoint is required. `--generate` is optional and only for
headless targets that cannot show chat; it calls the configured chat endpoint
and stores the resulting prose.

A deliverable brief has this shape:

```json
{
  "status": "delivered",
  "slot": {"date": "2026-09-28", "index": 0, "due_at": "08:00"},
  "material": {"id": 1, "name": "Book A", "cadence": "2/day"},
  "chunk": {"ordinal": 0, "text": "...", "token_est": 120},
  "related": [{"ordinal": 1, "text": "...", "score": 0.83}],
  "novelty": {"material_delivered": 0, "material_total": 9, "coverage_pct": 0.0},
  "prompt": "Compose a short, skimmable insight ..."
}
```

## reports.py

| Verb | Flags |
|---|---|
| `coverage` | `[--include-archived]` |
| `history` | `[--limit N] [--material M] [--date DATE]` |
| `stats` | — |

`coverage` reports per-material and overall delivered-versus-total percentages
and lists materials never touched. `history` lists recent deliveries with a
short preview of any generated prose. `stats` reports totals and today's
progress.

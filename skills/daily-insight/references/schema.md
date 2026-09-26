# Data model

One data root per user. Resolved in order: `--home DIR`, then
`$DAILY_INSIGHT_HOME`, then `~/.local/share/daily-insight`. Inside it:

- `daily-insight.db` — SQLite sidecar, the source of truth for configuration,
  ordering, and delivery state. WAL mode, foreign keys on, `user_version = 1`.
- `chroma/` — the persistent vector store, collection `chunks`.
- `outbox/` — optional generated prose, one `<date>.md` file per day.

Back up by copying the whole data root. The repository ships no data.

## Vector identity

Every chunk is written to SQLite and the vector store under the deterministic
id `"<material_id>:<ordinal>"`. That single rule lets the relational store and
the vector store be reconciled or rebuilt from each other. Embeddings are
produced by the configured backend (`hash` offline, or an OpenAI-compatible
embeddings endpoint). The vector collection uses cosine distance.

## Tables

```sql
meta(key PK, value)                 -- every setting as text:
                                    -- budget, wake, tz, strategy,
                                    -- embed.mode/provider/base_url/model/api_key_env/dim,
                                    -- chat.provider/base_url/model/api_key_env,
                                    -- cooldown_days, chunk_size, chunk_overlap,
                                    -- dedup_threshold, initialized

materials(
  id PK, name UNIQUE, source_path, source_hash,
  cadence_count INTEGER DEFAULT 1,
  cadence_period TEXT CHECK IN ('day','week') DEFAULT 'day',
  priority INTEGER DEFAULT 100,            -- lower = served first when trimming
  active INTEGER DEFAULT 1, created_at,
  chunk_count INTEGER DEFAULT 0)

chunks(
  id PK, material_id FK, ordinal INTEGER, text TEXT, token_est INTEGER,
  text_hash TEXT, delivered_count INTEGER DEFAULT 0,
  last_delivered_at TEXT NULL,
  UNIQUE(material_id, ordinal))

day_slots(
  date TEXT, slot_index INTEGER, material_id FK, due_at TEXT,
  status TEXT CHECK IN ('planned','delivered','skipped') DEFAULT 'planned',
  chunk_id FK NULL, delivered_at TEXT NULL, generated INTEGER DEFAULT 0,
  PRIMARY KEY(date, slot_index))

deliveries(                           -- append-only history
  id PK, date, slot_index, material_id FK, chunk_id FK,
  delivered_at, generated INTEGER DEFAULT 0, insight_text TEXT NULL,
  UNIQUE(date, slot_index))
```

Indexes cover `chunks(material_id)`, `chunks(last_delivered_at)`,
`chunks(text_hash)`, `deliveries(date)`, and `deliveries(material_id)`.

## Settings and secrets

Settings live in `meta` and are stored as text so the schema does not churn.
Every setting can be overridden for a single call by a namespaced host
environment variable (`DAILY_INSIGHT_*`); env wins over the stored value. Secret
material is never stored: `embed_api_key_env` and `chat_api_key_env` hold the
*name* of an environment variable, and the endpoint client reads that variable
at call time. `settings.py show`/`get` never return key values.

Endpoints are selected by provider. `embed_provider` is OpenAI-compatible only
(Anthropic has no embeddings endpoint). `chat_provider` is `openai`
(chat/completions, bearer auth) or `anthropic` (Messages API, `x-api-key` and
`anthropic-version` headers). An empty base URL falls back to the provider
default.

## Day planning

The plan for a date is deterministic from settings and materials:

1. Each active material contributes `cadence_count` slots on a `day` cadence, or
   one slot on its chosen weekdays for a `week` cadence. Weekly weekdays are
   spread deterministically and uniquely across the week with a per-material
   offset.
2. Slots are interleaved round-robin across materials ordered by
   `(priority, id)` so no material clusters.
3. The first `budget` interleaved slots are kept; the rest are reported as
   `dropped`.
4. Slot times are spread evenly across the wake window; a single slot uses the
   window start.

The plan is persisted in `day_slots` on first contact for that date and is
otherwise immutable. Changing settings mid-day takes effect the next day.

## Selection

Candidates are the chunks not delivered inside the cooldown window, ordered
never-delivered first, then oldest, then by ordinal. With the `coverage`
strategy the first candidate wins after semantic dedup: a candidate is dropped
when its cosine similarity to any of the last ten delivered chunks exceeds
`dedup_threshold`; if dedup would drop everything, it is ignored. The
`similarity` strategy ranks candidates against a query or the material name; the
`random` strategy picks uniformly. When every chunk has been delivered inside
the window, the oldest chunk is reused rather than stopping.

## Idempotency

`deliveries` is unique on `(date, slot_index)` and a slot is claimed with a
conditional `UPDATE ... WHERE status = 'planned'`. Two triggers firing at once
therefore deliver one insight between them; the loser sees `nothing_due`.
`run` after `next` posts nothing, and a repeated `run` posts nothing.

# daily-insight

A portable [Agent Skill](https://skills.sh) that turns a pile of source material
into a quiet stream of short, faithful insights. It chunks and embeds what you
give it into a local vector store, keeps a per-source cadence under a global
daily budget, and hands back one fresh excerpt at a time so the same passage is
not repeated before the rest has been seen. It works with any Agent Skills host
(Claude Code, Hermes, Codex, Kilo, nanobot/OpenClaw, and others).

Source: <https://github.com/kakalition/apollo-pack/tree/main/skills/daily-insight>

Everything executable lives in focused Python scripts under
`daily-insight/scripts/`. The host agent runs a script and reads its JSON
output. There is no server: state lives in a local SQLite database plus a local
Chroma store, and the only network calls are the embedding and chat endpoints
you configure.

## What it does

- Ingests pasted text and `.txt`, `.md`, `.rst`, `.csv`, `.json`, `.html`,
  `.docx`, and `.pdf` files, chunked and embedded.
- Gives each source a cadence (`2/day`, `1/day`, `3/week`) under a global daily
  budget, spread across your wake window and trimmed round-robin by priority
  when over budget.
- Selects the next un-delivered chunk with a coverage-first policy and semantic
  dedup, returning a structured **insight brief** (excerpt, related passages,
  novelty, prompt) that the host renders in chat.
- Optionally writes finished prose itself (`--generate`) to a local outbox for
  headless schedulers.
- Reports coverage, history, and totals.
- Emits host-agnostic scheduling artifacts and installs nothing.

## Install

With the skills.sh CLI:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill daily-insight --agent <your-agent> --copy --yes
```

For nanobot specifically, `--agent openclaw` is the marketplace agent id, and
it copies into `<workspace>/skills`:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill daily-insight --agent openclaw --copy --yes
```

Manual install: copy the `daily-insight/` folder into your host's skills
directory so that `daily-insight/SKILL.md` is discoverable. The folder name must
stay `daily-insight`. See `daily-insight/references/hosts.md` for the per-host
discovery paths.

## Quick start

```bash
SKILL=./daily-insight
pip install -r requirements.txt

python3 "$SKILL/scripts/init.py" init
python3 "$SKILL/scripts/settings.py" set --budget 5 --wake 08:00-22:00

python3 "$SKILL/scripts/materials.py" add --name "Deep Work" --cadence-count 2 --cadence-period day
python3 "$SKILL/scripts/ingest.py" ingest deep-work.md --material "Deep Work"

python3 "$SKILL/scripts/insights.py" due
python3 "$SKILL/scripts/insights.py" next
```

`next` returns a brief; the host composes 3-6 sentences from the excerpt and
related passages only. Embeddings default to a deterministic offline `hash`
mode. For real semantic search, point at an OpenAI-compatible endpoint:

```bash
export DAILY_INSIGHT_EMBED_API_KEY=...
python3 "$SKILL/scripts/settings.py" set \
  --embed-mode remote --embed-provider openai \
  --embed-base-url https://api.openai.com/v1 \
  --embed-model text-embedding-3-small
```

You do **not** need a chat model for normal use: the host agent is the language
model and composes the insight from the returned brief. Only the optional
`--generate` path (for headless schedulers that cannot show chat) calls a chat
endpoint, supporting either an OpenAI-compatible chat API or the Anthropic
Messages API:

```bash
export DAILY_INSIGHT_CHAT_API_KEY=...
python3 "$SKILL/scripts/settings.py" set \
  --chat-provider anthropic --chat-model claude-3-5-sonnet-latest
```

Every setting can also come from the host environment, namespaced with the
skill: `DAILY_INSIGHT_BUDGET`, `DAILY_INSIGHT_WAKE`, `DAILY_INSIGHT_EMBED_MODEL`,
`DAILY_INSIGHT_CHAT_PROVIDER`, and so on. A set variable overrides the stored
value for that call. Keys are read only from the environment and are never
stored or echoed; no `.env` file and no other application's config is read.

## Requirements

- Python 3.9 or newer (the scripts are standard library only).
- `chromadb`, `pypdf`, and `python-docx` for the vector store and rich file
  readers: `pip install -r requirements.txt`. Without them, `init` and `ingest`
  fail fast with a `dependency_missing` error and the read-only reports still
  work.

## Where the data lives

Resolved in order: `--home DIR`, `$DAILY_INSIGHT_HOME`, then
`~/.local/share/daily-insight/`. Inside it:

- `daily-insight.db` — SQLite: settings, materials, chunks, the day plan, and
  delivery history (WAL mode).
- `chroma/` — the local vector store.
- `outbox/` — optional generated prose, one `<date>.md` file per day.

Back up by copying the whole data root. No personal data is stored in this
repository.

## Scheduling

Scheduling is opt-in and one-directional: `insights.py schedule-hint` emits an
artifact for a chosen target and installs nothing. The host or user registers
it. `next` is idempotent per `(date, slot_index)`, so over-firing, retries, and
catch-up triggers are safe.

```bash
python3 "$SKILL/scripts/insights.py" schedule-hint --target generic
python3 "$SKILL/scripts/insights.py" schedule-hint --target crontab --generate
```

See `daily-insight/references/scheduling.md` for the target matrix and install
and cancel steps.

## Layout

```
skills/daily-insight/
├── SKILL.md
├── README.md
├── LICENSE
├── requirements.txt
├── .gitignore
├── tests/
│   ├── smoke.sh            # hermetic script E2E
│   ├── e2e_hosts.sh        # hermetic host-compatibility E2E
│   ├── e2e_live.sh         # opt-in network E2E
│   └── fixtures/           # sample .md, .txt, .docx, .pdf
├── scripts/                # _lib.py + one script per domain
└── references/             # commands.md, schema.md, scheduling.md, hosts.md
```

## Test

The suite has three tiers. Tiers 1 and 2 are hermetic (no network) and use the
offline `hash` embedder; tier 3 is the opt-in live proof. Both hermetic tiers
need the optional dependencies installed.

```bash
pip install -r requirements.txt
bash tests/smoke.sh        # tier 1: scripts end to end
bash tests/e2e_hosts.sh    # tier 2: per-host discovery, invocation, scheduling
# tier 3 (requires an embedding key; also chats if a chat key is set)
DAILY_INSIGHT_EMBED_API_KEY=... bash tests/e2e_live.sh
```

Tier 1 checks settings round-trips, chunking and dedup across all input types,
the interleaved day plan, budget trimming, idempotent delivery, coverage and
cycling, error codes, every scheduling artifact, and portability. Tier 2 checks
the frontmatter and authoring standards, simulates each host's skills directory,
runs the scripts by absolute and skill-relative path, and validates the emitted
artifacts. Tier 3 exercises real embeddings, semantic retrieval, generation, and
concurrent triggers.

## License

MIT. See `LICENSE`.

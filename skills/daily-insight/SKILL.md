---
name: daily-insight
description: Deliver spaced, deduplicated insights from local sources.
version: 1.0.0
author: kakalition (GitHub)
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Insights, Learning, Spaced-Repetition, Vector-Search, Scheduling]
    category: productivity
    related_skills: []
---

# Daily Insight Skill

Turn a pile of source material into a quiet stream of short, faithful insights.
The skill chunks and embeds what you give it, keeps a per-source cadence under a
global daily budget, and hands back one fresh excerpt at a time so the same
passage is not repeated before the rest has been seen. It does not fetch, invent,
or publish anything: selection and delivery state live in a local data root, and
the host agent only triggers a script and renders the JSON it returns.

## When to Use

- The user wants to work through a long source (book, paper, docs, feed) over
  days without re-reading the same passage.
- The user asks for a spaced-review or reading queue, a daily insight, or a
  digest drawn from material they supplied.
- The user wants that stream to arrive on a schedule through a host chat tool or
  an OS scheduler.
- The user asks what has been covered, what is left, or what was delivered.

Skip it for one-off summaries of a single page, for real-time web search, and
for anything needing facts that are not in the ingested sources.

## Prerequisites

- Python 3.9+. The scripts are standard library only.
- Optional heavy dependencies for the vector store and rich file readers:
  `chromadb`, `pypdf`, `python-docx`. Install with
  `pip install -r requirements.txt`. Without them, `init` and `ingest` fail
  fast with a `dependency_missing` error and the read-only reports still work.
- Embeddings default to the built-in offline `hash` mode. For real semantic
  search, point at an OpenAI-compatible embeddings endpoint (OpenAI, OpenRouter,
  vLLM, ...). That is the only endpoint ordinary use needs: **you** are the
  language model, so the host platform's own model composes the insight from the
  returned brief. Anthropic has no embeddings endpoint, so `embed_provider` is
  OpenAI-compatible only.
- A chat endpoint is optional and only for headless automation (`--generate`):
  it supports either an OpenAI-compatible API or the Anthropic Messages API,
  selected with `chat_provider`. Skip it entirely for agent-driven use.
- All configuration is read from the host environment first, namespaced with the
  skill name: `DAILY_INSIGHT_EMBED_API_KEY`, `DAILY_INSIGHT_EMBED_BASE_URL`,
  `DAILY_INSIGHT_EMBED_MODEL`, `DAILY_INSIGHT_CHAT_API_KEY`,
  `DAILY_INSIGHT_CHAT_BASE_URL`, `DAILY_INSIGHT_CHAT_MODEL`,
  `DAILY_INSIGHT_CHAT_PROVIDER`, and the other `DAILY_INSIGHT_*` names in
  `references/commands.md`. A set variable overrides the stored setting for that
  call. Key material is read only from the environment and is never stored in
  the data root or echoed.

## How to Run

Resolve the directory that contains this `SKILL.md`, then call a script through
`terminal`:

```
python3 <skill-dir>/scripts/<domain>.py <verb> [flags]
```

- `<domain>` is one of `init`, `settings`, `materials`, `ingest`, `insights`,
  `reports`.
- Use the real path to the loaded skill folder; there is no placeholder
  substitution.
- Every script accepts `--home DIR`, `--format json|table`, `--tz ZONE`, and
  `--quiet`.
- Read the JSON envelope from the terminal result. If `ok` is false, read
  `error.message` and fix the call instead of guessing.
- Open `references/commands.md` with `read_file` for every flag and the exact
  brief shape.

First run: initialize, then confirm or set the budget and wake window.

```
python3 <skill-dir>/scripts/init.py init
python3 <skill-dir>/scripts/settings.py set --budget 5 --wake 08:00-22:00
python3 <skill-dir>/scripts/settings.py show
```

## Quick Reference

| The user wants to... | Run |
|---|---|
| set up the data root / check dependencies | `init.py init` |
| see or change budget, wake window, strategy, endpoints | `settings.py show\|get\|set` |
| add, list, show, rename, archive a source | `materials.py add\|list\|show\|rename\|archive` |
| set a source cadence or priority | `materials.py cadence\|priority` |
| delete a source and its vectors | `materials.py delete` |
| add text, a file, or a paste | `ingest.py ingest` |
| see the day's plan without delivering | `insights.py due` |
| deliver the next insight | `insights.py next` |
| catch up every slot due today | `insights.py run` |
| emit a scheduler artifact | `insights.py schedule-hint` |
| see coverage, history, or totals | `reports.py coverage\|history\|stats` |

Run `--help` on any domain for every flag, or read
`references/commands.md`.

## Procedure

① **Initialize once.** Ask the user for the daily budget (recommended 5), the
wake window (recommended `08:00-22:00`), and the selection policy (recommended
`coverage`), then persist them with `settings.py set`. Confirm the embedding
mode: `hash` works offline and is the default; `remote` needs a base URL and
model.

② **Add material.** Create or reuse a source with `materials.py add`, then
`ingest.py ingest <file> --material NAME`. Accepts pasted `--text` or piped
stdin too. Then ask for the cadence and set it with
`materials.py cadence NAME --count N --period day|week`. A global budget caps
the whole day; per-source cadences are trimmed round-robin by priority when the
day is over budget.

③ **Deliver.** Run `insights.py next`. It returns a brief with the slot, the
material, the excerpt, related passages, novelty, and a prompt. Compose 3-6
sentences in the user's language from the excerpt and related passages only,
name the material, and do not add facts that are not in the excerpts. Do not
call `next` more than once per requested insight unless the user wants several.
No chat model is involved here — you write the prose with the model the host
already runs.

④ **Automate only when asked.** Run
`insights.py schedule-hint --target ...` and hand the emitted artifact to the
host. The skill installs nothing. For a headless target that cannot show chat,
pass `--generate --outbox` so finished prose is appended to
`<home>/outbox/<date>.md`.

⑤ **Report.** Use `reports.py coverage` to show what is left, `reports.py
history` for recent insights, and `reports.py stats` for totals and progress.

## Pitfalls

- **Do not compose from memory.** Every sentence must trace to the excerpt or a
  related passage. If the excerpts are too thin, say so.
- **Do not re-run `next` to get more.** Each call consumes a slot from the
  daily budget; a day that is done returns `nothing_due`.
- **Config changes apply to the next day.** A day's plan is persisted on first
  contact, so raising the budget mid-day does not add slots to today.
- **Never hardcode a data path.** Resolve the home from `--home`,
  `$DAILY_INSIGHT_HOME`, then the default; cite the resolved path in output.
- **Never assume the vector backend is installed.** Catch `dependency_missing`
  and repair it rather than retrying.
- **Never echo API keys.** Settings hold environment variable *names*, not key
  material.
- **One material per insight.** Do not blend two sources into a single brief.

## Verification

```bash
python3 <skill-dir>/scripts/reports.py stats
python3 <skill-dir>/scripts/insights.py due
```

Green means the envelope has `ok: true`, `init` reports the expected dependency
status, and `due` shows a plan whose slot count is at most the budget. After a
delivery, `reports.py history` shows the new row and `next` remains safe to
re-trigger (it returns `nothing_due` once the day is full). To check automation,
run the emitted command twice and confirm the second call is a no-op.

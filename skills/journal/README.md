# journal

A portable [Agent Skill](https://skills.sh) for keeping many free-form dated
journal entries in a local SQLite file, with full-text search and a weekly
review brief. It works with any Agent Skills host (nanobot, Claude Code,
Codex, Kilo, OpenClaw, and others).

Source: <https://github.com/kakalition/apollo-pack/tree/main/skills/journal>

Everything executable lives in focused Python scripts under `journal/scripts/`.
The agent runs a script and reads its JSON output. There is no server, no
network access, no model endpoint, and no third-party dependency: the standard
library only (Python 3.9+).

## What it does

- Many free-form, dated entries per day, each with a timestamp
- Optional title, source, and computed word count
- FTS5 full-text search when the SQLite build provides it, with a plain
  `LIKE` fallback otherwise
- A read-only weekly review brief: ranges, per-day counts, missing days,
  notable lines, top terms, and a composition prompt
- Totals and consecutive-day writing runs
- All configuration read from the host environment (`JOURNAL_*`)

The weekly review is composed by the host model from the brief only; the skill
never calls a model and never invents facts.

## Install

With the skills.sh CLI:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill journal --agent <your-agent> --copy --yes
```

For nanobot specifically, `--agent openclaw` is the marketplace agent id:

```bash
npx --yes skills@latest add kakalition/apollo-pack \
  --skill journal --agent openclaw --copy --yes
```

Manual install: copy the `journal/` folder into your host's skills directory
so that `journal/SKILL.md` is discoverable. The folder name must stay
`journal`.

## Quick start

```bash
SKILL=./journal
python3 "$SKILL/scripts/init.py" init
python3 "$SKILL/scripts/settings.py" set --tz Asia/Jakarta --week-start mon
python3 "$SKILL/scripts/entries.py" add --body "First entry." --date 2026-01-05
python3 "$SKILL/scripts/entries.py" search entry
python3 "$SKILL/scripts/reports.py" week --week 2026-W02
```

Add from a file or piped text too:

```bash
python3 "$SKILL/scripts/entries.py" add --file notes.md
printf 'a quick thought' | python3 "$SKILL/scripts/entries.py" add
```

## Requirements

- Python 3.9 or newer, standard library only
- SQLite with FTS5 for fast search; without it, search falls back to a
  substring scan and `settings.py show` reports `fts_enabled: false`
- A writable location for the database (default
  `~/.local/share/journal/journal.db`)

## Where the data lives

Resolved in order: `--db PATH`, `$JOURNAL_DB`, then
`~/.local/share/journal/journal.db`. Back up by copying that one file. No
personal data is stored in this repository.

## Weekly review

```bash
python3 "$SKILL/scripts/reports.py" week
python3 "$SKILL/scripts/reports.py" week --week 2026-W02
python3 "$SKILL/scripts/reports.py" stats --from 2026-01-01 --to 2026-01-07
```

`week` returns `read_only: true` and a `prompt`; the host model writes 3-6
sentences from the returned brief and names nothing that is not in the
entries. See `journal/references/schema.md`.

## Automate a weekly brief

```bash
python3 "$SKILL/scripts/reports.py" schedule-hint --target generic
```

`schedule-hint` emits an artifact for the target and installs nothing. See
`journal/references/scheduling.md`.

## Layout

```
skills/journal/
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

The harness runs the scripts end to end against throwaway databases and checks
hand-computed word counts and weekly summaries, FTS5 search, the `LIKE`
fallback, reindexing on edit, scheduling artifacts, and error handling.

## License

MIT. See `LICENSE`.

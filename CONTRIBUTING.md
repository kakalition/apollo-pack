# Contributing

Thanks for improving apollo-pack. This document covers the layout, metadata,
and checks that keep the pack consistent.

## Layout

```
apollo-pack/
├── skills/<id>/     # one Agent Skill per folder; <id> == frontmatter name
├── docs/            # cross-cutting documentation
└── tools/           # pack tooling (catalog generator)
```

Skills stay portable: prefer the standard library. A skill that needs a heavy
or optional package must declare it in a `requirements.txt` (as `daily-insight`
and `pdf-creator` do) and keep its non-rendering verbs working without the
package installed.

A skill that needs a non-Python runtime declares the Node-assisted pattern
instead (`charting`): commit `package.json` and `package-lock.json`, pin
exact versions, gitignore `node_modules/` and any generated bundle, keep every
state/library/validation verb in standard-library Python, and make only the
render verb require Node — failing fast with a `dependency_missing` error that
names the exact install command. Its smoke test must self-skip the render
sections when the runtime is absent.

Scripts must not name a specific host (no `nanobot`, `hermes`, `claude`,
`codex`, or `kilo` tokens outside the documented scheduling files). Host
discovery relies on the folder name matching the skill `name`.

## Adding or changing a skill

1. Put the skill at `skills/<id>/` with `SKILL.md`, `scripts/`, and
   `references/`.
2. Give `SKILL.md` frontmatter with at least `name`, `description`, `version`,
   `license`, `author`, and `platforms`. `metadata.hermes.{tags,category}` is
   optional and passed through to the catalog.
3. Keep `tests/smoke.sh` hermetic and runnable with `bash tests/smoke.sh`.
4. Refresh the catalog (below).

## Catalog

`catalog.json` and the catalog table in `README.md` are generated from item
metadata. After any item change:

```bash
uv run tools/catalog.py build
uv run tools/catalog.py check
```

`build` is deterministic; a second run must produce no diff. Commit both
`catalog.json` and `README.md` together.

## Checks

```bash
uv run tools/catalog.py check
bash skills/habit-tracker/tests/smoke.sh
bash skills/journal/tests/smoke.sh
bash skills/personal-finance/tests/smoke.sh
bash skills/daily-insight/tests/smoke.sh   # needs skills/daily-insight/requirements.txt
bash skills/pdf-creator/tests/smoke.sh     # needs skills/pdf-creator/requirements.txt
bash skills/charting/tests/smoke.sh   # Node 20+ and the built bundle gate the render checks
```

Pack CI runs the same set and a secret scan.

## Commits

Keep commits focused and write a short imperative subject. Do not commit
`kilo.json` or any other file that contains a secret.

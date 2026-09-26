# Scheduler-latch reference

`render.py schedule-hint` emits an artifact that re-renders a stored chart or a
spec file on a schedule. Like every skill in this pack it **installs nothing**:
it prints instructions and routes, and the host agent or user registers them. A
generic latch caller only needs `--target`, `--at-time`, `--tz`, `--name`, and
the storage flag (`--home`).

## Verb

```
python3 <skill-dir>/scripts/render.py schedule-hint [flags]
```

| Flag | Values | Notes |
|---|---|---|
| `--doc NAME` / `--spec FILE` | one required | the chart to render |
| `--out FILE` | path | output PNG (default `<home>/output/<name>.png`) |
| `--target` | `generic` `nanobot` `hermes` `claude` `codex` `kilo` `crontab` `systemd` `launchd` | default `generic` |
| `--path-mode` | `abs` `relative` `skill` | how emitted commands refer to the scripts |
| `--at-time` | `HH:MM` | daily trigger, default `08:00` |
| `--tz` | IANA zone | default `$TZ`, else `UTC` |
| `--name` | string | job name, default `charting-render` |
| `--action` | `add` `enable` `disable` `remove` `list` | default `add` |
| `--job` | string | required for `enable`/`disable`/`remove` |

## Envelope

`data` always contains `target`, `path_mode`, `generated_at`, `skill_dir`,
`script`, `store`, `name`, `cron_expr`, `tz`, `commands`, and
`installs_nothing: true`.

`commands` has two steps:

- `post` — `render.py render --doc NAME --out OUT --force --quiet`. It writes
  only the output PNG and overwrites it on each run, so duplicate fires are
  harmless.
- `report` — `reports.py history --limit 1`, read-only.

## Target matrix

- **generic / claude / codex / kilo** — `via: "host"`. The agent maps the
  artifact to the host's scheduler. No host tokens are hard-coded.
- **nanobot** — returns a `cron_tool` block (`action`, `name`, `message`,
  `cron_expr`, `tz`) whose message starts with `$charting`. Create it from a
  live chat session; keep `cron_expr` and `tz` together.
- **hermes** — returns a `cronjob` block with `skills: ["charting"]`, a
  pre-run `script`, and an equivalent `hermes cron add` line.
- **crontab** — emits a single `lines` entry; `%` is escaped for `date`.
- **systemd** — emits a `.service` and `.timer` under `install.files` plus the
  `systemctl --user` commands. `Persistent=true` catches up missed runs.
- **launchd** — emits a valid plist under `install.files` plus the `cp` and
  `launchctl load` commands.

## Manage actions

`--action enable|disable|remove|list` emits an instruction artifact with
`action`, `job`, `host_support`, `via`, `routes`, and `add_command`, and still
sets `installs_nothing: true`. The chat targets support `add`/`list`/`remove`;
`enable`/`disable` route through the WebUI automations API with a blunt
`remove` fallback. OS targets carry the exact shell commands. Host targets route
to `via: "host"` for the agent to map.

## Dry run

```bash
# a generic artifact that renders a stored chart
python3 scripts/render.py schedule-hint \
  --doc revenue --out ~/reports/revenue.png \
  --target generic --path-mode abs --tz Asia/Jakarta --name revenue-daily

# an on/off instruction
python3 scripts/render.py schedule-hint \
  --doc revenue --target nanobot --action disable --job revenue-daily
```

## Conformance checklist

1. `render.py schedule-hint` accepts all nine targets and the flags above.
2. `data` carries `store` and `installs_nothing: true`.
3. `commands[].step` is only `post` or `report`.
4. `nanobot` and `hermes` return a `cron_tool` block with `name`, `message`,
   `cron_expr`, and `tz`; the message starts with `$charting`.
5. `--action` covers `add` `enable` `disable` `remove` `list`.
6. `references/scheduling.md` (this file) documents the matrix.
7. `tests/smoke.sh` executes the emitted `report` command twice and checks it is
   a read-only no-op.

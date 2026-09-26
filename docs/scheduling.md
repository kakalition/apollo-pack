# Scheduler-latch contract

Local-first [Agent Skills](https://skills.sh), one per folder under `skills/`.
Every skill prints one JSON envelope per run; most are standard library only,
while a skill with a heavy dependency declares it in its own `requirements.txt`.
None of them ever installs, mutates, or talks to a scheduler on its own.

This document defines the **scheduler-latch interface**: the uniform
`schedule-hint` contract the skills share, so one agent (or one script) can
latch any of them into a host scheduler (nanobot, hermes, ...) or an OS
scheduler (crontab, systemd, launchd) without special-casing.

See the [pack README](../README.md) for how to install the skills.

## The skills

| Folder | Skill | Scheduler verb | Storage flag | Default latching cadence |
|---|---|---|---|---|
| `skills/daily-insight/` | `daily-insight` | `insights.py schedule-hint` | `--home DIR` | several slots per day (from wake window + budget) |
| `skills/personal-finance/` | `personal-finance` | `recurring.py schedule-hint` | `--db PATH` | daily |
| `skills/habit-tracker/` | `habit-tracker` | `reports.py schedule-hint` | `--db PATH` | daily |
| `skills/journal/` | `journal` | `reports.py schedule-hint` | `--db PATH` | daily |
| `skills/pdf-creator/` | `pdf-creator` | `render.py schedule-hint` | `--home DIR` | daily |
| `skills/charting/` | `charting` | `render.py schedule-hint` | `--home DIR` | daily |

`--home` is used by the skills whose data root holds more than one file
(`daily-insight`: a SQLite file, a vector store, and an outbox; `pdf-creator`: a
SQLite library plus `assets/`, `fonts/`, and `output/`; `charting`: a SQLite
library plus `output/` and `tmp/`). The others take a single `--db PATH`.
Whichever flag applies, the resolved path is always echoed under the uniform
`store` key.

## The contract

Every schedulable script exposes one verb:

```
python3 <skill-dir>/scripts/<script>.py schedule-hint [flags]
```

### Flags

| Flag | Values | Notes |
|---|---|---|
| `--target` | `generic` `nanobot` `hermes` `claude` `codex` `kilo` `crontab` `systemd` `launchd` | required choice, default `generic` |
| `--path-mode` | `abs` `relative` `skill` | how the emitted command refers to the script |
| `--at-time` | `HH:MM` | single trigger time, default `08:00`; collapses multi-slot skills to one time |
| `--tz` | IANA zone | default the stored timezone, then `$TZ`, then `UTC` |
| `--name` | string | job name for agent targets |
| `--action` | `add` `enable` `disable` `remove` `list` | default `add`; non-`add` emits an instruction artifact (on/off support) |
| `--job` | string | job name or id, required for `enable`/`disable`/`remove` |
| storage flag | `--db PATH` or `--home DIR` | skill-specific; echoed as `store` |

Skills may accept extra flags (`--budget`, `--wake`, `--within`); a generic
latch caller only needs the table above.

### Envelope

Success is one JSON object on stdout:

```json
{ "ok": true, "command": "<script>.schedule-hint", "data": { ... } }
```

`data` always contains these keys:

| Key | Meaning |
|---|---|
| `target`, `path_mode` | echoed choices |
| `generated_at` | date the artifact was generated (`YYYY-MM-DD`) |
| `skill_dir` | absolute path to the loaded skill folder |
| `script` | how the script is referenced, per `path_mode` |
| `store` | resolved storage path (`--db`/`--home`, or the default) |
| `name` | job name |
| `cron_expr` | 5-field cron expression (`M H * * *` form) |
| `tz` | IANA timezone for `cron_expr` |
| `commands` | list of `{step, description, command}` |
| `installs_nothing` | always `true` |

Skill-specific extras (`slot_times`, `budget`, `wake`, `db`, `home`,
`read_only`, `within`, ...) are allowed and ignored by a generic latch caller.

### `commands[].step`

Exactly two values, so a caller knows what is safe to re-run:

- `post` — writes state (for example, deliver an insight, post a recurring
  transaction). Idempotent where the skill can make it so.
- `report` — read-only.

A skill may emit several `post` commands (multiple slots) followed by a
`report`, or just one `report`.

### `installs_nothing`

Every artifact sets `installs_nothing: true`. `schedule-hint` never writes a
crontab, a unit file, or a chat cron job. The agent or the user registers the
artifact.

## Actions (on / off)

`--action add` (the default) emits the install artifact described above, with
`data.action: "add"`. The other actions emit an **instruction artifact** that
turns a latched job on, off, or removes it. `schedule-hint` still installs and
changes nothing itself; it names the host action and the routes that can carry
it out:

```json
{
  "action": "disable",
  "job": "habit-tracker-daily",
  "installs_nothing": true,
  "host_support": {"add": true, "list": true, "remove": true, "enable": false, "disable": false},
  "via": "chat_cron_tool",
  "routes": [
    {"via": "webui_automations", "action": "disable", "params": {"id": "habit-tracker-daily"}, "note": "requires the WebUI API token"},
    {"via": "cron_tool", "action": "remove", "params": {"job_id": "habit-tracker-daily"}, "note": "blunt off: deletes the job; re-add to restore"}
  ],
  "add_command": "python3 .../reports.py due --as-of \"$(date +%F)\" --db ..."
}
```

- `add` — install the job (full artifact, as above).
- `list` — `via` the host tool (`cron_tool action: "list"` on nanobot).
- `remove` — `cron_tool action: "remove"` (nanobot) or the OS equivalent.
- `disable` / `enable` — the target's on/off route.

`host_support` records which actions the *chat tool* itself supports; routes
list every way to achieve the action. On **nanobot**, the chat `cron` tool only
supports `add`/`list`/`remove`, so `enable`/`disable` route through the WebUI
automations API (`enable_path` needs the API token) with a blunt `remove`
fallback. On **hermes** the routes use the `hermes cron` CLI. For `generic`/
`claude`/`codex`/`kilo` the route is `via: "host"`, for you or the host to map.
For **crontab**/**systemd**/**launchd** the routes carry the exact shell
commands (comment/uncomment, `systemctl --user enable|disable --now`,
`launchctl load|unload`, delete, list).

Re-create or re-run the job with `add_command` when a route needs it.

## Latching to nanobot / OpenClaw

`--target nanobot` returns fields for nanobot's built-in `cron` tool:

```json
{
  "target": "nanobot",
  "name": "habit-tracker-daily",
  "message": "$habit-tracker Check which habits are due today and report them. Run: ...",
  "cron_expr": "0 8 * * *",
  "tz": "Asia/Jakarta",
  "cron_tool": {
    "action": "add",
    "name": "habit-tracker-daily",
    "message": "$habit-tracker ...",
    "cron_expr": "0 8 * * *",
    "tz": "Asia/Jakarta"
  },
  "store": "/home/you/.local/share/habit-tracker/habits.db",
  "installs_nothing": true
}
```

To latch: pass `cron_tool` to the host's cron tool with `action="add"`.
Rules the host enforces:

- Create the job **from a live chat session**. A script cannot create cron
  jobs, and jobs cannot be created from inside a cron run.
- Keep `cron_expr` and `tz` together; the tool rejects `tz` without
  `cron_expr`.
- The message uses the `$<skill>` explicit invocation so the cron turn re-enters
  the skill from its `SKILL.md`.
- `dream` and `heartbeat` are protected system jobs: visible, not removable.

## Latching to hermes

`--target hermes` returns fields for hermes' `cronjob` tool, including a
pre-run `script` whose stdout hermes injects into the prompt, a `skills` list,
and an equivalent CLI string:

```json
{
  "cron_tool": {
    "action": "add",
    "tool": "cronjob",
    "name": "journal-weekly",
    "message": "$journal Build the weekly review brief and write the review from it.",
    "cron_expr": "0 8 * * *",
    "tz": "Asia/Jakarta",
    "skills": ["journal"],
    "script": "/abs/path/journal/scripts/reports.py week --format json"
  },
  "hermes_cli": "hermes cron add --name journal-weekly --schedule '0 8 * * *' --skills journal"
}
```

## OS fallbacks (no chat notification)

`crontab`, `systemd`, and `launchd` run the script directly and put the
platform artifact under `data.install` (`lines`, or `files` plus `commands`).
They never load a skill into a chat session, so a read-only report is the safe
default.

- crontab escapes `%` in `date +%F` as `\%`; systemd escapes it as `%%`.
- launchd emits a valid plist.

### Path modes

- `abs` — absolute path resolved now. Default for the OS targets, `nanobot`,
  and `hermes`, which do not substitute placeholders.
- `relative` — `scripts/<script>.py`, for a scheduler that sets the working
  directory.
- `skill` — `{skillDir}/scripts/<script>.py`, for a host that substitutes its
  loaded skill directory.

## Per-skill notes

- **daily-insight** derives its trigger times from the wake window and daily
  budget (`slot_times`, several `post` commands, multi-time `cron_expr`). Pass
  `--at-time HH:MM` to collapse it to a single daily trigger. Storage is
  `--home DIR`.
- **personal-finance** emits a `post` command (`recurring.py run`,
  idempotent) then a `report` command (`recurring.py due`); `--within DAYS`
  sets the report window.
- **habit-tracker** and **journal** emit a single read-only `report` command
  (`reports.py due` / `reports.py week`); re-firing is always harmless.
- **pdf-creator** emits a `post` command (`render.py render --doc NAME --force`)
  that rewrites one output PDF, then a read-only `report` command
  (`reports.py history --limit 1`). Pass `--doc NAME` (or `--spec FILE`) and
  optionally `--out FILE`.
- **charting** mirrors pdf-creator: a `post` command
  (`render.py render --doc NAME --force`) rewrites one output PNG, then a
  read-only `report` command (`reports.py history --limit 1`). Pass `--doc NAME`
  (or `--spec FILE`) and optionally `--out FILE`. Rendering needs Node and the
  built bundle, so an unattended job should be validated with
  `render.py check --strict` first.

## Dry run every skill

Each command prints an artifact and writes nothing to a scheduler:

```bash
python3 skills/daily-insight/scripts/insights.py schedule-hint \
  --target nanobot --at-time 08:00 --tz Asia/Jakarta --name daily-insight

python3 skills/personal-finance/scripts/recurring.py schedule-hint \
  --target nanobot --at-time 08:00 --tz Asia/Jakarta --name personal-finance

python3 skills/habit-tracker/scripts/reports.py schedule-hint \
  --target nanobot --at-time 08:00 --tz Asia/Jakarta --name habit-tracker

python3 skills/journal/scripts/reports.py schedule-hint \
  --target nanobot --at-time 08:00 --tz Asia/Jakarta --name journal

python3 skills/pdf-creator/scripts/render.py schedule-hint \
  --doc invoice --out ~/invoices/current.pdf \
  --target nanobot --at-time 08:00 --tz Asia/Jakarta --name pdf-creator

python3 skills/charting/scripts/render.py schedule-hint \
  --doc revenue --out ~/reports/revenue.png \
  --target nanobot --at-time 08:00 --tz Asia/Jakarta --name charting
```

## Conformance checklist for a new skill

1. One script exposes `schedule-hint` with the flags above (extra flags are
   fine).
2. `data` carries every required key, including `store` and
   `installs_nothing: true`.
3. `commands[].step` is only `post` or `report`.
4. All nine targets are accepted; `nanobot` and `hermes` return a `cron_tool`
   block that includes `name`, `message`, `cron_expr`, and `tz`.
5. The `message` starts with `$<skill>`.
6. `--action` covers `add` `enable` `disable` `remove` `list`; non-`add`
   artifacts carry `action`, `job`, `host_support`, `via`, `routes`, and
   `add_command`, and still set `installs_nothing: true`.
7. `references/scheduling.md` documents the target matrix; the smoke test
   checks `ok`, `installs_nothing`, path modes, the manage actions, and
   executes the emitted `report` command twice as a read-only no-op. A skill
   whose `post` step writes a file must make that write idempotent.

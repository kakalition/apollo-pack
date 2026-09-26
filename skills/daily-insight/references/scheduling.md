# Scheduling (agent-agnostic)

Scheduling is opt-in and one-directional: `insights.py schedule-hint` **emits**
an artifact for a chosen target and installs nothing. The host or the user
registers it. The skill's SQLite + vector data root stays the source of truth
for what is delivered; the scheduler only triggers.
`insights.py next` is idempotent per `(date, slot_index)`, so over-firing,
retries, and catch-up triggers are all safe.

Two commands are involved:

1. `insights.py next` — delivers at most one insight and returns a brief.
2. `insights.py due` — read-only preview of the plan.

`--path-mode abs|relative|skill` controls how the emitted command references
`scripts/insights.py`: `abs` resolves the absolute path now (the default for the
OS targets, `nanobot`, and `hermes`), `relative` emits `scripts/insights.py`,
and `skill` emits the `{skillDir}/scripts/insights.py` placeholder for a host
that substitutes its loaded skill directory. Other flags: `--at-time HH:MM`
(collapse the day to a single trigger time), `--budget N`,
`--wake HH:MM-HH:MM`, `--name JOB`, `--generate`, `--outbox`. Each emitted
command carries `step: "post"` because `next` writes a delivery.

## On / off

`--action add` (the default) emits an install artifact. `--action
list|enable|disable|remove` emits an instruction artifact instead: it sets
`action` and `job`, keeps `installs_nothing: true`, and lists `routes` for
carrying the action out. On nanobot the chat `cron` tool only supports
`add`/`list`/`remove`, so `enable`/`disable` route through the WebUI
automations API (token required) with a `remove` fallback; on hermes the routes
use the `hermes cron` CLI; OS targets carry exact shell commands. `--job
<name>` is required for `enable`/`disable`/`remove`.

## Targets

| Target | Emits | Notifies in chat? |
|---|---|---|
| `generic` | instructions, one command per slot, notes | depends on host |
| `nanobot` | `{name, message, cron_expr, tz, cron_tool}` | yes |
| `hermes` | `{name, message, cron_expr, tz, skills, script, cron_tool}` + CLI form | yes |
| `claude` | instructions plus commands; fall back to an OS target | no |
| `codex` | instructions plus commands; fall back to an OS target | no |
| `kilo` | instructions plus commands; fall back to an OS target | no |
| `crontab` | one ready line per slot | no |
| `systemd` | `daily-insight.service` and `daily-insight.timer` contents | no |
| `launchd` | `com.daily-insight.deliver.plist` contents | no |

A single cron expression cannot always express several slot times, so the
artifact also provides `slot_times`. Over-firing is harmless: `next` returns
`nothing_due` once the day's budget is exhausted.

## nanobot / OpenClaw

The `nanobot` target returns fields for the built-in `cron` tool:

```json
{
  "name": "daily-insight",
  "message": "$daily-insight Deliver the next due insight and render it for me.",
  "cron_expr": "0,30 9,13,18 * * *",
  "tz": "Asia/Jakarta",
  "cron_tool": {"action": "add", "name": "daily-insight", "message": "...", "cron_expr": "...", "tz": "..."}
}
```

Create the job with `action="add"` **from a live chat session**; a script cannot
create cron jobs, and jobs cannot be added from inside a cron run. Keep
`cron_expr` and `tz` together — the tool rejects `tz` without `cron_expr`.
Protected system jobs (`dream`, `heartbeat`) can be listed but not removed.
For a background check that should stay silent unless there is something to
report, put it in `HEARTBEAT.md` instead of creating a cron job.

## Hermes

The `hermes` target returns fields for the `cronjob` tool:

```json
{
  "name": "daily-insight",
  "message": "$daily-insight Deliver the next due insight and render it for me.",
  "cron_expr": "0,30 9,13,18 * * *",
  "tz": "Asia/Jakarta",
  "skills": ["daily-insight"],
  "script": "/abs/path/daily-insight/scripts/insights.py next --format json",
  "cron_tool": {"action": "add", "tool": "cronjob", "skills": ["daily-insight"], "script": "..."}
}
```

Hermes injects the pre-run `script`'s stdout into the prompt. Pass `--generate`
to add `--generate --outbox` to the script and set `no_agent: true`, so the
script output is the whole job. The artifact also carries an equivalent
`hermes cron add ...` command for users without the tool. Schedules may be a
duration, an "every" phrase, a 5-field cron, or an ISO one-shot; a per-job
`skills` list and `script` are supported.

## OS targets (portable fallback, no chat notification)

These run the script directly and, because they cannot show chat, pass
`--generate --outbox` so finished prose lands in `<home>/outbox/<date>.md`. Use
`--quiet` to keep an exhausted day silent.

### crontab

One line per slot; append with `crontab -e`. The `%` character is escaped as
`\%` inside crontab.

```
0 9 * * * /usr/bin/env python3 <script> next --format json --generate --outbox --home <home> --quiet
30 13 * * * /usr/bin/env python3 <script> next --format json --generate --outbox --home <home> --quiet
```

### systemd (Linux, user units)

Write the two emitted files to `~/.config/systemd/user/`, then:

```
systemctl --user daemon-reload
systemctl --user enable --now daily-insight.timer
```

`Persistent=true` catches up runs missed while the machine was off.

### launchd (macOS)

Write the emitted plist to `~/Library/LaunchAgents/`, then:

```
launchctl load ~/Library/LaunchAgents/com.daily-insight.deliver.plist
```

launchd runs missed jobs on wake.

## Rules and triggers are independent

- Removing a scheduled trigger never deletes materials or cadences.
- Deleting a material never removes a trigger.
- Archiving a material stops its slots even while a trigger keeps firing.
- The trigger only runs commands; it never selects a chunk.

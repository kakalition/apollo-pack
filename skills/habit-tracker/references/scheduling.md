# Scheduling (agent-agnostic)

Scheduling is opt-in and one-directional: `reports.py schedule-hint` **emits**
an artifact for a chosen target and installs nothing. The host or user
registers it. The database stays the source of truth for cadences and
streaks; the scheduler only triggers a read-only report.

The emitted artifact calls:

1. `reports.py due --as-of "$(date +%F)"` — read-only. Lists habits that are
   due, plus interval habits due inside the window.

Nothing is written, so over-firing, retries, and catch-up triggers are all
safe no-ops.

`--path-mode abs|relative|skill` controls how the emitted command references
`scripts/reports.py`: `abs` resolves the absolute path now (the default for the
OS targets, `nanobot`, and `hermes`), `relative` emits
`scripts/reports.py`, and `skill` emits the `{skillDir}/scripts/reports.py`
placeholder for a host that substitutes its loaded skill directory. Other
flags: `--at-time HH:MM` (daily trigger, default 08:00), `--tz ZONE` (default
the stored timezone, then `$TZ`, then `UTC`), `--name JOB` (agent targets).

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
| `generic` | instructions, the report command, notes | depends on host |
| `nanobot` | `{name, message, cron_expr, tz, cron_tool}` | yes |
| `hermes` | `{name, message, cron_expr, tz, skills, script, cron_tool}` + CLI form | yes |
| `claude` | instructions plus the command; fall back to an OS target | no |
| `codex` | instructions plus the command; fall back to an OS target | no |
| `kilo` | instructions plus the command; fall back to an OS target | no |
| `crontab` | one ready crontab line | no |
| `systemd` | `habit-tracker-due.service` and `.timer` contents | no |
| `launchd` | `com.habit-tracker.due.plist` contents | no |

The report is read-only, so a single daily trigger is enough; there is no slot
list to fan out.

## nanobot / OpenClaw

The `nanobot` target returns fields for the built-in `cron` tool:

```json
{
  "name": "habit-tracker-daily",
  "message": "$habit-tracker Check which habits are due today and report them. Run: ...",
  "cron_expr": "0 8 * * *",
  "tz": "Asia/Jakarta",
  "cron_tool": {"action": "add", "name": "habit-tracker-daily", "message": "...", "cron_expr": "0 8 * * *", "tz": "Asia/Jakarta"}
}
```

Create the job with `action="add"` **from a live chat session**; a script
cannot create cron jobs, and jobs cannot be added from inside a cron run. Keep
`cron_expr` and `tz` together — the tool rejects `tz` without `cron_expr`.
Protected system jobs (`dream`, `heartbeat`) can be listed but not removed.

## Hermes

The `hermes` target returns fields for the `cronjob` tool, including a
pre-run `script` whose stdout Hermes injects into the prompt, a `skills` list,
and an equivalent `hermes cron add ...` command:

```json
{
  "name": "habit-tracker-daily",
  "message": "$habit-tracker Check which habits are due today and report them.",
  "cron_expr": "0 8 * * *",
  "tz": "Asia/Jakarta",
  "skills": ["habit-tracker"],
  "script": "/abs/path/habit-tracker/scripts/reports.py due --as-of \"$(date +%F)\" --format json",
  "cron_tool": {"action": "add", "tool": "cronjob", "skills": ["habit-tracker"], "script": "..."}
}
```

## OS targets (portable fallback, no chat notification)

These run the script directly with `--quiet`, so an empty day stays silent.
Cancelling a trigger never changes the habits.

### crontab

Append the emitted line with `crontab -e`. In crontab the `%` in `date +%F` is
escaped as `\%`:

```
0 8 * * * /usr/bin/env python3 <script> due --as-of "$(date +\%F)" --db <db> --quiet
```

### systemd (Linux, user units)

Write both emitted files to `~/.config/systemd/user/`, then:

```
systemctl --user daemon-reload
systemctl --user enable --now habit-tracker-due.timer
```

`Persistent=true` catches up runs missed while the machine was off. In a
systemd unit the `%` in `date +%F` is escaped as `%%`.

### launchd (macOS)

Write the emitted plist to `~/Library/LaunchAgents/`, then:

```
launchctl load ~/Library/LaunchAgents/com.habit-tracker.due.plist
```

launchd runs missed jobs on wake.

## Rules and triggers are independent

- Removing or cancelling a trigger does not change habits or check-ins.
- Pausing or archiving a habit hides it from the report even while a trigger
  keeps firing.
- The trigger only runs a read-only command; it never computes a streak.

See `commands.md` for exact flags and `schema.md` for the data model.

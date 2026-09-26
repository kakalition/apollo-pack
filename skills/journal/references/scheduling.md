# Scheduling (agent-agnostic)

Scheduling is opt-in and one-directional: `reports.py schedule-hint` **emits**
an artifact for a chosen target and installs nothing. The host or user
registers it. The database stays the source of truth; the scheduler only
triggers a read-only weekly brief.

The emitted artifact calls:

1. `reports.py week` — read-only. Builds the weekly review brief for the
   current week (per the `week_start` setting) for the host model to compose
   from.

Nothing is written, so over-firing, retries, and catch-up triggers are all
safe no-ops.

`--path-mode abs|relative|skill` controls how the emitted command references
`scripts/reports.py`: `abs` resolves the absolute path now (the default for the
OS targets, `nanobot`, and `hermes`), `relative` emits `scripts/reports.py`,
and `skill` emits the `{skillDir}/scripts/reports.py` placeholder for a host
that substitutes its loaded skill directory. Other flags: `--at-time HH:MM`
(trigger time, default 08:00), `--tz ZONE` (default the stored timezone, then
`$TZ`, then `UTC`), `--name JOB` (agent targets).

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
| `crontab` | one ready crontab line (Sundays) | no |
| `systemd` | `journal-weekly.service` and `.timer` contents | no |
| `launchd` | `com.journal.weekly.plist` contents | no |

## nanobot / OpenClaw

The `nanobot` target returns fields for the built-in `cron` tool:

```json
{
  "name": "journal-weekly",
  "message": "$journal Build the weekly review brief and write the review from it. Run: ...",
  "cron_expr": "0 8 * * *",
  "tz": "Asia/Jakarta",
  "cron_tool": {"action": "add", "name": "journal-weekly", "message": "...", "cron_expr": "0 8 * * *", "tz": "Asia/Jakarta"}
}
```

Create the job with `action="add"` **from a live chat session**; a script
cannot create cron jobs, and jobs cannot be added from inside a cron run. Keep
`cron_expr` and `tz` together — the tool rejects `tz` without `cron_expr`.
Protected system jobs (`dream`, `heartbeat`) can be listed but not removed.

## Hermes

The `hermes` target returns fields for the `cronjob` tool, including a pre-run
`script` whose stdout Hermes injects into the prompt, a `skills` list, and an
equivalent `hermes cron add ...` command:

```json
{
  "name": "journal-weekly",
  "message": "$journal Build the weekly review brief and write the review from it.",
  "cron_expr": "0 8 * * *",
  "tz": "Asia/Jakarta",
  "skills": ["journal"],
  "script": "/abs/path/journal/scripts/reports.py week --format json",
  "cron_tool": {"action": "add", "tool": "cronjob", "skills": ["journal"], "script": "..."}
}
```

## OS targets (portable fallback, no chat notification)

These run the script directly with `--quiet`. Cancelling a trigger never
changes the entries.

### crontab

Append the emitted line with `crontab -e`. The line runs on Sundays:

```
0 8 * * 0 /usr/bin/env python3 <script> week --db <db> --quiet
```

### systemd (Linux, user units)

Write both emitted files to `~/.config/systemd/user/`, then:

```
systemctl --user daemon-reload
systemctl --user enable --now journal-weekly.timer
```

### launchd (macOS)

Write the emitted plist to `~/Library/LaunchAgents/`, then:

```
launchctl load ~/Library/LaunchAgents/com.journal.weekly.plist
```

## Rules and triggers are independent

- Removing or cancelling a trigger does not change any entry.
- The trigger only runs a read-only command; it never writes or calls a model.

See `commands.md` for exact flags and `schema.md` for the data model.

# Host compatibility

The skill is a plain Agent Skills folder, so it has no per-host code paths. It
needs a compliant `SKILL.md` plus scripts invoked by an absolute or
skill-relative path. This file records the per-host specifics; `SKILL.md`
itself stays host-neutral.

`SKILL.md` frontmatter is written to satisfy the strictest common denominator
(Claude Code, Kilo, Codex, nanobot/OpenClaw, Hermes, skills.sh): a short
one-sentence `description`, `version`, `author` (human first), `license`,
`platforms`, and `metadata.hermes.{tags,category,related_skills}`. Hosts that do
not know a field ignore it.

`platforms: [linux, macos, windows]` is honest: the scripts import only
`pathlib`, `sqlite3`, `urllib`, `hashlib`, and other standard-library modules;
they use no `fcntl`, `/proc`, `osascript`, or bash-only primitives. Timezone
resolution uses `zoneinfo` and falls back to UTC.

## Discovery and invocation

| Host | Skills discovery | Invoke scripts | Scheduling |
|---|---|---|---|
| Claude Code | `~/.claude/skills/daily-insight/` | `Bash` + `Read` | OS targets (`crontab`, `launchd`) |
| Hermes | `~/.hermes/skills/daily-insight/` (agentskills.io loader, `HERMES_HOME` aware) | `terminal`, `read_file`, `patch` | `hermes` target → `cronjob` tool / `hermes cron add`, with `skills: [daily-insight]` and optional `script` pre-run |
| Codex | `~/.codex/skills/daily-insight/` | shell tool | OS targets |
| Kilo | `~/.config/kilo/skills/daily-insight/` or project `.kilo/skills/daily-insight/` | `Bash` + `Read` | OS targets / Agent Manager workflows |
| nanobot / OpenClaw | `<workspace>/skills/daily-insight/` (marketplace agent id `openclaw`) | `exec` | `nanobot` target → built-in `cron` tool |
| Generic | the host's skills directory | the host's exec tool | `generic` artifact or an OS target |

The folder name must stay `daily-insight` and `SKILL.md` must sit directly
inside it. The data root is independent of the skill folder, so reinstalling or
upgrading the skill never touches the user's materials or history.

## Install

With the skills.sh CLI:

```bash
npx --yes skills@latest add <owner>/apollo-pack \
  --skill daily-insight --agent <your-agent> --copy --yes
```

For nanobot specifically, `--agent openclaw` is the marketplace agent id and it
copies into `<workspace>/skills`.

Manual install: copy the `daily-insight/` folder into the host's skills
directory so that `daily-insight/SKILL.md` is discoverable. Copying is safe to
repeat; the data root is elsewhere.

## Running under any host

Resolve the loaded skill directory and call:

```
python3 <skill-dir>/scripts/init.py init
python3 <skill-dir>/scripts/ingest.py ingest book.md --material "Book"
python3 <skill-dir>/scripts/insights.py next
```

Use the host's terminal/exec tool for that command and read the JSON it prints.
`--home` can point anywhere the host can write; otherwise the skill uses
`$DAILY_INSIGHT_HOME` or `~/.local/share/daily-insight`.

## Notes per host

- **Claude Code** has no native scheduler; emit an OS target and register it.
- **Hermes** can run a per-job pre-run `script` whose stdout is injected into
  the prompt, and can run the script as the entire job via `no_agent`. Use
  `skills: [daily-insight]` so the cron session can load the skill.
- **Codex** uses the shell tool and OS targets.
- **Kilo** discovers skills from `~/.config/kilo/skills/` or a project
  `.kilo/skills/`; OS targets and Agent Manager workflows are both available.
- **nanobot / OpenClaw** loads skills from `<workspace>/skills/`. Create cron
  jobs with the built-in `cron` tool from a live chat session, never by calling
  the CLI through `exec`. Silent checks belong in `HEARTBEAT.md`.

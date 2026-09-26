# nanobot-live-status

Show **one rotating status sentence** in Telegram while a nanobot turn runs:
the same message is edited in place every few seconds, then removed when the
answer arrives. No step list, no elapsed timer, no tool names, no shell
commands — just a warm phrase that changes.

> Not affiliated with, or endorsed by, the [nanobot](https://github.com/HKUDS/nanobot)
> project. This is an independent third-party plugin.

Source: <https://github.com/kakalition/apollo-pack/tree/main/plugins/nanobot-live-status>

## Apply it now

Three commands and one chat message. Full details follow below.

```bash
# 1. Install the plugin into nanobot's own tool environment.
#    (From a local checkout, replace the name with the repo path.)
uv pip install --python "$(uv tool dir)/nanobot-ai/bin/python" nanobot-live-status

# 2. Hide the noisy "$ command" tool hints (writes a JSON file; no secrets touched).
python - <<'PY'
import json, pathlib
p = pathlib.Path.home() / ".nanobot" / "config.json"
cfg = json.loads(p.read_text())
cfg.setdefault("channels", {})["sendToolHints"] = False
p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
PY

# 3. Confirm the entry point resolves (the tool env's bin is often not on PATH).
"$(uv tool dir)/nanobot-ai/bin/nanobot-live-status" doctor
#   -> live_status registered: yes
```

4. Send `/restart` in your chat. The gateway now loads the plugin and the
   config, and the next turn shows the rotating sentence.

To revert:

```bash
uv pip uninstall --python "$(uv tool dir)/nanobot-ai/bin/python" nanobot-live-status
# and set channels.sendToolHints back to true (or restore your config backup)
```

```
🧠 mulling over the details…
   ↓ (3s)
🪄 sketching out the plan…
   ↓ (3s)
🧩 piecing together the loose ends…
   ↓
(final answer)
```

## Why this exists

nanobot streams `$ command` tool hints and (optionally) progress text into the
chat. That is useful but noisy if all you want is a sense that work is
happening. This plugin turns that into a single, calm status bubble and leaves
the chat showing only the rotating sentence and the final answer.

Set `channels.sendToolHints: false` in `~/.nanobot/config.json` to hide the
`$ command` echoes; this plugin provides the "still working" signal instead.

## Install

nanobot usually runs as a [`uv` tool](https://docs.astral.sh/uv/concepts/tools/),
in its **own** Python environment. For the entry point to resolve, the plugin
must be installed *into that environment* — installing it into your own
project venv will not be picked up by the running `nanobot`.

```bash
# Add the plugin to the existing nanobot tool environment (recommended)
uv pip install --python "$(uv tool dir)/nanobot-ai/bin/python" nanobot-live-status

# Or recreate the tool with the plugin included
uv tool install nanobot-ai --with nanobot-live-status --force
```

`pipx` has an explicit inject command:

```bash
pipx inject nanobot-ai nanobot-live-status
```

To install from a local checkout instead of PyPI, point the commands at the
repository path:

```bash
uv pip install --python "$(uv tool dir)/nanobot-ai/bin/python" /path/to/apollo-pack/plugins/nanobot-live-status
```

Verify it loaded (the tool env's `bin` is often not on `PATH`):

```bash
"$(uv tool dir)/nanobot-ai/bin/nanobot-live-status" doctor
```

You should see `live_status registered: yes`. Then restart the gateway
(`/restart` in chat) so the channel re-reads config.

## Configuration

Read from nanobot's `~/.nanobot/config.json`:

```json
{
  "channels": {
    "sendToolHints": false,
    "telegram": { "enabled": true, "token": "123456:ABC…", "streaming": true }
  }
}
```

Optional environment overrides (set in the gateway's environment):

| Variable | Default | Meaning |
| --- | --- | --- |
| `NANOBOT_LIVE_STATUS_DISABLED` | unset | `1`/`true` disables the plugin |
| `NANOBOT_LIVE_STATUS_TOKEN` | from config | Bot token override (mainly for tests) |
| `NANOBOT_LIVE_STATUS_INTERVAL` | `3` | Seconds between edits (clamped to 1–60) |
| `NANOBOT_LIVE_STATUS_PHRASES` | built-in deck | Custom phrases, `\|`-separated |
| `NANOBOT_LIVE_STATUS_KEEP` | unset | `1`/`true` keeps the last phrase instead of deleting |

The token is only ever read from config or the environment. It is never logged
or printed.

## How it works

- The only external extension surface nanobot exposes is the
  `nanobot.tools` entry-point group, which requires a registered `Tool`.
- `LiveStatusTool.create(ctx)` runs **once, at loop construction, before any
  turn**, and receives `ToolContext.bus`. It subscribes to `SessionTurnStarted`
  and `TurnCompleted`, so the very first turn after a restart already shows the
  status.
- On `SessionTurnStarted` (Telegram only) it sends one message; an asyncio
  ticker edits it with the next phrase; on `TurnCompleted` it stops and deletes.
- `_scopes = {"core"}` keeps it out of subagent registries, so it is registered
  exactly once.
- All nanobot internals imports are guarded; a drifted host makes the plugin
  log once and no-op instead of crashing.

### The dummy-tool tradeoff

Because `nanobot.tools` is the only external seam, the plugin must register a
tool. That tool — `live_status` — is intentionally **internal and
non-callable**: its description says "do not call", it declares no parameters,
and `execute()` is a no-op. All real behavior happens in `create()`, before any
turn. If upstream adds a `nanobot.hooks` entry-point group, this can become a
zero-cost hook with no behavior change.

## Compatibility

- `nanobot-ai >= 0.3.5, < 0.4` (pinned; internals are semi-private and may drift
  within a major line — the plugin fails soft if they do).
- Python 3.11+.
- Telegram only; other channels are ignored.
- Reuses `httpx` (already a nanobot dependency) for the Bot API.

## Development

```bash
uv venv .venv --python 3.14
uv pip install -e ".[dev]" --python .venv
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/mypy
python -m build && twine check dist/*
```

## License

MIT. See [LICENSE](LICENSE). Security notes in [SECURITY.md](SECURITY.md).

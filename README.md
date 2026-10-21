# artifact-to-hex

A Claude Code skill that turns a Claude artifact (an HTML dashboard built in chat from Snowflake MCP
queries) into a live Hex generative app, then proves it matches.

## What it does

1. Finds the artifact in the conversation and the Snowflake queries that produced its data.
2. Rebuilds each embedded dataset as a Hex SQL cell and checks the rows match the artifact's numbers.
3. Hand-writes the generative app (React, no Hex agent), tests its logic in node with real data, and
   pushes it with the hex CLI.
4. Runs the notebook, screenshots the Hex app next to the artifact in your Chrome, exercises every
   control, and fixes differences until they match.
5. Reports parity and asks before publishing.

## Install

```bash
git clone https://github.com/finn-mcswiggan/artifact-to-hex ~/.claude/skills/artifact-to-hex
pip install pyyaml jinja2 snowflake-connector-python
```

Claude Code picks the skill up from `~/.claude/skills/` in new sessions.

## Use it

In a chat that contains the artifact: "put this artifact in Hex", "migrate this dashboard to a Hex app",
or `/artifact-to-hex`.

## Requirements

- hex CLI, logged in (`hex auth login`), with a Snowflake data connection in the workspace
- Python 3 with `pyyaml`, `jinja2`, `snowflake-connector-python`, and a connection in
  `~/.snowflake/connections.toml` (or the Snowflake MCP as a fallback)
- Node 18+ for the logic harness
- Claude in Chrome, signed in to Hex and claude.ai, for the UI checks

## Safety

The skill contains no credentials and no connection details. It acts only through the logins on the
machine running it: your `hex` CLI login and your `~/.snowflake/connections.toml`. So:

- **Before anything is created, it shows you the Hex workspace and Snowflake account it will use and asks
  you to confirm.** `init` won't run without `--confirm-workspace <id>` matching the active Hex login.
- **Each migration is pinned to the confirmed workspace**: `push` and `run` refuse if the active
  `hex` login changes mid-way.
- **Optional blocklist**: if this machine also has an employer's or client's logins, list the ones the
  skill must never touch in `~/.artifact2hex/config.json` (stays on your machine):

  ```json
  {
    "blocked_hex_workspaces": ["<hex workspace id>"],
    "blocked_snowflake_accounts": ["<ORG-ACCOUNT or account locator>"]
  }
  ```

  Find the values with `python3 scripts/hexgen.py whoami` and `python3 scripts/sfquery.py --whoami`.
  The file lives in your home folder, outside this repo and the installed skill, so it is never committed
  (`.gitignore` also excludes it, and every other file a migration writes, as a backstop).
  Better still, keep separate logins: a dedicated `hex` profile (`hex auth login <profile>`,
  `hex auth switch <profile>`) and a dedicated Snowflake connection name (`SNOWFLAKE_CONNECTION=<name>`).

## Layout

```
SKILL.md                         workflow
references/hex-genapp-runtime.md runtime API, YAML format, CLI gotchas, data limits
references/porting.md            artifact → Hex mapping
references/verification.md       parity checks, fix loop, report, publishing
scripts/hexgen.py                init / push / run / status
scripts/sfquery.py               run cell SQL against Snowflake (Jinja params)
scripts/compare.py               diff row sets
scripts/harness/                 node harness for app logic
assets/base-tokens.css           fallback theme tokens (normally copied from your workspace)
```

Work happens in `~/.artifact2hex/<slug>/`, so a migration can be resumed.

Related: Hex's own `import-claude-dashboard-from-url` (Hex MCP) rebuilds Claude Design dashboard exports
with the Hex agent. This skill is for chat artifacts and builds the app directly for exact parity.

---
name: artifact-to-hex
description: Migrate a Claude artifact (an HTML dashboard/prototype built in chat from Snowflake MCP query results) into a live Hex generative app, end to end - rebuilds the data as Snowflake SQL cells, hand-writes the generative app code (React, no Hex agent) and pushes it with the hex CLI, then proves parity by checking the numbers against the artifact, testing the app logic, screenshotting both UIs, and finally asks before publishing. Use whenever someone wants an artifact, prototype, or "this dashboard/page/visualisation" from the conversation turned into, moved to, rebuilt in, or shipped as a Hex app or Hex dashboard, including "put this in Hex", "productionise this artifact", "make this live in Hex", or "/artifact-to-hex", even if they don't say "migrate".
---

# Claude artifact → Hex generative app

Turn an artifact from this conversation into a Hex generative app whose data is live from Snowflake, that
looks and behaves like the artifact, and whose numbers are proven to match. The user should be able to
call this with one message. Work autonomously and only stop for the decisions listed under **Stops**.

The artifact is a frozen snapshot: its data was pasted in from Snowflake MCP queries run earlier in the
chat. The Hex app replaces that snapshot with SQL cells, so the queries in the conversation are as
important as the HTML.

Bundled resources (paths relative to this skill's folder):

- `scripts/hexgen.py`: create the workdir, build the project YAML, import it, repair data connections, run the notebook
- `scripts/sfquery.py`: run a cell's SQL (with Jinja params) against Snowflake, save rows, print size
- `scripts/compare.py`: diff two row sets; exits non-zero on any difference
- `scripts/harness/prepare.py` + `walk.mjs`: run the app code in node with real data to test its logic
- `assets/base-tokens.css`: fallback theme tokens; `init` normally copies the real ones from a generative app in the user's workspace
- `references/hex-genapp-runtime.md`: the runtime API, YAML format, CLI gotchas, data limits. **Read before writing app code.**
- `references/porting.md`: how artifact pieces map to Hex pieces. **Read before Phase 1.**
- `references/verification.md`: the four parity checks, fix loop, report and publish steps. **Read before Phase 4.**

## Stops (the only times to ask the user)

0. **Always, before anything is created: confirm where it will run.** Show the user the output of
   `hexgen.py whoami` (Hex user + workspace) and `sfquery.py --whoami` (Snowflake account, user, role)
   and ask "Build here?". Hex and Snowflake access come from whatever logins are active on this machine,
   which may be an employer's. Never assume; a wrong answer here puts someone's data in the wrong place.
1. More than one candidate artifact in the conversation, or more than one Snowflake connection in Hex and
   no way to tell which one the artifact used.
2. A blocker you cannot work around (hex CLI not authenticated, no Snowflake access, the queries can't be
   found or rebuilt). Say exactly what is missing.
3. **Publishing**: always ask, after the parity report. Never publish without a clear yes.

Everything else (naming, cell design, layout decisions, fix rounds) you decide, and explain in the report.

## Progress checklist

```
- [ ] Phase 0: Preflight and workdir
- [ ] Phase 1: Inventory the artifact and recover its queries
- [ ] Phase 2: Build and prove the SQL cells
- [ ] Phase 3: Write the app, test its logic, push to Hex
- [ ] Phase 4: Verify in Hex (cells, UI, interactions), fix until parity
- [ ] Phase 5: Parity report, ask to publish
```

## Phase 0: Preflight and workdir

1. **Find the artifact.** It's in this conversation: a claude.ai artifact URL (read its HTML with the
   Artifact tool, `action: "read"`) or an HTML file written earlier in the session. If the user named
   one, use it.
2. **Hex CLI**: `hex --version`, then `python3 <skill>/scripts/hexgen.py whoami`. If not logged in, ask the
   user to run `hex auth login` (a browser login you cannot do for them). If they have several profiles,
   `hex auth switch <profile>` selects one.
3. **Snowflake connection in Hex**: `hex connection list --json`. Pick the Snowflake connection that
   matches the database the artifact queried (ask only if ambiguous).
4. **Local Snowflake access** for validation: `scripts/sfquery.py` uses the Python connector and
   `~/.snowflake/connections.toml` (`--connection NAME` or `$SNOWFLAKE_CONNECTION`). If that's
   unavailable, use the Snowflake MCP `run_snowflake_query` tool for checks and save results to JSON.
   Needs `pip install pyyaml jinja2 snowflake-connector-python` if missing. Run
   `sfquery.py --whoami` to see which account it will query.
   **Confirm the target now (Stop 0)** with both identities on screen. After the yes, pass
   `--expect-account <account>` to every `sfquery.py` call so a changed login can't slip in.
5. **Browser**: Claude in Chrome tools (`mcp__claude-in-chrome__*`) for the UI checks; the user must be
   signed in to Hex there. If Chrome isn't available, say the UI check will be skipped and continue.
6. **Workdir**: `~/.artifact2hex/<artifact-slug>/` (survives restarts). Create the project and skeleton:
   ```
   python3 <skill>/scripts/hexgen.py init <workdir> --title "<App name>" --connection <connection-id> \
       --confirm-workspace <workspace id the user approved>
   ```
   The workdir is pinned to that workspace: `push`/`run`/`status` refuse if the active hex login changes.
   (or `--project <id>` to reuse an existing project). It writes `hexgen.json` (project, connection,
   cell list), `app/app.css` (Hex tokens) and `app/componentValues.json`. Keep notes, specs and
   screenshots in the workdir too. If resuming, read `hexgen.json` and `state.json` first.

## Phase 1: Inventory the artifact and recover its queries

Follow `references/porting.md` §1–2. Output in the workdir:

- `spec.md`: sections, copy, charts, colours, controls, derived formulas, in page order;
- `expected/<dataset>.json`: each embedded dataset flattened to rows (the numbers to reproduce);
- `queries.md`: for each dataset, the Snowflake query from the conversation plus any post-processing;
- baseline screenshots of the artifact (default state and each control state), if Chrome is available.

The conversation history is the source of truth for the queries: search it for `run_snowflake_query`
calls and for scripts that reshaped the results. When something is ambiguous, prefer what the artifact
actually shows.

## Phase 2: Build and prove the SQL cells

1. Write one SQL file per dataset in `sql/` and register it in `hexgen.json` `cells` (order = notebook order):
   ```json
   {"name": "orders", "label": "Orders by account and month", "type": "sql", "var": "orders"}
   {"name": "selected_account", "label": "Selected account", "type": "input",
    "input": {"name": "selected_account", "default": "acme-001", "outputType": "STRING"}}
   ```
2. Run each: `sfquery.py sql/<name>.sql -o out/<name>.json [--param k=v]`. Check the size it prints
   against the budget (runtime ref §6); over budget → aggregate, pack, or filter with an input cell.
3. Prove each: `compare.py expected/<name>.json out/<name>.json --key <grain>`. Fix or explain every
   difference before moving on. Data refreshed since the artifact was built is a valid explanation, but
   check it (compare at the artifact's date range).

## Phase 3: Write the app, test its logic, push to Hex

1. Read `references/hex-genapp-runtime.md`. Write `app/App.js`, `app/views/*.js`, `app/components/*.js`,
   `app/lib/*.js` and extend `app/app.css` per `references/porting.md` §4. Plain ES modules, `React.createElement`,
   `app/...` imports, cells referenced as `"__CELL:<name>__"`.
2. Test the logic before touching Hex: `harness/prepare.py` with the `out/` fixtures, then a `check.mjs`
   that asserts the values the artifact displays and exercises every control (verification ref §2). Fix
   until it passes.
3. Push: `python3 <skill>/scripts/hexgen.py push <workdir>`. It builds `import.yaml`, imports it, repairs
   any SQL cell the import left without a data connection, and verifies cells and app files landed. A
   non-zero exit means something didn't land; read its PROBLEMS list.
4. Kernel and run: `hex project open <project_id>` (once per project; cells can't run without it), then
   `python3 <skill>/scripts/hexgen.py run <workdir>`.

## Phase 4: Verify in Hex, fix until parity

Follow `references/verification.md` §3–5: cell row counts match local runs; screenshots of the Hex app
(draft → **App builder**) against the artifact for every state; every control exercised, including
selection changes that re-run SQL (data must arrive, not hang on "Loading…"). Batch fixes per round,
`push`, `run`, re-screenshot. Verify each fix in pixels, never assume it landed.

## Phase 5: Parity report, ask to publish

Report using verification ref §6 (link, numbers, logic, UI, interactions, open risks), then ask
**Publish now / Not yet**. On yes, click **Publish changes** in the Hex editor via Chrome, re-test the
published app (`/app/<slug>/latest`), and share its link. Publishing shares the app with everyone who
can see the project, so flag any personal data (usernames, emails) the app shows before asking.

## Why the build is hand-written

The Hex agent can rebuild apps from prompts, but it can "simplify" queries, costs AI credits, and is
hard to steer to exact parity. Writing the files directly makes the build deterministic and diffable,
and the harness can test it before Hex ever runs it. Use the Hex agent only if the user asks for it.

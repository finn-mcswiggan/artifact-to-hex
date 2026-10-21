# Verifying parity: numbers, logic, UI, interactions

Parity is proven in four layers. Each catches problems the others miss, so run all four every round.

## Contents
1. Numbers: SQL cells vs the artifact's data
2. Logic: the app code vs the artifact's displayed values (node harness)
3. Hex: cells run and deliver all rows
4. UI and interactions: screenshots of both, side by side
5. Fix loop
6. Parity report and publishing

## 1. Numbers: SQL cells vs the artifact's data

For every cell: `sfquery.py sql/<name>.sql -o out/<name>.json [--param k=v]`, then
`compare.py expected/<name>.json out/<name>.json --key <grain columns>`. Zero differences, or each
difference explained in the report (data refreshed since the artifact was built, deliberate scope change).
For input-filtered cells, compare at the artifact's original selection and spot-check one other value.

## 2. Logic: the app code vs the artifact's displayed values

```
python3 scripts/harness/prepare.py <workdir> <workdir>/harness \
  --fixture <cell>=out/<cell>.json ... --input <input_name>=<default>
```

Write `<workdir>/harness/check.mjs`: render each view with `renderText` and `expectText` the values the
artifact shows (KPI tiles, labels, table cells, chart tooltips you can read off the page). Also test:

- every control option renders without errors (`HEX_UI`, `HEX_INPUTS`, `HEX_STATE` overrides);
- staged rows (`globalThis.HEX_PARTIAL = { cell: 1 }`) show a loading state, never a partial result;
- empty selections render an empty state, not a crash;
- a loop over every value of each selector (e.g. every account) renders with zero errors.

Use fixtures pulled at the same time as the artifact comparison so the expected numbers line up.

## 3. Hex: cells run and deliver all rows

After `hexgen.py push`: open the project once (`hex project open <id>`) so a kernel exists, then
`hexgen.py run <workdir>`. For each SQL cell, `get_cell_output` (Hex MCP) must show `totalRows` equal to
the local `sfquery.py` row count. A fast failure with no detail means a missing data connection or no
kernel (hex-genapp-runtime.md §5).

## 4. UI and interactions: screenshots of both, side by side

Use Claude in Chrome (the user's signed-in browser; Hex and claude.ai both need sign-in). Load the
chrome-browser skill first if it is available. Work in a new tab.

**Artifact side**: open the artifact URL (claude.ai/artifact/...) or the local HTML file. Screenshot the
default state, then each control state, scrolling to cover the full page.

**Hex side**: open `https://app.hex.tech/<org>/hex/<project-slug>/draft/app`, click **App builder** in
the top bar, wait ~6 s for the iframe to render. (The `/draft/app` page without App builder shows the
classic layout; `/app/<id>/latest` only works after publishing.) Page-text tools cannot read inside the
app iframe, so verify with screenshots and `zoom`. Screenshot the same states as the artifact.

Compare each pair section by section:

- titles, copy, labels, number formats, ordering;
- chart type, scale, series, colours, legend, tooltip contents (hover);
- values shown (KPI tiles, table cells, axis ticks) against the artifact and the harness output;
- control behaviour: change every control in Hex and confirm the view changes the same way it does in
  the artifact. For input-driven cells, confirm the new data **arrives** (row-count line updates, no
  endless dimmed or "Loading…" state after ~20 s);
- light and dark theme readability (switch the Hex theme if the artifact supports both).

## 5. Fix loop

Batch every discrepancy found in a round, fix them in the workdir, `hexgen.py push`, re-run the harness,
`hexgen.py run`, re-screenshot. Never assume a fix landed: verify it in pixels. Stop when a round finds
nothing, or only differences that are explained and accepted (data drift, things that do not port).
Expect two or three rounds.

## 6. Parity report and publishing

Report to the user, in this order:

1. Hex project link (draft) and what was built (cells, app files).
2. Numbers: per cell, rows and `compare.py` result; explain any drift.
3. Logic: harness checks passed / failed.
4. UI: what matched, what differs and why (with the screenshot pairs if useful).
5. Interactions tested, including selection changes and how long data took to arrive.
6. Open risks (personal data shown, things that did not port, the input re-run issue if seen).

Then ask with AskUserQuestion: **Publish now / Not yet**. Publishing makes the app visible to everyone
the project is shared with, so never publish without a clear yes in this conversation. On yes: in the Hex
editor, click **Publish changes** (top right), confirm, then open the published app
(`/app/<slug>/latest`) and repeat the interaction checks from §4. A published app can behave
differently from the draft, so check it again rather than assuming. Report the published link.

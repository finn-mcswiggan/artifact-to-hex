# Porting a Claude artifact to a Hex generative app

A Claude artifact built from Snowflake MCP data is a single HTML page: its data is frozen into the page
(usually a `const DATA = {...}` JSON blob), its charts are drawn by a CDN library or hand-written SVG, and
its controls change what is drawn. The Hex version must get the same data **live from SQL cells**, draw
the same things, and behave the same way.

## Contents
1. Inventory the artifact
2. Recover the queries
3. Design the SQL cells
4. Translate the page
5. Things that do not port

## 1. Inventory the artifact

Read the whole artifact source (the Artifact tool's `read` action returns the HTML for the owner's
artifacts; a local file from this session works too). Write `spec.md` in the workdir with:

- **Sections** in page order: titles, subtitles, body copy (verbatim), KPI tiles, charts, tables, notes.
- **Charts**: type, series, axes and scale (fixed or dynamic), colours (hex values and which token they
  come from), legend, tooltips, animation, click behaviour.
- **Controls**: every select, toggle, slider, search box, play button; their options and defaults; what
  each one changes.
- **Embedded datasets**: every JSON blob or array literal, its shape (keys, nesting), row count, and which
  sections read it. Save each one to `expected/<name>.json` flattened to rows; these are the numbers the
  Hex app must reproduce.
- **Derived numbers**: anything the page computes in JS (averages, indices, labels, rankings, thresholds).
  Copy the exact formulas into the spec; they become `lib/` functions.
- **Baseline screenshots** of the artifact in its default state and after each control change.

## 2. Recover the queries

The artifact rarely contains SQL, but the conversation that built it does. Search the chat for the
Snowflake MCP calls (`run_snowflake_query` statements) and any local scripts that produced each dataset,
including Python/JS post-processing between the query and the embed (pivots, rounding, ratios, renamed
keys). For each embedded dataset, record: the query, the post-processing, and where the output landed.

Then make each one a single SQL statement for a Hex cell:

- Fold post-processing into SQL where reasonable (pivots → conditional aggregates, ratios, rounding).
  Leave genuinely presentational maths (index = a / b, labels, sorting) in `lib/` so it matches the
  artifact's JS exactly.
- Replace hard-coded scope (`WHERE company_id = 'abc'`, date literals) with input cells or relative dates
  when the Hex app should cover more than the artifact did, but keep the artifact's scope as the default
  so the first comparison is like-for-like.
- If no query can be found, rebuild it from the schema and prove it with the numbers (step 3 below).
  Say so in the final report.

## 3. Design the SQL cells

- One SQL cell per dataset the app reads; name cells for what they hold (`orders`, `region_totals`).
- Return columns already shaped for the app (UPPERCASE names, one row per thing the UI iterates over).
- Run each with `scripts/sfquery.py` and check the size it prints against the budget in
  hex-genapp-runtime.md §6. Over budget → aggregate, pack, or filter with an input cell.
- Prove each cell: `scripts/compare.py expected/<name>.json out/<name>.json --key ...`. Every difference
  must be explained (data refreshed since the artifact was made, a deliberate scope change) or fixed
  before any UI work. Data drift is normal; check the artifact's date range and compare like with like.

## 4. Translate the page

| Artifact | Hex generative app |
|---|---|
| `const DATA = {...}` | `useHexData("__CELL:name__")` + a `lib/model.js` that turns rows into the same shape the artifact's JS expected, so the drawing code ports almost unchanged |
| Inline `<script>` logic | Pure functions in `lib/` (formulas copied verbatim) + view components |
| DOM building (`innerHTML`, `appendChild`) | `React.createElement` trees (`var h = React.createElement;`) |
| Chart.js / other CDN chart | Hand-written SVG components or `d3` from `app/_data.js`; match chart type, scale, colours, labels and tooltips |
| `<select>`, buttons, `<input type=range>` | The same native elements in React; keep option labels and defaults identical |
| Search box over a long list | A combobox: text input + a filtered list the user can click / arrow through. A plain `<select>` beside a search input does not show results and reads as broken |
| `localStorage` preferences | `useHexUiState(key, default)` |
| Selection that changes which data loads | An INPUT cell + `setHexInput` + Jinja in the SQL (hex-genapp-runtime.md §3) |
| CSS tokens + dark mode media queries | `app.css` started by `hexgen.py init` (theme tokens from the workspace); redefine tokens under `:root[data-theme="dark"]` |
| Google Fonts link | Hex already loads IBM Plex Sans/Mono (`--font-body`, `--font-mono`); match sizes and weights |
| Play / animate button | `setInterval` in a `useEffect`; tween values with `requestAnimationFrame`; respect `prefers-reduced-motion` |

Guidelines:

- Keep the artifact's copy, labels, number formats, and ordering verbatim unless the user asked for changes.
- Every loading/empty/error state needs explicit UI: "Loading…", "No data for X", "Query failed".
- Guard staged rows (hex-genapp-runtime.md §2) before building anything from a cell.
- Show a small "data loaded" line (row counts per cell) while verifying; it makes Hex-side problems
  visible in screenshots. Remove or tuck it into a details panel before publishing.
- Write the app with cell placeholders (`"__CELL:orders__"`); `hexgen.py push` substitutes static ids.

## 5. Things that do not port

- `window.claude.*` runtime capabilities (shared storage, asking Claude). Replace with Hex inputs or drop,
  and say so.
- Per-viewer browser storage semantics: `useHexUiState` is the nearest equivalent.
- Static snapshots: the artifact froze data on the day it was built; the Hex app is live. Expect drift and
  explain it in the report rather than forcing old numbers.
- Personal data: anything rendered in the app is visible to everyone the app is shared with. Flag
  usernames, emails and other personal fields to the user before publishing.

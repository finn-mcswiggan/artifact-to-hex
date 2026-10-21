# Hex generative apps: runtime, project YAML and CLI facts

Everything here was confirmed against hex CLI 1.2026.08–09 and live Hex projects. Where something is
inferred rather than confirmed, it says so.

## Contents
1. What a generative app is
2. Runtime module `app/_data.js`
3. Input cells and app-driven SQL
4. Project YAML (export/import)
5. CLI behaviour and gotchas
6. Data delivery limits
7. Theme and CSS

## 1. What a generative app is

A React app that Hex renders in an iframe ("App builder" tab of the project). Its source lives in the
project YAML under `genAppFiles` as `{path, contents}` pairs. Conventional layout, matching what the Hex
agent generates:

```
App.js                 entry point; must call render(h(App))
app.css                theme tokens + styles (imported by App.js as "app/app.css")
componentValues.json   {"byType": {}, "byInstance": {}}  (edit-panel overrides; keep it present)
views/*.js             one module per page/tab
components/*.js        reusable pieces (charts, pickers, tables)
lib/*.js               data shaping, formatting, constants
```

Files import each other with absolute `app/...` paths: `import { Radar } from "app/components/Radar.js";`
Write plain ES modules with `var h = React.createElement;`. **No JSX** (there is no build step).
No npm packages. External CDN scripts are untested; prefer the runtime's `d3` or hand-written SVG.

## 2. Runtime module `app/_data.js`

Names seen across 25 Hex-generated apps in a production workspace:

| Export | Use |
|---|---|
| `React` | React itself (`useState`, `useMemo`, `useEffect`, `useRef`, ...) |
| `render(element)` | mount the app; call once at the end of `App.js` |
| `useHexData(staticCellId)` | `{ rows, status, hasData, isEmpty, rowCount }` for a SQL cell listed in `dataAppCellIds` |
| `useHexInput(inputCellId)` | `{ currentValue, options, ... }` for an INPUT cell (`options.valueOptions` holds dropdown options) |
| `setHexInput(inputCellId, value)` | set the input; SQL cells that reference it re-run |
| `useHexUiState(key, default)` | `[value, setValue]` persisted per viewer (selected tab, toggles) |
| `useHexConfig()` | app config object (rarely needed) |
| `d3`, `dateFns`, `LucideIcons` | libraries |
| `BaseSelect`, `BaseCombobox`, `BaseTabs`, `BaseSwitch`, `BaseTooltip`, `BasePopover`, `DayPicker` | headless UI primitives (APIs undocumented; plain HTML elements are safer) |
| `ChartShell`, `ComponentChrome`, `useComponentValues`, `useEditEmitter`, `useChartSubregionEditState` | edit-panel integration used by Hex-generated chart components; not needed for hand-written apps |

`useHexData` details that matter:

- `rows` is an array of objects keyed by the SQL column names, which Snowflake returns UPPERCASE.
  Numbers often arrive as strings ("1.5"). Convert explicitly with `Number()`.
- `status` is `RUNNING` / `QUEUED` while the cell (re-)runs, `COMPLETED` when done, `ERRORED` on failure.
- **Rows can arrive in stages while a cell re-runs.** An app that memoised on the first rows it saw showed
  only a handful of the hundreds of rows its cells returned. Only use a cell's rows when it is not RUNNING/QUEUED and
  `rows.length >= rowCount`, and include `rows.length` in `useMemo` dependencies. Show a loading state
  meanwhile. (Cause inferred from the symptoms; the guard fixed them.)
- `useHexData` uses the cell's **static id** (the YAML `cellId`), not the per-version id from `hex cell list`.

## 3. Input cells and app-driven SQL

Use this when a dataset is too big to ship whole (see §6), e.g. per-account detail.

YAML for the input cell:

```yaml
- cellType: INPUT
  cellId: <uuid7>
  cellLabel: Selected account
  config:
    inputType: DROPDOWN          # also MULTISELECT, DATE, ...
    name: selected_account        # the Jinja variable name
    outputType: STRING            # NUMBER, LIST_STRING, DATETIME, ...
    options: { valueOptions: ["acme-001"], optional: false }
    defaultValue: "acme-001"
```

SQL references it as a bound parameter, no quotes: `WHERE account_id = {{ selected_account }}`.
Lists use `{{ name | array }}` (e.g. `col IN ({{ segs | array }})`). Jinja `{% if %}` blocks work.

App side:

```js
var input = useHexInput("__CELL:selected_account__");
var current = input && input.currentValue;
setHexInput("__CELL:selected_account__", newId);   // dependent SQL re-runs
```

- Put the input cell id in `dataAppCellIds` (hexgen.py does this for every SQL and INPUT cell).
- Values outside `valueOptions` are accepted, so the option list does not need to enumerate every value;
  feed the picker from its own unfiltered SQL cell.
- Have the filtered cell echo the parameter back as a column (`{{ selected_account }} AS ACCOUNT_ID`) so the
  app can tell stale rows (previous selection) from fresh ones.
- **Open issue:** in one published app, choosing a new value left the app on "Loading…" (the dependent
  cell never reported fresh rows). Always test a selection change end to end in the browser, in both the
  draft App builder and after publishing. If it hangs, report it rather than claiming the app works.

## 4. Project YAML (export/import)

```
schemaVersion: 3
meta: { projectId, sourceVersionId, title, ... }   # DO NOT change projectId/sourceVersionId
sharedAssets: { dataConnections: [{ dataConnectionId: ... }], ... }
cells: [ ... ]                 # SQL / INPUT / MARKDOWN / CODE cells, in notebook order
appLayout: { ... }             # classic app layout; leave as exported
genAppFiles: [ { path, contents }, ... ]
dataAppCellIds: [ ... ]        # cells the generative app may read
```

SQL cell config keys: `source`, `dataConnectionId`, `resultVariableName`, `sqlCellOutputType: PANDAS`,
`castDecimals`, `useNativeDates`, `tableDisplayConfig`, ... (hexgen.py fills sensible defaults).

## 5. CLI behaviour and gotchas

- `hex project create "<title>" -d "<desc>" --json` → `{ id, ... }`.
- `hex project export <id> -o file.yaml` / `hex project import file.yaml`: import with the same
  `meta.projectId` **updates the project in place and keeps the YAML cellIds**. Cells missing from the
  YAML are removed.
- **Import can drop `dataConnectionId` on newly added SQL cells** (seen every time a new SQL cell was
  imported). Symptom: the cell fails in ~0.5 s with "The latest cell run failed, but no detailed error
  output was available". Fix: `hex cell update <cell-api-id> --data-connection-id <conn>`. hexgen.py
  `push` does this automatically and re-verifies.
- `hex cell list <project>` returns per-version cell ids that differ from the static YAML ids; use those
  ids for `hex cell update/run/delete`, and the static ids in app code.
- **Cells only run once the project has a kernel.** Open it in a browser once (`hex project open <id>`);
  before that, `hex project run` / `hex cell run` fail instantly with no detail.
- `hex project run <id>` (draft run) supports only `--no-cache` in these versions: no `-i` input overrides,
  no `--timeout`. Poll with `hex run status <project> <run> --json`.
- No CLI command publishes an app. Publishing is the **Publish changes** button in the Hex editor.
- The Hex MCP (`run_notebook`, `run_cell`, `get_cell_output`) is an alternative for running cells and
  reading the first 50 rows plus `totalRows` of a SQL cell.
- `hex project export` of other generative apps in the workspace is the best way to learn new runtime APIs.

## 6. Data delivery limits

The app receives every row of every cell it reads, up front. Budget per cell, measured as JSON
(`sfquery.py` prints `json_kb`):

- Comfortable: under ~500 KB and ~15,000 rows (Hex-agent apps routinely read 15k rows).
- Too big: an ~8 MB, 13k-row cell appeared to arrive only partly (inferred, not confirmed).
- When a dataset is over budget, either aggregate further in SQL, pack rows (one row per entity with a
  compact encoded string), or filter it with an input cell so only the current selection is sent.

## 7. Theme and CSS

Hex stamps `data-theme="light"|"dark"` on the root and follows the viewer's setting. `hexgen.py init`
starts `app.css` with the `:root` token blocks copied from a generative app already in the user's
workspace (`--css-from <project>` to choose one), so colours and fonts match Hex exactly; it falls back to
`assets/base-tokens.css` (same token names) when the workspace has none. Tokens include `--color-text`,
`--color-text-muted`, `--color-bg`, `--color-bg-muted`, `--color-border`, `--color-border-muted`,
`--font-body`, `--font-mono`, `--space-*`, `--radius`. Define app colours as tokens under both `:root`
and `:root[data-theme="dark"]`, and have charts read colours from these CSS variables so both themes work.

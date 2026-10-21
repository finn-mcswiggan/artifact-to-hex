#!/usr/bin/env python3
"""Build and push a hand-written Hex generative app with the hex CLI.

A workdir looks like:

    workdir/
      hexgen.json        # project id, connection id, cell list (see `init`)
      sql/<name>.sql     # one file per SQL cell
      app/               # the generative app source: App.js, app.css, views/, components/, lib/
      state.json         # written by this script: cell name -> static cell id

App code refers to cells by placeholder, e.g. useHexData("__CELL:orders__") or
useHexInput("__CELL:selected_account__"). `push` swaps placeholders for the real static ids.

Commands:
  init  <workdir> --project <id> --connection <id>   create workdir skeleton (base css, config)
  init  <workdir> --title "Name" --connection <id>   ...and create a new Hex project first
        [--css-from <project_id>]                      take theme tokens from this generative app
  push  <workdir> [--dry-run] [--allow-remove]       build YAML, import, repair connections, verify
                                                     (refuses to delete cells it didn't create unless --allow-remove)
  run   <workdir> [--timeout 900]                    run the draft notebook and wait for the result
  status <workdir>                                   show cells, connections and app files in Hex

Facts this script relies on (learned the hard way, hex CLI 1.2026.x):
  * `hex project import` with the same meta.projectId updates in place and keeps YAML cellIds
    (static ids, which useHexData/useHexInput use). `hex cell list` returns different, per-version ids.
  * Import can leave NEW SQL cells with dataConnectionId null. They then fail in ~0.5s with no error
    detail. `push` repairs this with `hex cell update --data-connection-id`.
  * Cells only run once the project has a kernel: open it in a browser once (`hex project open`).
"""
import argparse, copy, json, os, re, secrets, subprocess, sys, tempfile, time, uuid

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

HERE = os.path.dirname(os.path.abspath(__file__))
FALLBACK_CSS = os.path.join(HERE, "..", "assets", "base-tokens.css")
CHECK = os.path.join(tempfile.gettempdir(), "hexgen_check.yaml")
PLACEHOLDER = re.compile(r"__CELL:([A-Za-z0-9_\-]+)__")

SQL_CONFIG_DEFAULTS = {
    "dataFrameCell": False,
    "useRichDisplay": True,
    "enablePreview": True,
    "sqlCellOutputType": "PANDAS",
    "useQueryMode": False,
    "castDecimals": True,
    "useNativeDates": True,
    "outputFilteredResult": True,
    "allowDuplicateColumns": False,
    "tableDisplayConfig": {
        "pageSize": 50, "height": None, "hideIcons": False, "defaultColumnWidth": None, "hideIndex": False,
        "defaultSortColumn": None, "defaultSortIndexColumn": None, "defaultSortDirection": "ASC",
        "conditionalFormatting": None, "calcs": None, "filters": None, "columnProperties": [],
        "columnOrdering": None, "customColumnOrdering": None, "pinnedColumns": None, "hiddenColumns": None,
        "pinIndexColumns": False, "showAggregations": False, "columnAggregations": None,
    },
}


def sh(args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        sys.exit(f"command failed: {' '.join(args[:4])} ...\n{r.stdout}\n{r.stderr}")
    return r.stdout


def hex_json(args):
    out = sh(["hex"] + args + ["--json"])
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        sys.exit(f"unexpected hex output for {' '.join(args)}:\n{out[:800]}")


def uuid7():
    ms = int(time.time() * 1000)
    r = secrets.randbits(74)
    v = (ms << 80) | (0x7 << 76) | ((r >> 62) << 64) | (0b10 << 62) | (r & ((1 << 62) - 1))
    return str(uuid.UUID(int=v))


def load(wd, name, default=None):
    p = os.path.join(wd, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def save(wd, name, data):
    with open(os.path.join(wd, name), "w") as f:
        json.dump(data, f, indent=2)


def export(project_id, path):
    sh(["hex", "project", "export", project_id, "-o", path])
    with open(path) as f:
        return yaml.safe_load(f)


class Dumper(yaml.SafeDumper):
    pass


Dumper.add_representer(str, lambda d, s: d.represent_scalar("tag:yaml.org,2002:str", s, style="|" if "\n" in s else None))


# ---------------------------------------------------------------- init
ROOT_BLOCK = re.compile(r":root[^{]*\{[^}]*\}")


def tokens_from_project(project_id):
    """The :root token blocks (light + dark) of a generative app's app.css, or None."""
    try:
        d = export(project_id, CHECK)
    except SystemExit:
        return None
    css = next((f["contents"] for f in d.get("genAppFiles") or [] if f["path"] == "app.css"), None)
    blocks = ROOT_BLOCK.findall(css or "")
    return "\n\n".join(blocks) if any("dark" in b for b in blocks) else None


def workspace_tokens(explicit=None, scan=15):
    """Theme tokens copied from a generative app in the user's own workspace, so they match Hex exactly.

    Nothing Hex-authored ships with this skill; the tokens come from the user's workspace at init time.
    """
    if explicit:
        return tokens_from_project(explicit), explicit
    listed = hex_json(["project", "list", "-n", str(scan), "--sort-by", "last_edited_at", "--sort-direction", "desc"])
    for p in listed.get("projects", []):
        toks = tokens_from_project(p["id"])
        if toks:
            return toks, p["id"]
    return None, None


def base_css(explicit=None):
    with open(FALLBACK_CSS) as f:
        fallback = f.read()
    toks, source = workspace_tokens(explicit)
    if not toks:
        print("no generative app with theme tokens found in the workspace; using the bundled fallback tokens")
        return fallback
    print(f"theme tokens copied from your workspace project {source}")
    element_defaults = fallback[fallback.index("*, *::before"):]
    return ("/* Theme tokens copied from a generative app in this workspace (" + source + ") by hexgen.py init. */\n\n"
            + toks + "\n\n" + element_defaults)


def cmd_init(a):
    wd = a.workdir
    os.makedirs(os.path.join(wd, "sql"), exist_ok=True)
    os.makedirs(os.path.join(wd, "app"), exist_ok=True)
    project_id = a.project
    if not project_id:
        if not a.title:
            sys.exit("pass --project <id> or --title <name>")
        created = hex_json(["project", "create", a.title] + (["-d", a.description] if a.description else []))
        project_id = created["id"]
        print(f"created Hex project {project_id}")
    cfg = load(wd, "hexgen.json", {})
    cfg.update({"project_id": project_id, "connection_id": a.connection})
    cfg.setdefault("cells", [])
    save(wd, "hexgen.json", cfg)
    css = os.path.join(wd, "app", "app.css")
    if not os.path.exists(css):
        with open(css, "w") as f:
            f.write(base_css(a.css_from) + "\n\n/* ---- App styles ---- */\n")
    cv = os.path.join(wd, "app", "componentValues.json")
    if not os.path.exists(cv):
        with open(cv, "w") as f:
            f.write('{\n  "byType": {},\n  "byInstance": {}\n}\n')
    print(f"workdir ready: {wd}\nnext: add cells to hexgen.json, SQL to sql/, app code to app/, then `push`")


# ---------------------------------------------------------------- push
def build_cells(cfg, wd, state, existing):
    """Return YAML cells in config order, reusing static ids from state or the current export."""
    by_label = {c.get("cellLabel"): c for c in existing}
    cells = []
    for spec in cfg["cells"]:
        name = spec["name"]
        label = spec.get("label", name)
        cid = state.get(name) or (by_label.get(label) or {}).get("cellId") or uuid7()
        state[name] = cid
        time.sleep(0.002)  # keep generated uuid7s distinct and ordered
        if spec["type"] == "sql":
            src_path = os.path.join(wd, spec.get("sql", f"sql/{name}.sql"))
            with open(src_path) as f:
                src = f.read()
            cfg_ = copy.deepcopy(SQL_CONFIG_DEFAULTS)
            prev = by_label.get(label)
            if prev and prev.get("cellType") == "SQL":
                cfg_.update({k: v for k, v in prev["config"].items() if k != "source"})
            cfg_.update({"source": src, "resultVariableName": spec.get("var", name),
                         "dataConnectionId": spec.get("connection_id", cfg["connection_id"])})
            cells.append({"cellType": "SQL", "cellId": cid, "cellLabel": label, "config": cfg_})
        elif spec["type"] == "input":
            inp = spec["input"]
            conf = {
                "inputType": inp.get("inputType", "DROPDOWN"),
                "name": inp.get("name", name),
                "outputType": inp.get("outputType", "STRING"),
                "options": inp.get("options", {"valueOptions": [inp.get("default")], "optional": False}),
                "defaultValue": inp.get("default"),
            }
            cells.append({"cellType": "INPUT", "cellId": cid, "cellLabel": label, "config": conf})
        elif spec["type"] == "markdown":
            cells.append({"cellType": "MARKDOWN", "cellId": cid, "cellLabel": label,
                          "config": {"source": spec.get("text", "")}})
        else:
            sys.exit(f"unknown cell type {spec['type']} for {name}")
    return cells


def collect_app_files(wd, state):
    app = os.path.join(wd, "app")
    files, missing = [], set()
    for root, _, names in os.walk(app):
        for n in sorted(names):
            if n.startswith("."):
                continue
            p = os.path.join(root, n)
            rel = os.path.relpath(p, app).replace(os.sep, "/")
            with open(p) as f:
                txt = f.read()

            def sub(m):
                if m.group(1) not in state:
                    missing.add(m.group(1))
                    return m.group(0)
                return state[m.group(1)]

            files.append({"path": rel, "contents": PLACEHOLDER.sub(sub, txt)})
    if missing:
        sys.exit(f"app code references unknown cells: {sorted(missing)} (add them to hexgen.json)")
    if not any(f["path"] == "App.js" for f in files):
        sys.exit("app/App.js is missing: it is the generative app's entry point")
    files.sort(key=lambda f: (f["path"] != "App.js", f["path"]))
    return files


def repair_connections(cfg, project_id):
    """Set the data connection on SQL cells the import left without one."""
    d = export(project_id, CHECK)
    broken = [c["cellLabel"] for c in d["cells"] if c["cellType"] == "SQL" and not c["config"].get("dataConnectionId")]
    if not broken:
        return d, []
    listed = hex_json(["cell", "list", project_id, "-n", "100"]).get("cells", [])
    want = {s.get("label", s["name"]): s.get("connection_id", cfg["connection_id"]) for s in cfg["cells"]}
    fixed = []
    for c in listed:
        if c.get("label") in broken:
            sh(["hex", "cell", "update", c["id"], "--data-connection-id", want.get(c["label"], cfg["connection_id"]), "--json"])
            fixed.append(c["label"])
    return export(project_id, CHECK), fixed


def cmd_push(a):
    wd = a.workdir
    cfg = load(wd, "hexgen.json")
    if not cfg:
        sys.exit("no hexgen.json: run `init` first")
    pid = cfg["project_id"]
    state = load(wd, "state.json", {})
    base = export(pid, os.path.join(wd, ".base.yaml"))
    # Import replaces the notebook: any cell not in hexgen.json is deleted. Only allow that for cells this
    # workdir created (tracked in state.json) unless the user explicitly opts in.
    managed_ids = set(state.values())
    managed_labels = {s.get("label", s["name"]) for s in cfg["cells"]}
    unmanaged = [c.get("cellLabel") or c["cellId"] for c in base.get("cells") or []
                 if c["cellId"] not in managed_ids and c.get("cellLabel") not in managed_labels]
    if unmanaged and not a.allow_remove:
        sys.exit("refusing to push: these existing cells are not in hexgen.json and would be deleted:\n  "
                 + "\n  ".join(unmanaged) + "\nAdd them to hexgen.json, use a new project, or pass --allow-remove.")
    cells = build_cells(cfg, wd, state, base.get("cells") or [])
    files = collect_app_files(wd, state)
    base["cells"] = cells
    base["genAppFiles"] = files
    base["dataAppCellIds"] = [c["cellId"] for c in cells if c["cellType"] in ("SQL", "INPUT")]
    conns = sorted({c["config"]["dataConnectionId"] for c in cells if c["cellType"] == "SQL"})
    base.setdefault("sharedAssets", {})["dataConnections"] = [{"dataConnectionId": x} for x in conns]
    out = os.path.join(wd, "import.yaml")
    with open(out, "w") as f:
        yaml.dump(base, f, Dumper=Dumper, sort_keys=False, allow_unicode=True, width=10000)
    save(wd, "state.json", state)
    print(f"wrote {out}: {len(cells)} cells, {len(files)} app files")
    if a.dry_run:
        return
    res = hex_json(["project", "import", out])
    print(f"imported -> version {res.get('hexVersionId')}")
    after, fixed = repair_connections(cfg, pid)
    if fixed:
        print(f"repaired missing data connection on: {', '.join(fixed)}")
    # Verify what Hex now holds matches what we sent.
    got = {c["cellId"]: c for c in after["cells"]}
    problems = [f"cell {n} ({cid}) missing after import" for n, cid in state.items() if cid not in got and any(s['name'] == n for s in cfg['cells'])]
    problems += [f"SQL cell '{c['cellLabel']}' still has no data connection" for c in after["cells"]
                 if c["cellType"] == "SQL" and not c["config"].get("dataConnectionId")]
    sent = {f["path"]: f["contents"] for f in files}
    have = {f["path"]: f["contents"] for f in after.get("genAppFiles") or []}
    problems += [f"app file {p} differs after import" for p in sent if have.get(p) != sent[p]]
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("verified: cells, connections and app files match")


# ---------------------------------------------------------------- run
def cmd_run(a):
    cfg = load(a.workdir, "hexgen.json")
    pid = cfg["project_id"]
    started = hex_json(["project", "run", pid] + (["--no-cache"] if a.no_cache else []))
    rid = started.get("run_id") or started.get("runId")
    print(f"run {rid} started")
    t0 = time.time()
    while True:
        st = hex_json(["run", "status", pid, rid])
        s = st.get("status")
        if s not in ("RUNNING", "PENDING", "QUEUED"):
            break
        if time.time() - t0 > a.timeout:
            sys.exit(f"timed out after {a.timeout}s; last status {s}")
        time.sleep(4)
    print(json.dumps({k: st.get(k) for k in ("status", "start_time", "end_time", "elapsed_seconds")}))
    if s != "COMPLETED":
        print("Run did not complete. If it failed in under a second with no detail: open the project in a browser "
              "once (`hex project open <id>`) so a kernel starts, and check every SQL cell has a data connection.")
        sys.exit(1)


def cmd_status(a):
    cfg = load(a.workdir, "hexgen.json")
    d = export(cfg["project_id"], CHECK)
    for c in d["cells"]:
        extra = c["config"].get("dataConnectionId", c["config"].get("name"))
        print(f"{c['cellType']:9} {c['cellId']}  {c.get('cellLabel')}  [{extra}]")
    print("app files:", ", ".join(f["path"] for f in d.get("genAppFiles") or []) or "none")
    print("dataAppCellIds:", d.get("dataAppCellIds"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init"); i.add_argument("workdir"); i.add_argument("--project"); i.add_argument("--title")
    i.add_argument("--description"); i.add_argument("--connection", required=True)
    i.add_argument("--css-from", help="project id of a generative app to copy theme tokens from"); i.set_defaults(fn=cmd_init)
    q = sub.add_parser("push"); q.add_argument("workdir"); q.add_argument("--dry-run", action="store_true")
    q.add_argument("--allow-remove", action="store_true", help="allow deleting existing cells that are not in hexgen.json"); q.set_defaults(fn=cmd_push)
    r = sub.add_parser("run"); r.add_argument("workdir"); r.add_argument("--timeout", type=int, default=900)
    r.add_argument("--no-cache", action="store_true"); r.set_defaults(fn=cmd_run)
    s = sub.add_parser("status"); s.add_argument("workdir"); s.set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()

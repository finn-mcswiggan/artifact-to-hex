#!/usr/bin/env python3
"""Run a SQL file against Snowflake and save the rows as JSON (for validation and size budgeting).

  sfquery.py sql/orders.sql -o out/orders.json --param selected_account=acme-001

Hex SQL cells use Jinja ({{ param }}); --param values are bound the way Hex binds them (strings quoted,
numbers bare). Lists: --param segs='["A","B"]' renders as a SQL list for {{ segs | array }}.
Connection: --connection NAME, else $SNOWFLAKE_CONNECTION, else the default in ~/.snowflake/connections.toml.
Prints row count, columns and JSON size, which is what decides whether a cell needs an input filter.
"""
import argparse, datetime, decimal, json, os, re, sys


def literal(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, list):
        return ", ".join(literal(x) for x in v)
    return "'" + str(v).replace("'", "''") + "'"


def render(sql, params):
    try:
        import jinja2  # real Jinja handles {% if %} blocks the way Hex does

        class Raw(str):
            pass

        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
        env.filters["array"] = lambda v: Raw(literal(v if isinstance(v, list) else [v]))
        env.finalize = lambda v: v if isinstance(v, Raw) else literal(v)
        return env.from_string(sql).render(**params)
    except ImportError:
        if "{%" in sql:
            sys.exit("SQL has {% %} blocks: pip install jinja2 to render them faithfully")
        def sub(m):
            name, filt = m.group(1), m.group(2)
            if name not in params:
                sys.exit(f"missing --param {name}")
            return literal(params[name])
        return re.sub(r"\{\{\s*(\w+)\s*(\|\s*\w+\s*)?\}\}", sub, sql)


def parse_param(s):
    k, _, v = s.partition("=")
    try:
        v = json.loads(v)
    except json.JSONDecodeError:
        pass
    return k, v


def default(o):
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()
    return str(o)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sql_file"); p.add_argument("-o", "--out"); p.add_argument("--param", action="append", default=[])
    p.add_argument("--connection"); p.add_argument("--print-sql", action="store_true")
    a = p.parse_args()
    params = dict(parse_param(x) for x in a.param)
    sql = render(open(a.sql_file).read(), params)
    if a.print_sql:
        print(sql); return
    import snowflake.connector
    kw = {}
    name = a.connection or os.environ.get("SNOWFLAKE_CONNECTION")
    if name:
        kw["connection_name"] = name
    con = snowflake.connector.connect(**kw)
    cur = con.cursor(snowflake.connector.DictCursor)
    cur.execute(sql)
    rows = cur.fetchall()
    blob = json.dumps(rows, default=default)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        open(a.out, "w").write(blob)
    cols = list(rows[0].keys()) if rows else []
    print(json.dumps({"rows": len(rows), "columns": cols, "json_kb": round(len(blob) / 1024, 1), "out": a.out}))


if __name__ == "__main__":
    main()

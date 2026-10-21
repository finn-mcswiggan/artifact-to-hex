#!/usr/bin/env python3
"""Compare two row sets (JSON arrays of objects) and report every difference.

  compare.py expected.json actual.json --key ROLE,SKILL,MONTH [--cols PTS6,ACT6] [--tol 0.01] [--rel 0.001]

expected = what the artifact shows (its embedded data, or numbers read off the page),
actual   = what the Hex SQL cell returns. Column names match case-insensitively. Numeric values
match within --tol absolute or --rel relative difference; strings must match exactly after trimming.
Exit code 1 if anything differs, so it can gate the verification step.
"""
import argparse, json, sys


def norm(rows):
    return [{str(k).upper(): v for k, v in r.items()} for r in rows]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("expected"); p.add_argument("actual"); p.add_argument("--key", required=True)
    p.add_argument("--cols"); p.add_argument("--tol", type=float, default=0.01); p.add_argument("--rel", type=float, default=0.001)
    p.add_argument("--max-report", type=int, default=25)
    a = p.parse_args()
    exp, act = norm(json.load(open(a.expected))), norm(json.load(open(a.actual)))
    keys = [k.strip().upper() for k in a.key.split(",")]
    cols = [c.strip().upper() for c in a.cols.split(",")] if a.cols else sorted(set(exp[0]) - set(keys)) if exp else []
    def kf(r): return tuple(str(r.get(k)) for k in keys)
    E, A = {kf(r): r for r in exp}, {kf(r): r for r in act}
    issues = []
    for k in E.keys() - A.keys(): issues.append(f"missing in actual: {dict(zip(keys, k))}")
    for k in A.keys() - E.keys(): issues.append(f"extra in actual: {dict(zip(keys, k))}")
    checked = 0
    for k in E.keys() & A.keys():
        for c in cols:
            ev, av = E[k].get(c), A[k].get(c)
            en, an = num(ev), num(av)
            if en is not None and an is not None:
                ok = abs(en - an) <= a.tol or abs(en - an) <= a.rel * max(abs(en), abs(an))
            else:
                ok = str(ev).strip() == str(av).strip()
            checked += 1
            if not ok:
                issues.append(f"{dict(zip(keys, k))} {c}: expected {ev} got {av}")
    print(json.dumps({"expected_rows": len(E), "actual_rows": len(A), "values_checked": checked, "differences": len(issues)}))
    for line in issues[: a.max_report]:
        print("  " + line)
    if len(issues) > a.max_report:
        print(f"  ... and {len(issues) - a.max_report} more")
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()

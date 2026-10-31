"""Long-running soak test on synthetic data, meant to run in the background.

For every layout in SCHEMA.md and every seed, write N synthetic records, convert them
to SQLite, and check every value read back. Progress and any mismatch go to soak.log.

    python soak.py --schema tests/SCHEMA.md --records 10000 --seeds 20

Synthetic data only. Never point this, or the converter, at the ACC folder.
"""
import argparse
import os
import sqlite3
import tempfile
import time
import zlib
from decimal import Decimal

from dblconv.convert import convert
from dblconv.schema import parse_schema
from dblconv.synth import write_file


def check(layout, n, seed, workdir):
    data = os.path.join(workdir, "data.dat")
    db = os.path.join(workdir, "out.sqlite")
    if os.path.exists(db):
        os.remove(db)
    expected = write_file(data, layout, n, seed=seed)
    info = convert(data, layout, db, table="t")
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute('PRAGMA table_info("t")')][1:]
    problems = []
    for rec, (row, want) in enumerate(
            zip(con.execute('SELECT * FROM "t" ORDER BY _record'), expected), 1):
        got = dict(zip(cols, row[1:]))
        for name, v in want.items():
            g = got[name]
            ok = (Decimal(str(g)) == v) if isinstance(v, Decimal) else (g == v)
            if not ok:
                problems.append(f"record {rec} {name}: wrote {v!r}, read {g!r}")
    con.close()
    if info["records"] != n or info["field_errors"]:
        problems.append(f"converter reported {info}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=os.path.join("tests", "SCHEMA.md"))
    ap.add_argument("--records", type=int, default=10000)
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--log", default="soak.log")
    a = ap.parse_args()
    layouts = parse_schema(a.schema)
    start, failures = time.time(), 0
    with open(a.log, "w", encoding="utf-8") as log, tempfile.TemporaryDirectory() as wd:
        log.write(f"soak: {len(layouts)} layouts x {a.seeds} seeds x {a.records} records\n")
        for s in range(a.seeds):
            for lay in layouts:
                seed = zlib.crc32(f"{lay.key}/{s}".encode())
                problems = check(lay, a.records, seed, wd)
                if problems:
                    failures += 1
                    log.write(f"FAIL {lay.key} seed {seed}\n")
                    for p in problems[:20]:
                        log.write(f"    {p}\n")
            log.write(f"seed round {s + 1}/{a.seeds} done, {failures} failures, "
                      f"{time.time() - start:.0f} s\n")
            log.flush()
        log.write(f"FINISHED: {failures} failing layout runs in {time.time() - start:.0f} s\n")
    print(open(a.log, encoding="utf-8").read().splitlines()[-1])


if __name__ == "__main__":
    main()

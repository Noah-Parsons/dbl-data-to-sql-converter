"""Convert a fixed-record DBL data file into a SQLite table.

    python -m dblconv.convert --schema SCHEMA.md --layout ADRMS DATAFILE OUT.sqlite

Every field becomes a column (arrays become NAME_1 .. NAME_n). Decimal fields become
INTEGER columns when they have no implied decimals, and TEXT holding the exact decimal
string when they do, so that no cents are lost to floating point. Fields that cannot
be decoded are stored as NULL and listed, with the raw bytes, in _conversion_errors.
"""
import argparse
import os
import sqlite3
import sys

from .codec import DecodeError, decode_alpha, decode_decimal
from .schema import find_layout, parse_schema

TERMINATORS = [b"\r\n", b"\n", b""]


def detect_terminator(path, reclen):
    """Pick the record terminator that divides the file evenly into records whose
    terminators sit where they should. Raises ValueError if none fits."""
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        head = fh.read((reclen + 2) * 4)
    for term in TERMINATORS:
        step = reclen + len(term)
        if size == 0 or size % step:
            continue
        if term and any(head[i * step + reclen:(i + 1) * step] != term
                        for i in range(min(4, size // step))):
            continue
        return term
    raise ValueError(f"{path}: size {size} does not fit records of {reclen} bytes "
                     f"with CRLF, LF or no terminator")


def columns(layout):
    cols = []
    for f in layout.fields:
        if f.filler:
            continue
        sqltype = "TEXT" if f.kind == "A" or f.decimals else "INTEGER"
        names = [f.name] if f.count == 1 else [f"{f.name}_{i + 1}" for i in range(f.count)]
        for i, n in enumerate(names):
            cols.append((n, sqltype, f, i))
    return cols


def decode_record(rec, layout, cols):
    row, errors = [], []
    for name, _, f, i in cols:
        start = f.offset + i * f.width
        raw = rec[start:start + f.width]
        if f.kind == "A":
            row.append(decode_alpha(raw))
            continue
        try:
            v = decode_decimal(raw, f.decimals)
        except DecodeError as e:
            row.append(None)
            errors.append((name, raw, str(e)))
            continue
        if v is None:
            row.append(None)
        elif f.decimals:
            row.append(str(v))
        else:
            row.append(int(v))
    return row, errors


def is_empty_slot(rec):
    """Unused records in preallocated DBL files are filled with ']'."""
    return rec.strip(b"]") == b"" and rec != b""


def convert(path, layout, out, table=None, skip=0, keep_empty=False):
    reclen = layout.length
    term = detect_terminator(path, reclen)
    table = table or layout.name.replace(" ", "_")
    cols = columns(layout)
    db = sqlite3.connect(out)
    db.execute(f'DROP TABLE IF EXISTS "{table}"')
    db.execute(f'CREATE TABLE "{table}" ('
               + ", ".join(["_record INTEGER PRIMARY KEY"]
                           + [f'"{n}" {t}' for n, t, _, _ in cols]) + ")")
    db.execute("CREATE TABLE IF NOT EXISTS _conversion_errors "
               "(source TEXT, tbl TEXT, record INTEGER, field TEXT, raw BLOB, error TEXT)")
    marks = ", ".join("?" * (len(cols) + 1))
    step = reclen + len(term)
    n = bad = empty = 0
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(step)
            if not chunk:
                break
            n += 1
            if n <= skip:
                continue
            if not keep_empty and is_empty_slot(chunk[:reclen]):
                empty += 1
                continue
            row, errors = decode_record(chunk[:reclen], layout, cols)
            db.execute(f'INSERT INTO "{table}" VALUES ({marks})', [n] + row)
            for fld, raw, msg in errors:
                bad += 1
                db.execute("INSERT INTO _conversion_errors VALUES (?,?,?,?,?,?)",
                           (os.path.basename(path), table, n, fld, raw, msg))
    db.commit()
    db.close()
    return {"records": n - min(skip, n) - empty, "empty_slots": empty,
            "field_errors": bad,
            "terminator": term.decode() or "none", "record_length": reclen}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--schema", required=True, help="path to SCHEMA.md")
    ap.add_argument("--layout", required=True,
                    help="record name (ADRMS) or FILE:RECORD (APADJ.FD:APADJ)")
    ap.add_argument("--table", help="table name (default: the record name)")
    ap.add_argument("--skip", type=int, default=0,
                    help="records to skip first, e.g. 1 for a control record")
    ap.add_argument("--keep-empty", action="store_true",
                    help="also convert unused slots (records filled with ']')")
    ap.add_argument("datafile")
    ap.add_argument("out", help="SQLite database to create or add to")
    a = ap.parse_args(argv)
    layout = find_layout(parse_schema(a.schema), a.layout)
    for note in layout.notes:
        print("schema note:", note, file=sys.stderr)
    print(convert(a.datafile, layout, a.out, a.table, a.skip, a.keep_empty))


if __name__ == "__main__":
    main()

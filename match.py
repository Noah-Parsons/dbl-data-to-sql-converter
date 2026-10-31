"""Suggest which SCHEMA.md layouts fit each data file, by record length.

    python match.py --schema tests/SCHEMA.md DATAFILE [DATAFILE ...]

For each file, lists the layouts whose record length (with a CRLF, LF or no terminator)
divides the file exactly, with the terminators sitting where they should, and how many
fields of the first few records decode cleanly under each candidate.
"""
import argparse
import os

from dblconv.codec import DecodeError, decode_decimal
from dblconv.convert import detect_terminator
from dblconv.schema import parse_schema


def clean_fraction(path, layout, term, sample=200):
    """Decode the numeric fields of up to `sample` non-empty records after the first
    (which is often a control record), skipping unused slots filled with ']'."""
    step = layout.length + len(term)
    good = total = seen = 0
    with open(path, "rb") as fh:
        fh.read(step)
        while seen < sample:
            rec = fh.read(step)[:layout.length]
            if len(rec) < layout.length:
                break
            if rec.strip(b"]") == b"":
                continue
            seen += 1
            for f in layout.fields:
                if f.kind != "D" or f.filler:
                    continue
                for i in range(f.count):
                    raw = rec[f.offset + i * f.width:f.offset + (i + 1) * f.width]
                    total += 1
                    try:
                        decode_decimal(raw, f.decimals)
                        good += 1
                    except DecodeError:
                        pass
    return good, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", default=os.path.join("tests", "SCHEMA.md"))
    ap.add_argument("files", nargs="+")
    a = ap.parse_args()
    layouts = parse_schema(a.schema)
    lengths = {}
    for lay in layouts:
        lengths.setdefault(lay.length, []).append(lay)
    for path in a.files:
        size = os.path.getsize(path)
        print(f"{os.path.basename(path)}  ({size} bytes)")
        cands = []
        for length, lays in lengths.items():
            if length < 10:
                continue
            try:
                term = detect_terminator(path, length)
            except ValueError:
                continue
            for lay in lays:
                good, total = clean_fraction(path, lay, term)
                frac = good / total if total else 0.0
                cands.append((frac, len(term) > 0, length, lay, term, good, total))
        cands.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
        for frac, _, length, lay, term, good, total in cands[:5]:
            n = size // (length + len(term))
            score = f"{good}/{total} numeric fields decode" if total else "no numeric fields"
            print(f"    {lay.key:28s} length {length:4d}  {n:6d} records  "
                  f"terminator {term!r:7s}  {score}")
        if not cands:
            print("    no layout length fits")


if __name__ == "__main__":
    main()

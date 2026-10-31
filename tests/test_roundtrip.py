"""Round-trip tests on synthetic data only.

For every layout in SCHEMA.md: write synthetic records, convert them to SQLite, and
check that every value read back equals the value written.
"""
import os
import zlib
import sqlite3
from decimal import Decimal

import pytest

from dblconv.codec import DecodeError, decode_decimal, encode_decimal
from dblconv.convert import convert, detect_terminator
from dblconv.schema import parse_schema
from dblconv.synth import write_file

SCHEMA = os.path.join(os.path.dirname(__file__), "SCHEMA.md")
LAYOUTS = parse_schema(SCHEMA)
N = int(os.environ.get("DBLCONV_RECORDS", "50"))


def test_schema_counts():
    assert len(LAYOUTS) == 339


@pytest.mark.parametrize("text,dec,value", [
    (b"0000123", 0, Decimal(123)),
    (b"000012s", 0, Decimal(-123)),
    (b"0000p", 0, Decimal(0)),
    (b"0012345", 2, Decimal("123.45")),
    (b"001234y", 2, Decimal("-123.49")),
    (b"   12", 0, Decimal(12)),
])
def test_decode_known(text, dec, value):
    assert decode_decimal(text, dec) == value


def test_blank_is_null():
    assert decode_decimal(b"     ") is None


@pytest.mark.parametrize("bad", [b"12a45", b"1234z", b"12-45"])
def test_bad_digits_rejected(bad):
    with pytest.raises(DecodeError):
        decode_decimal(bad)


def test_encode_decode_inverse():
    for v in [0, 1, -1, 99999, -99999, Decimal("-0.05"), Decimal("123.40")]:
        assert decode_decimal(encode_decimal(v, 7, 2), 2) == Decimal(v)


@pytest.mark.parametrize("layout", LAYOUTS, ids=[l.key for l in LAYOUTS])
def test_roundtrip(layout, tmp_path):
    data, db = tmp_path / "data.dat", tmp_path / "out.sqlite"
    expected = write_file(data, layout, N, seed=zlib.crc32(layout.key.encode()))
    assert detect_terminator(data, layout.length) == b"\r\n"
    table = "t"
    info = convert(data, layout, db, table=table)
    assert info["records"] == N and info["field_errors"] == 0
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute(f'PRAGMA table_info("{table}")')][1:]
    rows = con.execute(f'SELECT * FROM "{table}" ORDER BY _record').fetchall()
    assert len(rows) == N
    for row, want in zip(rows, expected):
        got = dict(zip(cols, row[1:]))
        for name, v in want.items():
            g = got[name]
            if isinstance(v, Decimal):
                assert Decimal(str(g)) == v, (layout.key, name, g, v)
            else:
                assert g == v, (layout.key, name, g, v)


@pytest.mark.parametrize("term", [b"", b"\n", b"\r\n"])
def test_terminators(term, tmp_path):
    lay = next(l for l in LAYOUTS if l.name == "ADRMS")
    data = tmp_path / "d.dat"
    write_file(data, lay, 10, terminator=term)
    assert detect_terminator(data, lay.length) == term
    info = convert(data, lay, tmp_path / "o.sqlite", table="t")
    assert info["records"] == 10


def test_corrupt_field_logged(tmp_path):
    lay = next(l for l in LAYOUTS if l.key == "APADJ.FD:APADJ")
    data = tmp_path / "d.dat"
    write_file(data, lay, 3)
    raw = bytearray(data.read_bytes())
    raw[0] = ord("X")            # first byte of AJVND (D4) in record 1
    data.write_bytes(bytes(raw))
    db = tmp_path / "o.sqlite"
    info = convert(data, lay, db, table="t")
    assert info["field_errors"] == 1
    con = sqlite3.connect(db)
    (rec, fld), = con.execute("SELECT record, field FROM _conversion_errors")
    assert (rec, fld) == (1, "AJVND")


def test_empty_slots_skipped(tmp_path):
    lay = next(l for l in LAYOUTS if l.name == "ADRMS")
    data = tmp_path / "d.dat"
    write_file(data, lay, 3)
    with open(data, "ab") as fh:
        fh.write(b"]" * lay.length + b"\r\n")
        fh.write(b"]" * lay.length + b"\r\n")
    info = convert(data, lay, tmp_path / "o.sqlite", table="t")
    assert info["records"] == 3 and info["empty_slots"] == 2

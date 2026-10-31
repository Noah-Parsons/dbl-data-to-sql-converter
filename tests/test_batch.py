"""Folder conversion on synthetic data: layout choice, control records, unused slots,
CSV export and the report."""
import csv
import re
import os
import sqlite3
import zlib
from decimal import Decimal

from dblconv.batch import choose_layout, read_overrides, run
from dblconv.schema import find_layout, parse_schema
from dblconv.synth import synth_record

SCHEMA = os.path.join(os.path.dirname(__file__), "SCHEMA.md")
LAYOUTS = parse_schema(SCHEMA)


def write_relative(path, layout, n, slots=5, seed=1):
    """Control record, n data records, then unused ']' slots, CRLF terminated."""
    import random
    rng = random.Random(seed)
    expected = []
    with open(path, "wb") as fh:
        fh.write(b"0" * layout.length + b"\r\n")           # stand-in control record
        for _ in range(n):
            rec, values = synth_record(layout, rng)
            fh.write(rec + b"\r\n")
            expected.append(values)
        for _ in range(slots):
            fh.write(b"]" * layout.length + b"\r\n")
    return expected


def test_layout_from_file_name(tmp_path):
    lay = find_layout(LAYOUTS, "SALCT")
    p = tmp_path / "AR01SALC.DDF"
    write_relative(p, lay, 20)
    got, how = choose_layout(str(p), LAYOUTS, {})
    assert got.name == "SALCT" and "file name" in how


def test_layout_from_definition_file_name(tmp_path):
    lay = find_layout(LAYOUTS, "PB15.FD:PCHLG")
    p = tmp_path / "PR01PB15.DDF"
    write_relative(p, lay, 20)
    got, how = choose_layout(str(p), LAYOUTS, {})
    assert got.key == "PB15.FD:PCHLG"


def test_override_file(tmp_path):
    lay = find_layout(LAYOUTS, "SALCT")
    p = tmp_path / "ODDNAME.DDF"
    write_relative(p, lay, 5)
    (tmp_path / "layouts.csv").write_text("file,layout\nODDNAME.DDF,SALCT\n")
    got, how = choose_layout(str(p), LAYOUTS, read_overrides(str(tmp_path)))
    assert got.name == "SALCT" and "layouts.csv" in how


def test_folder_conversion(tmp_path):
    data, out = tmp_path / "DAT", tmp_path / "OUT"
    data.mkdir()
    lay = find_layout(LAYOUTS, "SALCT")
    expected = write_relative(data / "AR01SALC.DDF", lay, 30, slots=7)
    (data / "AR01JUNK.DDF").write_bytes(b"x" * 13)           # fits no layout
    (data / "AR01EMPT.DDF").write_bytes(b"")
    (data / "AR01ARCU.ISM").write_bytes(b"\0" * 64)           # ISAM: reported, not read
    results = run(str(data), str(out), SCHEMA, log=lambda *_: None)

    byname = {r[0]: r for r in results}
    info = byname["AR01SALC.DDF"][3]
    assert info["records"] == 30 and info["empty_slots"] == 7 and info["field_errors"] == 0
    assert byname["AR01JUNK.DDF"][3] is None and byname["AR01EMPT.DDF"][3] is None

    con = sqlite3.connect(out / "converted.sqlite")
    cols = [r[1] for r in con.execute('PRAGMA table_info("AR01SALC")')][1:]
    rows = con.execute('SELECT * FROM "AR01SALC" ORDER BY _record').fetchall()
    assert [r[0] for r in rows] == list(range(2, 32))         # record 1 is the control record
    for row, want in zip(rows, expected):
        got = dict(zip(cols, row[1:]))
        for k, v in want.items():
            assert (Decimal(str(got[k])) == v) if isinstance(v, Decimal) else (got[k] == v)
    (ctl,) = con.execute("SELECT raw FROM _control_records WHERE source='AR01SALC.DDF'").fetchone()
    assert ctl == "0" * lay.length

    with open(out / "Spreadsheets (CSV)" / "AR01SALC.csv", encoding="utf-8-sig") as fh:
        table = list(csv.reader(fh))
    assert table[0] == ["_record"] + cols and len(table) == 31
    assert table[1][1:] == ["" if v is None else str(v) for v in rows[0][1:]]

    report = (out / "CONVERSION REPORT.txt").read_text(encoding="utf-8-sig")
    assert re.search(r"Files converted:\s+1\b", report)
    assert "AR01ARCU.ISM" in report and "ISLOAD" in report
    assert "AR01JUNK.DDF" in report


def test_originals_untouched(tmp_path):
    data, out = tmp_path / "DAT", tmp_path / "OUT"
    data.mkdir()
    lay = find_layout(LAYOUTS, "SALCT")
    write_relative(data / "AR01SALC.DDF", lay, 10)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime) for p in data.iterdir()}
    run(str(data), str(out), SCHEMA, log=lambda *_: None)
    after = {p.name: (p.read_bytes(), p.stat().st_mtime) for p in data.iterdir()}
    assert before == after


def test_isam_unload_has_no_control_record(tmp_path):
    """An ISLOAD unload (.SEQ) is read from its first record, and its .ISM is no longer listed."""
    import random
    data, out = tmp_path / "DAT", tmp_path / "OUT"
    data.mkdir()
    lay = find_layout(LAYOUTS, "SALCT")
    rng = random.Random(9)
    with open(data / "AR01SALC.SEQ", "wb") as fh:
        for _ in range(12):
            fh.write(synth_record(lay, rng)[0] + b"\r\n")
    (data / "AR01SALC.ISM").write_bytes(b"\0" * 64)
    results = run(str(data), str(out), SCHEMA, log=lambda *_: None)
    (info,) = [r[3] for r in results if r[0] == "AR01SALC.SEQ"]
    assert info["records"] == 12
    con = sqlite3.connect(out / "converted.sqlite")
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='_control_records'").fetchone()
    assert con.execute('SELECT MIN(_record) FROM "AR01SALC"').fetchone()[0] == 1
    report = (out / "CONVERSION REPORT.txt").read_text(encoding="utf-8-sig")
    assert "ISAM files requiring an unload:             0" in report


def test_failed_file_does_not_stop_the_run(tmp_path, monkeypatch):
    import dblconv.batch as batch
    data, out = tmp_path / "DAT", tmp_path / "OUT"
    data.mkdir()
    lay = find_layout(LAYOUTS, "SALCT")
    write_relative(data / "AR01SALC.DDF", lay, 5)
    write_relative(data / "AR02SALC.DDF", lay, 6)
    real = batch.convert

    def flaky(path, *a, **k):
        if "AR01" in path:
            raise OSError("simulated read failure")
        return real(path, *a, **k)
    monkeypatch.setattr(batch, "convert", flaky)
    results = run(str(data), str(out), SCHEMA, log=lambda *_: None)
    byname = {r[0]: r for r in results}
    assert byname["AR01SALC.DDF"][3] is None and "simulated" in byname["AR01SALC.DDF"][2]
    assert byname["AR02SALC.DDF"][3]["records"] == 6
    assert not (out / "Spreadsheets (CSV)" / "AR01SALC.csv").exists()

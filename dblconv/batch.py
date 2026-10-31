"""Convert a whole DBL data folder in one step.

    python -m dblconv.batch DATA_FOLDER OUTPUT_FOLDER

For every data file (.DDF) in the folder this picks the record layout, converts the
records into one SQLite database, writes each table as a CSV file that opens in Excel,
and writes a plain-English report of what was done. ISAM files (.ISM/.IS1) cannot be
read directly: they are listed in the report as needing to be unloaded with ISLOAD first.

How a layout is chosen for a file such as AR01SALC.DDF:
  1. A layouts.csv file in the data folder (file,layout) overrides everything.
  2. Otherwise the name is read as module (AR), company (01) and file code (SALC), and
     the layouts whose record name or definition file starts with the code are tried.
  3. Only layouts whose record length fits the file exactly are kept; if more than one
     fits, the one whose numeric fields decode cleanly most often wins.
  4. If the name gives no match the file is not converted. Record length alone is not
     enough (on test data it chose the wrong layout about a third of the time), so the
     report lists the layouts whose length fits and asks for one to be named in layouts.csv.
Control-record layouts (CTL..., overlays, "... CONTROL RECORD") are never used for data.

Record 1 of each file is the file's control record. It is kept, unchanged, in the
_control_records table rather than decoded as data. Unused record slots (filled with
']') are skipped and counted.
"""
import argparse
import csv
import datetime
import os
import re
import sqlite3
import sys

from . import __version__
from .codec import DecodeError, decode_decimal
from .convert import convert, detect_terminator, is_empty_slot
from .schema import find_layout, parse_schema

DATA_EXT = (".DDF", ".SEQ")   # relative files; sequential unloads of ISAM files
SEQ_EXT = ".SEQ"
ISAM_EXT = (".ISM", ".IS1")
CSV_DIR = "Spreadsheets (CSV)"
DB_NAME = "converted.sqlite"
REPORT_NAME = "CONVERSION REPORT.txt"
NAME_RE = re.compile(r"^([A-Z]{2})(\d{2})(\w+)$")


def default_schema():
    base = getattr(sys, "_MEIPASS", None)
    here = os.path.join(base, "dblconv") if base else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "data", "SCHEMA.md")


def clean_fraction(path, layout, term, sample=200, skip=None):
    """Share of numeric fields that decode in up to `sample` used records."""
    if skip is None:
        skip = 0 if path.upper().endswith(SEQ_EXT) else 1
    step = layout.length + len(term)
    good = total = seen = 0
    with open(path, "rb") as fh:
        for _ in range(skip):
            fh.read(step)
        while seen < sample:
            rec = fh.read(step)[:layout.length]
            if len(rec) < layout.length:
                break
            if is_empty_slot(rec):
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
    return good, total, seen


def fits(path, layout):
    if layout.length <= 0:          # layouts with no fixed fields cannot describe a file
        return None
    try:
        return detect_terminator(path, layout.length)
    except ValueError:
        return None


def is_control_layout(layout):
    """Control-record layouts describe record 1 only, never the data records."""
    n = layout.name.upper()
    return (n.startswith("CTL") or n.startswith("OVERLAY") or n.endswith("CTL") or n == "CNTRL"
            or "CONTROL RECORD" in layout.title.upper())


def choose_layout(path, layouts, overrides):
    """Return (layout, how) or (None, reason)."""
    base = os.path.basename(path)
    stem = os.path.splitext(base)[0].upper()
    if base.upper() in overrides:
        spec = overrides[base.upper()]
        try:
            lay = find_layout(layouts, spec)
        except KeyError as e:
            return None, f"layouts.csv names {spec!r}, which is not usable: {e}"
        if fits(path, lay) is None:
            return None, f"layouts.csv names {lay.key}, but its record length ({lay.length}) does not fit the file"
        return lay, f"named in layouts.csv ({lay.key})"

    m = NAME_RE.match(stem)
    code = m.group(3) if m else stem
    named = [l for l in layouts if not is_control_layout(l) and (
        l.name.upper().startswith(code)
        or os.path.splitext(l.source)[0].upper().startswith(code)
        or code.startswith(os.path.splitext(l.source)[0].upper()))]
    pool = [l for l in named if fits(path, l) is not None]
    how = "matched by file name and record length"
    if not pool:
        # Record length alone is not safe: on test data it picked the wrong layout about a
        # third of the time. List the candidates so the user can name one in layouts.csv.
        cands = sorted({l.key for l in layouts if not is_control_layout(l) and fits(path, l)})
        if named:
            why = ("the file name suggests " + ", ".join(sorted({l.key for l in named}))
                   + ", but no layout's record length fits the file")
        else:
            why = "the file name does not match any record layout"
        if cands:
            shown = ", ".join(cands[:8]) + (f" and {len(cands) - 8} more" if len(cands) > 8 else "")
            why += f"; layouts with a record length that fits: {shown}"
        else:
            why += "; no layout in the layout set has a record length that fits this file"
        return None, why

    scored = []
    for lay in pool:
        good, total, seen = clean_fraction(path, lay, fits(path, lay))
        frac = good / total if total else 1.0
        scored.append((frac, good, -len(lay.fields), lay))
    scored.sort(key=lambda s: (s[0], s[1], s[2]), reverse=True)
    best = scored[0]
    # several layouts with identical results (e.g. the same record in an .FD and an .FDC)
    ties = [s for s in scored if s[0] == best[0] and s[1] == best[1]
            and [f.name for f in s[3].fields] != [f.name for f in best[3].fields]]
    note = ""
    if ties:
        note = "; other layouts fitted equally well: " + ", ".join(s[3].key for s in ties[:4])
    return best[3], f"{how} ({best[3].key}){note}"


def read_overrides(folder):
    path = os.path.join(folder, "layouts.csv")
    out = {}
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for row in csv.reader(fh):
                if len(row) >= 2 and row[0].strip() and not row[0].startswith("#"):
                    if row[0].strip().lower() == "file":
                        continue
                    out[row[0].strip().upper()] = row[1].strip()
    return out


def table_name(path):
    return re.sub(r"\W", "_", os.path.splitext(os.path.basename(path))[0].upper())


def save_control_record(db_path, path, layout):
    term = fits(path, layout) or b""
    with open(path, "rb") as fh:
        rec = fh.read(layout.length + len(term))[:layout.length]
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE IF NOT EXISTS _control_records (source TEXT, raw TEXT)")
    con.execute("INSERT INTO _control_records VALUES (?, ?)",
                (os.path.basename(path), rec.decode("latin-1")))
    con.commit()
    con.close()


def export_csv(db_path, table, csv_path):
    con = sqlite3.connect(db_path)
    cur = con.execute(f'SELECT * FROM "{table}" ORDER BY 1')
    cols = [d[0] for d in cur.description]
    n = 0
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for row in cur:
            w.writerow(["" if v is None else v.decode("latin-1") if isinstance(v, bytes) else v
                        for v in row])
            n += 1
    con.close()
    return n


def list_folder(folder):
    """Return (data files, ISAM files) in a folder, sorted by name."""
    names = sorted(os.listdir(folder))
    data = [n for n in names if n.upper().endswith(DATA_EXT) and os.path.isfile(os.path.join(folder, n))]
    unloaded = {os.path.splitext(n)[0].upper() for n in data if n.upper().endswith(SEQ_EXT)}
    isam = [n for n in names if n.upper().endswith(".ISM") and os.path.splitext(n)[0].upper() not in unloaded]
    return data, isam


def plural(n, word):
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def run(data_folder, out_folder, schema=None, skip_control=True, log=print):
    schema = schema or default_schema()
    layouts = parse_schema(schema)
    data_folder, out_folder = os.path.abspath(data_folder), os.path.abspath(out_folder)
    os.makedirs(out_folder, exist_ok=True)
    csv_dir = os.path.join(out_folder, CSV_DIR)
    os.makedirs(csv_dir, exist_ok=True)
    for old in os.listdir(csv_dir):          # results of an earlier run in this folder
        if old.lower().endswith(".csv"):
            os.remove(os.path.join(csv_dir, old))
    db_path = os.path.join(out_folder, DB_NAME)
    if os.path.exists(db_path):
        os.remove(db_path)
    overrides = read_overrides(data_folder)

    data_files, isam_files = list_folder(data_folder)
    log(f"Source folder: {data_folder}")
    log(f"{plural(len(data_files), 'data file')}, {plural(len(isam_files), 'ISAM file')}")

    results = []
    for n in data_files:
        path = os.path.join(data_folder, n)
        if os.path.getsize(path) == 0:
            results.append((n, None, "the file is empty (0 bytes)", None))
            log(f"  {n}: not converted (empty file)")
            continue
        lay, how = choose_layout(path, layouts, overrides)
        if lay is None:
            results.append((n, None, how, None))
            log(f"  {n}: not converted (no matching record layout)")
            continue
        table = table_name(path)
        has_control = skip_control and not n.upper().endswith(SEQ_EXT)   # unloads have none
        try:
            info = convert(path, lay, db_path, table=table, skip=1 if has_control else 0)
            if has_control:
                save_control_record(db_path, path, lay)
            rows = export_csv(db_path, table, os.path.join(csv_dir, f"{table}.csv"))
            if rows != info["records"]:
                raise RuntimeError(f"spreadsheet has {rows} rows but {info['records']} records were converted")
        except Exception as e:   # one bad file must not stop the rest
            drop_table(db_path, table, n)
            csv_path = os.path.join(csv_dir, f"{table}.csv")
            if os.path.exists(csv_path):
                os.remove(csv_path)
            results.append((n, None, f"conversion failed ({type(e).__name__}: {e})", None))
            log(f"  {n}: not converted (error: {e})")
            continue
        results.append((n, lay, how, info))
        log(f"  {n}: {plural(info['records'], 'record')} ({lay.key})"
            + (f", {plural(info['field_errors'], 'unreadable field')}" if info["field_errors"] else ""))

    if any(r[3] for r in results):
        export_csv(db_path, "_conversion_errors", os.path.join(csv_dir, "_conversion_errors.csv"))

    report = write_report(out_folder, data_folder, schema, results, isam_files, skip_control)
    ok = sum(1 for r in results if r[3])
    log(f"Complete: {ok} of {len(results)} files converted. Report: {report}")
    return results


def drop_table(db_path, table, source):
    """Remove whatever a failed conversion left behind."""
    if os.path.exists(db_path):
        con = sqlite3.connect(db_path)
        con.execute(f'DROP TABLE IF EXISTS "{table}"')
        for t in ("_control_records", "_conversion_errors"):
            if con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (t,)).fetchone():
                con.execute(f"DELETE FROM {t} WHERE source = ?", (source,))
        con.commit()
        con.close()


def write_report(out_folder, data_folder, schema, results, isam_files, skip_control):
    path = os.path.join(out_folder, REPORT_NAME)
    ok = [r for r in results if r[3]]
    bad = [r for r in results if not r[3]]
    errors = sum(r[3]["field_errors"] for r in ok)
    ties = [r for r in ok if "fitted equally well" in r[2]]
    layouts = ("built-in layout set" if os.path.abspath(schema) == os.path.abspath(default_schema())
               else schema)
    rule = "-" * 78

    def section(title):
        return ["", title.upper(), rule]

    lines = [
        "DBL DATA CONVERTER - CONVERSION REPORT",
        rule,
        f"Program version:  {__version__}",
        f"Date:             {datetime.datetime.now():%d %B %Y, %H:%M}",
        f"Source folder:    {data_folder}",
        f"Output folder:    {out_folder}",
        f"Record layouts:   {layouts}",
    ]
    lines += section("1. Summary")
    lines += [
        f"Files converted:                     {len(ok):>8,}",
        f"Records converted:                   {sum(r[3]['records'] for r in ok):>8,}",
        f"Unused record slots skipped:         {sum(r[3]['empty_slots'] for r in ok):>8,}",
        f"Fields that could not be read:       {errors:>8,}",
        f"Files not converted:                 {len(bad):>8,}",
        f"ISAM files requiring an unload:      {len(isam_files):>8,}",
    ]
    lines += section("2. Required checks")
    checks = ["Compare a sample of records and control totals with reports printed from the "
              "accounting system before relying on the converted data."]
    if ties:
        checks.append("Check in particular the files marked [CHECK LAYOUT] in section 3: more than "
                      "one record layout matched them equally well.")
    if errors:
        checks.append("Review _conversion_errors.csv. Each unreadable field is stored as blank and "
                      "listed there with its original contents.")
    if bad or isam_files:
        checks.append("Sections 4 and 5 list files that were not converted and the action required.")
    for i, c in enumerate(checks, 1):
        lines += wrap(f"{i}. {c}", indent="   ")
    lines += section("3. Files converted")
    if not ok:
        lines.append("None.")
    for n, lay, how, info in ok:
        flag = "  [CHECK LAYOUT]" if "fitted equally well" in how else ""
        lines += [f"{n}{flag}",
                  f"   Records: {info['records']:,}    Unused slots: {info['empty_slots']:,}    "
                  f"Unreadable fields: {info['field_errors']:,}",
                  f"   Spreadsheet: {CSV_DIR}\\{table_name(n)}.csv    Database table: {table_name(n)}"]
        lines += wrap("Layout: " + how, indent="   ", first="   ")
    if bad:
        lines += section("4. Files not converted")
        for n, _, why, _ in bad:
            lines.append(n)
            lines += wrap("Reason: " + why[:1].upper() + why[1:] + ".", indent="   ", first="   ")
        lines += [""] + wrap(
            "Action: where the reason lists layouts whose record length fits, the correct layout can "
            "be specified in a file named layouts.csv in the source folder, one line per data file "
            "in the form FILE,LAYOUT (for example: AR01SALC.DDF,SALCT). Run the conversion again "
            "afterwards. See the User Guide, Appendix A.")
    if isam_files:
        lines += section("5. ISAM files not read")
        lines += wrap("These indexed files cannot be read directly. Unload each one to a sequential "
                      "file with the accounting system's ISLOAD utility, giving the unloaded file the "
                      "same name with the extension .SEQ (for example AR01ARCU.ISM to AR01ARCU.SEQ). "
                      "Place it in the source folder and run the conversion again. See the User "
                      "Guide, section 4.3.")
        lines += [f"   {n}" for n in isam_files]
    lines += section("Notes")
    notes = [f"{DB_NAME} contains every converted table in a single SQLite database.",
             "Amounts with implied decimal places are stored as exact decimal text "
             "(for example 1234.56); no precision is lost.",
             "Record 1 of each file is its control record. It is stored unchanged in the "
             "_control_records table and is not included in the spreadsheets. Unloaded ISAM "
             "files (.SEQ) have no control record." if skip_control else
             "Control records were converted as ordinary records (--keep-control).",
             "The source files were opened read-only and have not been modified."]
    for c in notes:
        lines += wrap("- " + c, indent="  ")
    with open(path, "w", encoding="utf-8-sig", newline="\r\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def wrap(text, width=78, indent="", first=""):
    import textwrap
    return textwrap.wrap(text, width=width, initial_indent=first, subsequent_indent=indent or first) or [""]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert every DBL data file in a folder to SQLite and CSV.")
    ap.add_argument("data_folder")
    ap.add_argument("output_folder")
    ap.add_argument("--schema", help="path to SCHEMA.md (default: the copy bundled with dblconv)")
    ap.add_argument("--keep-control", action="store_true",
                    help="convert record 1 as data instead of keeping it as a control record")
    ap.add_argument("--version", action="version", version=f"dblconv {__version__}")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.data_folder):
        ap.error(f"{a.data_folder} is not a folder")
    run(a.data_folder, a.output_folder, a.schema, skip_control=not a.keep_control)


if __name__ == "__main__":
    main()

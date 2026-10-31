# DBL Data Converter

Converts the data files of a DBL accounting system to Excel-compatible spreadsheets (CSV)
and a single SQLite database, using the system's 339 record layouts. It keeps the
accounting records readable after the original system is retired, and gives a starting
point for moving them to another system.

- Reads relative data files (`.DDF`) and ISLOAD unloads of ISAM files (`.SEQ`).
- Identifies each file's record layout from its name and record length. A file it cannot
  identify is left out and listed, never guessed at.
- Writes a conversion report with the checks to make before relying on the results.
- Opens source files read-only and never modifies them.
- Runs entirely offline. No dependencies beyond the Python standard library.

## Download

Windows 10 or 11: download `DBL Data Converter.exe` from the
[latest release](../../releases/latest). No installation is needed. The
[User Guide](DBL%20Data%20Converter%20User%20Guide.docx) covers installation, use,
verification and troubleshooting.

## Use from Python

Python 3.9 or later.

```
python -m dblconv                                      # application window
python -m dblconv.batch SOURCE_FOLDER OUTPUT_FOLDER    # command line
```

The output folder receives:

| Item | Contents |
|---|---|
| `CONVERSION REPORT.txt` | Files converted, record counts, files not converted and why, required checks |
| `Spreadsheets (CSV)\` | One CSV file per data file; `_conversion_errors.csv` lists any unreadable field |
| `converted.sqlite` | Every table in one SQLite database, plus `_control_records` and `_conversion_errors` |

If a file's layout cannot be identified, the report lists the layouts whose record length
fits. Name the correct one in `layouts.csv` in the source folder, one line per file:

```
file,layout
GL01MAST.DDF,GLAMS.FD:GLAMS
```

To try it without real data:

```
python make_sample_data.py "Sample data"
python -m dblconv.batch "Sample data" "Sample data - Converted"
```

## Tests

```
pip install pytest
python -m pytest -q tests
python soak.py --records 10000 --seeds 20     # long run; writes soak.log
```

The tests round-trip synthetic records through every one of the 339 layouts and cover
folder conversion, layout selection, control records, ISLOAD unloads, failure handling
and the guarantee that source files are not modified. All test data is synthetic.

## Building the Windows application

On Windows 10 or 11 with Python 3.9 or later:

```
build_exe.bat
```

The script installs PyInstaller into a separate `.buildenv` folder, runs the tests, and
writes `dist\DBL Data Converter.exe` with the icon, version information, record layouts
and User Guide built in.

## How it works

- `dblconv/schema.py` reads the record layouts in `SCHEMA.md`: field offsets, alpha (`A`)
  and decimal (`D`) types, arrays such as `18D7`, and implied decimals from precisions
  such as `D10.2`.
- `dblconv/codec.py` decodes fields. Decimal fields are ASCII digits; a negative value
  stores its sign in the right-most digit as `p` to `y` for 0 to 9, and implied decimal
  points take no space (Synergy/DE, *Data types*:
  https://www.synergex.com/docs/lrm/lrmChap2Datatypes.htm). Blank decimal fields become NULL.
- `dblconv/convert.py` detects the record terminator (CRLF, LF or none) from the file
  size and writes one SQLite table per file. Whole-number decimals become INTEGER;
  decimals with implied places become TEXT holding the exact value, so nothing is lost to
  floating point. Undecodable fields are stored as NULL and logged in `_conversion_errors`.
- `dblconv/batch.py` converts a whole folder: layout selection, control records, unused
  record slots (`]`), CSV export and the report.
- `dblconv/gui.py` is the application window.
- `dblconv/synth.py` writes synthetic records from a layout for the tests.

See [CHANGELOG.md](CHANGELOG.md) for release history and [PROJECT_NOTES.md](PROJECT_NOTES.md)
for the original project plan and development log.

# Changelog

## 1.0.0 (October 2026)

First release.

- Windows application (DBL Data Converter.exe): source and output folder selection,
  progress display, activity log, conversion report viewer, Help menu with the user guide
  and version information. Also available from the command line:
  `python -m dblconv.batch SOURCE_FOLDER OUTPUT_FOLDER`.
- Converts relative data files (.DDF) and ISLOAD unloads of ISAM files (.SEQ) to one
  SQLite database and one CSV file per data file (Excel-compatible, UTF-8 with BOM).
- Selects each file's record layout from its file name and record length. A file whose
  layout cannot be identified is not converted; the report lists the layouts whose length
  fits, and a layout can be specified in layouts.csv. Record length alone is never used.
- Control records (record 1 of .DDF files) are stored unchanged in _control_records.
  Unused record slots are skipped and counted. Unreadable fields are stored as blank and
  listed in _conversion_errors.
- A failure in one file does not stop the conversion of the others; partial output for
  that file is removed.
- Writes a structured CONVERSION REPORT.txt with required checks.
- Source files are opened read-only and are not modified (tested).
- Record layouts (339), program icon and user guide are built in.

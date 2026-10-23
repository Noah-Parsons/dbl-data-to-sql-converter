# P45 — DBL data to SQL converter

**Field:** Software preservation  
**Size:** Medium (one project season)  
**Time:** 6-8 weeks

## Question
Build a tool that turns legacy DBL fixed-record data files into SQLite/Parquet using the published SCHEMA.md, and test it on synthetic files.

## Why it matters
It makes the preserved system's data readable without the runtime. Use only synthetic test data; never touch client data.

## Builds on
dibol-analysis SCHEMA.md, tools-fdparse.py

## Method
1. Generate synthetic files from the schema
2. Decoder for DBL numeric/alpha/date fields
3. Round-trip tests; publish as an open tool

## Deliverable
Open-source converter + note in the DIBOL deposit.

## Risks
Never test on real data: the Desktop ACC folder is off-limits.

## Before you start: novelty check
Search Google Scholar / arXiv / GitHub for: _legacy fixed width record conversion DIBOL_. If the question is already answered, narrow it or pick another project.

## Possible outlet
iPRES poster; software preservation community

## Log
_(dates, decisions, results)_

#!/usr/bin/env python3
"""
One-time EMIS -> Wing map builder.

Reads the legacy base file ("Punjab Enrollment Data - Base", same layout as
the old Google Sheet) and writes data/emis_wing.json, a static lookup the
dashboard uses to restore the Wing dimension that the new Grades export
does not include. After this runs once, the dashboard has NO live dependency
on the old sheet.

The new Grades CSV is the only daily data source; EMIS codes missing from
this map fall back to a Markaz-name keyword rule in the dashboard
(Male/Men/Boys vs Female/Women/Girls).

Usage:
  # from a local copy of the base file:
  python scripts/export_wing_map.py --csv "Punjab Enrollment Data - Base.csv"

  # directly from the legacy Google Sheet (needs internet):
  python scripts/export_wing_map.py --url

  python scripts/export_wing_map.py --csv base.csv --out data/emis_wing.json
"""

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

LEGACY_SHEET_CSV = ("https://docs.google.com/spreadsheets/d/"
                    "1AxmpCZhsQ-rFAJkgYrTbPby6FEG8HHkbL60IStUl-ak"
                    "/export?format=csv")

# Positional fallback (matches legacy fetch-data.js column indices).
FALLBACK_EMIS_IDX = 5
FALLBACK_WING_IDX = 3


def norm_emis(value):
    v = (value or "").strip()
    v = re.sub(r"\.0$", "", v)  # tolerate Excel-mangled codes
    return v


def norm_col(c):
    return re.sub(r"[\s_]+", "", (c or "").strip().lower())


WING_ALIASES = {"wing", "wname", "wingname"}
EMIS_ALIASES = {"emis", "emiscode"}


def detect_columns(header):
    """Return (emis_idx, wing_idx) from a header row, or (None, None)."""
    low = [norm_col(c) for c in header]
    emis_idx = next((i for i, c in enumerate(low)
                     if "emis" in c or c in EMIS_ALIASES), None)
    wing_idx = next((i for i, c in enumerate(low)
                     if c in WING_ALIASES or "wing" in c), None)
    if emis_idx is not None and wing_idx is not None:
        return emis_idx, wing_idx
    return None, None


def load_rows(args):
    if args.url or not args.csv:
        import urllib.request
        url = args.url or LEGACY_SHEET_CSV
        print(f"Downloading {url}")
        with urllib.request.urlopen(url, timeout=60) as resp:
            text = resp.read().decode("utf-8-sig")
        return text.splitlines()
    path = Path(args.csv)
    if not path.exists():
        sys.exit(f"ERROR: file not found: {path}")
    return path.read_text(encoding="utf-8-sig").splitlines()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", help="local base CSV file")
    ap.add_argument("--url", nargs="?", const=LEGACY_SHEET_CSV, default=None,
                    help="fetch from legacy Google Sheet URL (or custom URL)")
    ap.add_argument("--out", default="data/emis_wing.json",
                    help="output JSON path")
    args = ap.parse_args()

    lines = load_rows(args)
    reader = csv.reader(lines)
    try:
        first = next(reader)
    except StopIteration:
        sys.exit("ERROR: empty input")

    emis_idx, wing_idx = detect_columns(first)
    if emis_idx is None:
        print("No header detected; using positional fallback "
              f"(EMIS col {FALLBACK_EMIS_IDX}, Wing col {FALLBACK_WING_IDX}).")
        emis_idx, wing_idx = FALLBACK_EMIS_IDX, FALLBACK_WING_IDX
        data_rows = [first] + list(reader)
    else:
        print(f"Header detected: EMIS col {emis_idx}, Wing col {wing_idx}.")
        data_rows = list(reader)

    mapping, conflicts, skipped = {}, Counter(), 0
    for row in data_rows:
        if len(row) <= max(emis_idx, wing_idx):
            skipped += 1
            continue
        emis = norm_emis(row[emis_idx])
        wing = (row[wing_idx] or "").strip()
        if not emis or not wing:
            skipped += 1
            continue
        if emis in mapping and mapping[emis] != wing:
            conflicts[emis] += 1
        mapping[emis] = wing  # last wins on conflict

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mapping, indent=0, sort_keys=True))

    wings = Counter(mapping.values())
    print(f"Wrote {out}: {len(mapping)} EMIS codes, "
          f"{len(wings)} distinct wings, {skipped} skipped rows, "
          f"{len(conflicts)} conflicting EMIS (last won).")
    for wing, count in wings.most_common():
        print(f"  {wing!r}: {count}")
    if conflicts:
        print("Sample conflicts:", list(conflicts)[:10])


if __name__ == "__main__":
    main()

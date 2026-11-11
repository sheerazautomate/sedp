#!/usr/bin/env python3
"""
Build the list of high and higher secondary schools with low enrollment.

Reads the dashboard snapshots in data/ and writes, for a ceiling of 300 students:

    secondary_low_enrollment/secondary_schools_300_or_less.xlsx
    secondary_low_enrollment/secondary_schools_300_or_less.csv

Run from the repository root:

    python3 scripts/build_secondary_low_enrollment.py             # 300 or less
    python3 scripts/build_secondary_low_enrollment.py --max 200   # another ceiling

The workbook needs openpyxl (pip install openpyxl); the CSV does not.

Rules
-----
Schools covered  Every school the dashboard marks as Secondary wing (SE in
                 data/emis_wing.json), plus every school named as high or
                 higher secondary that the wing list files elsewhere. The
                 second group carries a remark in the output.
Enrollment       The current total the dashboard shows: boys + girls + other
                 from the source chosen in data/source.json (SIS or Grades).
Grades fallback  A school with no SIS record keeps its Grades figure, as on
                 the dashboard. So does a school where SIS shows 0 while Grades
                 recorded students: SIS answers 0 when a school's saved IDs go
                 stale, so that 0 is read as a failed lookup. Both cases carry
                 a remark, and the second is listed on its own sheet.
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "secondary_low_enrollment"

# (header, column width, cell kind) for the list, shared by the CSV and the workbook.
# Kinds: text (wraps), code (centred whole number), int (thousands separator), pct.
LIST_COLUMNS = [
    ("Sr.", 6, "code"), ("District", 21, "text"), ("Tehsil", 26, "text"), ("EMIS", 11, "code"),
    ("School", 52, "text"), ("Level", 17, "text"), ("Gender", 8, "text"),
    ("Boys Enrolled", 9, "int"), ("Girls Enrolled", 9, "int"), ("Other", 7, "int"),
    ("Total Enrollment", 12, "int"), ("Remarks", 30, "text"),
]

# School-type acronyms that open most names: GPS, GGES, GHS, GGHSS, GGCMHS ...
# Consonants only before the ending, so ordinary words such as "FAITHS" never match.
SCHOOL_ACRONYM = re.compile(r"^G[B-DF-HJ-NP-TV-Z]*?(PS|ES|MS|HSS|HS)$")

# Why a school shows its Grades figure although SIS is the selected source.
NO_RECORD, SIS_ZERO = "No SIS record", "SIS shows 0"


# ---------------------------------------------------------------------------
# reading the snapshots
# ---------------------------------------------------------------------------
def num(value):
    """Counts as the dashboard reads them: blank or dash is 0, commas stripped."""
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in ("", "-", "--"):
        return 0
    try:
        return int(round(float(text)))
    except ValueError:
        return 0


def clean(text):
    return " ".join(str(text or "").split())


def emis_code(value):
    return re.sub(r"\.0$", "", clean(value))


def read_json(name):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def fetched_at(name):
    """(day, day and time) of a snapshot: ('11 Nov 2026', '11 Nov 2026, 04:07 PM PKT')."""
    try:
        text = clean(read_json(name).get("fetched_at_pkt"))
        when = dt.datetime.strptime(text.replace(" PKT", ""), "%Y-%m-%d %I:%M %p")
    except (OSError, ValueError, AttributeError):
        return "date not recorded", "date not recorded"
    day = f"{when.day} {when:%b %Y}"
    return day, f"{day}, {when:%I:%M %p} PKT"


def selected_source():
    """'sis' or 'grades', as chosen for the dashboard in data/source.json."""
    try:
        config = read_json("source.json")
        choice = config.get("source") or config.get("datasource") or config.get("data_source")
    except (OSError, ValueError, AttributeError):
        choice = ""
    return "sis" if str(choice or "").strip().lower() == "sis" else "grades"


def name_tokens(name):
    """Upper-case words of a name, letters only ('H/S' -> 'HS'); chak numbers dropped."""
    return [re.sub(r"[^A-Z]", "", word) for word in name.upper().split()
            if not any(ch.isdigit() for ch in word)]


def school_level(name):
    """'Higher Secondary', 'High', or '' when the name does not say."""
    upper = name.upper()
    tokens = name_tokens(name)
    lead = SCHOOL_ACRONYM.match(tokens[0]) if tokens else None
    if lead:  # 'GHS ...', 'GGPS ...': the opening acronym settles it
        return {"HSS": "Higher Secondary", "HS": "High"}.get(lead.group(1), "")
    endings = [m.group(1) for m in map(SCHOOL_ACRONYM.match, tokens) if m]
    if "HIGHER SECONDARY" in upper or "HSS" in tokens or "HSS" in endings:
        return "Higher Secondary"
    if "HIGH SCHOOL" in upper or "SECONDARY SCHOOL" in upper or "HS" in tokens or "HS" in endings:
        return "High"
    return ""


def school_gender(name, boys, girls):
    """('Boys' or 'Girls', True when the name says so, False when judged by students)."""
    upper = name.upper()
    if re.search(r"\bGIRLS?\b", upper):
        return "Girls", True
    if re.search(r"\bBOYS?\b", upper):
        return "Boys", True
    tokens = name_tokens(name)
    acronym = next((t for t in tokens if SCHOOL_ACRONYM.match(t)), "")
    lead = tokens[0] if tokens else ""
    # GGHS, GGCMHS, 'GG BBS HS', and G(M)GHS where the G before HS is "Girls".
    if acronym.startswith("GG") or lead.startswith("GG") or re.fullmatch(r"G[A-Z]+GHSS?", acronym):
        return "Girls", True
    if acronym in ("GHS", "GHSS"):
        return "Boys", True
    return ("Girls" if girls > boys else "Boys"), False


def load_schools(source, grades_day):
    """Every school in scope, with its current counts and any remarks."""
    wing_of = read_json("emis_wing.json")
    sis = {}
    if source == "sis":
        sis = {emis_code(s["emis"]): s for s in read_json("sis_enrollment.json")["schools"]
               if str(s.get("status") or "ok").lower() == "ok"}

    schools = []
    with open(DATA / "enrollment.csv", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            emis = emis_code(row["EMIS"])
            name = clean(row["School Name"])
            wing = clean(wing_of.get(emis))
            level = school_level(name)
            if wing != "SE" and not level:
                continue

            remarks = []
            if wing != "SE":
                on_dashboard = f"{wing} on dashboard" if wing else "Not on dashboard"
                in_grades = "Secondary Wing" if "SECONDARY" in row["Markaz"].upper() else "elementary markaz"
                remarks.append(f"{on_dashboard}; {in_grades} in Grades")

            # Grades figures first; SIS replaces them unless its lookup is missing or failed.
            boys, girls, total = num(row["Male Current"]), num(row["Female Current"]), num(row["Total Current"])
            fallback = ""
            if source == "sis":
                record = sis.get(emis)
                if record is None:
                    fallback = NO_RECORD
                else:
                    sis_boys, sis_girls = num(record.get("curM")), num(record.get("curF"))
                    sis_total = (num(record["curT"]) if record.get("curT") is not None
                                 else sis_boys + sis_girls + num(record.get("curOther")))
                    if sis_total == 0 and total > 0:
                        fallback = SIS_ZERO
                    else:
                        boys, girls, total = sis_boys, sis_girls, sis_total
            if fallback:
                remarks.append(f"{fallback}; Grades figure of {grades_day} used")

            gender, named = school_gender(name, boys, girls)
            schools.append({
                "district": clean(row["District"]), "tehsil": clean(row["Tehsil"]),
                "emis": int(emis) if emis.isdigit() else emis, "school": name, "wing": wing,
                "level": level or "Not stated", "gender": gender, "gender_named": named,
                "boys": boys, "girls": girls, "other": total - boys - girls, "total": total,
                "remarks": "; ".join(remarks), "fallback": fallback,
            })
    return schools


# ---------------------------------------------------------------------------
# shaping the output
# ---------------------------------------------------------------------------
def size_bands(ceiling):
    """[(label, low, high)] in steps of 100: 'Up to 100', '101-200', '201-300'."""
    bands, low = [], 0
    for high in list(range(100, ceiling, 100)) + [ceiling]:
        bands.append((f"Up to {high}" if not bands else f"{low}\u2013{high}", low, high))
        low = high + 1
    return bands


def list_row(index, s):
    return [index, s["district"], s["tehsil"], s["emis"], s["school"], s["level"], s["gender"],
            s["boys"], s["girls"], s["other"], s["total"], s["remarks"]]


def district_rows(schools, listed, bands):
    """One row per district, most listed schools first, and a Punjab total row."""
    in_scope = Counter(s["district"] for s in schools)
    by_district = {}
    for s in listed:
        by_district.setdefault(s["district"], []).append(s)

    def row(label, scope_count, group):
        return ([label, scope_count, len(group), len(group) / scope_count if scope_count else 0,
                 sum(s["level"] == "High" for s in group),
                 sum(s["level"] == "Higher Secondary" for s in group),
                 sum(s["gender"] == "Boys" for s in group),
                 sum(s["gender"] == "Girls" for s in group)]
                + [sum(low <= s["total"] <= high for s in group) for _, low, high in bands]
                + [sum(s["total"] for s in group)])

    rows = [row(district, count, by_district.get(district, [])) for district, count in in_scope.items()]
    rows.sort(key=lambda r: (-r[2], r[0]))
    return rows, row("Punjab", len(schools), listed)


def notes(schools, listed, sis_zeros, ceiling, source_line, grades_day):
    """(label, text) pairs for the Notes sheet. Counts follow a colon so 1 reads as well as 13."""
    se_count = sum(s["wing"] == "SE" for s in schools)
    not_se = sum(s["wing"] != "SE" for s in listed)
    no_record = sum(s["fallback"] == NO_RECORD for s in listed)
    by_students = sum(not s["gender_named"] for s in listed)

    out = [
        ("What is listed",
         f"Government high and higher secondary schools in Punjab whose total enrollment is "
         f"{ceiling} or less: {len(listed):,} of {len(schools):,} schools."),
        ("Enrollment",
         f"{source_line}. This is the figure the dashboard shows. Total = Boys + Girls + Other, "
         f"for the whole school."),
        ("Schools covered",
         f"All {se_count:,} schools the dashboard marks as Secondary wing (SE), plus "
         f"{len(schools) - se_count:,} schools named as high or higher secondary that it does "
         f"not mark SE."),
    ]
    if not_se:
        out.append(("Not marked SE",
                    f"Schools in the list that the dashboard does not mark SE: {not_se}. The remark "
                    f"gives the wing the dashboard shows and where Grades places the school. To "
                    f"keep only the dashboard's SE wing, filter Remarks to blanks."))
    if sis_zeros:
        in_list = sum(s["total"] <= ceiling for s in sis_zeros)
        out.append((SIS_ZERO,
                    f"Schools where SIS shows 0 students although Grades recorded students on "
                    f"{grades_day}: {len(sis_zeros)}. Each 0 is read as a failed SIS lookup, not an "
                    f"empty school, so the Grades figure is used instead; the dashboard shows 0. "
                    f"{in_list or 'None'} of them {'is' if in_list <= 1 else 'are'} in the list. "
                    f"See the '{SIS_ZERO}' sheet."))
    if no_record:
        out.append((NO_RECORD,
                    f"Schools in the list with no SIS record: {no_record}. The Grades figure of "
                    f"{grades_day} is used for them, as on the dashboard."))
    gender = ("Boys or Girls, read from the school name (GHS, GHSS = boys; GGHS, GGHSS or "
              "'Girls' = girls).")
    if by_students:
        gender += (f" Where the name does not say, the larger group of students decides "
                   f"(schools in the list: {by_students}).")
    out += [
        ("Level", "High or Higher Secondary, read from the school name."),
        ("Gender", gender),
        ("Other", "Students reported as 'Other' rather than as boys or girls."),
        ("Order", "By district (A to Z), then smallest enrollment first."),
    ]
    return out


def write_csv(path, listed):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([header for header, _, _ in LIST_COLUMNS])
        writer.writerows(list_row(index, s) for index, s in enumerate(listed, 1))


# ---------------------------------------------------------------------------
# workbook
# ---------------------------------------------------------------------------
def write_workbook(path, schools, listed, sis_zeros, ceiling, source_line, grades_day):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins
    from openpyxl.worksheet.properties import PageSetupProperties

    def font(size=11, **style):
        return Font(name="Calibri", size=size, **style)

    navy = "1F3864"
    edge = Side(style="thin", color="BFBFBF")
    box = Border(left=edge, right=edge, top=edge, bottom=edge)
    bold, title_font, subtitle_font = font(bold=True), font(14, bold=True, color=navy), font(10, color="595959")
    head_font = font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", start_color=navy)
    head_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
    flag_fill = PatternFill("solid", start_color="FFF2CC")
    total_fill = PatternFill("solid", start_color="E7E6E6")
    align = {
        "text": Alignment(vertical="top", wrap_text=True),
        "code": Alignment(horizontal="center", vertical="top"),
        "int": Alignment(horizontal="right", vertical="top"),
        "pct": Alignment(horizontal="right", vertical="top"),
    }
    number_format = {"code": "0", "int": "#,##0", "pct": "0.0%"}

    # Row heights are left to the spreadsheet program, which fits them to wrapped text.
    def heading(ws, title, subtitle=None):
        ws["A1"], ws["A1"].font = title, title_font
        if subtitle:
            ws["A2"], ws["A2"].font = subtitle, subtitle_font

    def head_cell(ws, row, column, value):
        cell = ws.cell(row=row, column=column, value=value)
        cell.font, cell.fill, cell.border, cell.alignment = head_font, head_fill, box, head_align

    def table(ws, top, columns, rows):
        """Write a bordered table with its header on row `top`; return its last row."""
        for c, (header, width, _) in enumerate(columns, 1):
            head_cell(ws, top, c, header)
            ws.column_dimensions[get_column_letter(c)].width = width
        for r, values in enumerate(rows, top + 1):
            for c, value in enumerate(values, 1):
                kind = columns[c - 1][2]
                cell = ws.cell(row=r, column=c, value=value)
                cell.border, cell.alignment = box, align[kind]
                if kind in number_format:
                    cell.number_format = number_format[kind]
        return top + len(rows)

    def printable(ws, title_rows=None):
        """Landscape A4, one page wide, header rows repeated on every page."""
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
        ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
        ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.6)
        ws.oddFooter.center.text = "Page &P of &N"
        if title_rows:
            ws.print_title_rows = title_rows

    wb = Workbook()

    # 1. the list
    ws = wb.active
    ws.title = f"Schools {ceiling} or less"
    heading(ws, f"Punjab: high and higher secondary schools with enrollment of {ceiling} or less",
            f"{len(listed):,} schools  \u00b7  {source_line}  \u00b7  Sorted by district, smallest school first")
    last = table(ws, 3, LIST_COLUMNS, [list_row(i, s) for i, s in enumerate(listed, 1)])
    headers = [header for header, _, _ in LIST_COLUMNS]
    total_col, remarks_col = headers.index("Total Enrollment") + 1, headers.index("Remarks") + 1
    for r in range(4, last + 1):
        ws.cell(row=r, column=total_col).font = bold
        if ws.cell(row=r, column=remarks_col).value:
            ws.cell(row=r, column=remarks_col).fill = flag_fill
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = f"A3:{get_column_letter(len(LIST_COLUMNS))}{last}"
    printable(ws, "3:3")

    # 2. district summary: a group label on row 3 over the columns about listed schools
    bands = size_bands(ceiling)
    rows, punjab = district_rows(schools, listed, bands)
    ws = wb.create_sheet("District summary")
    heading(ws, f"District summary: schools with enrollment of {ceiling} or less",
            f"{source_line}  \u00b7  Districts with the most such schools first")
    columns = ([("District", 22, "text"), ("All high & higher secondary schools", 19, "int"),
                ("Schools", 10, "int"), ("Share of district", 10, "pct"),
                ("High", 9, "int"), ("Higher Secondary", 12, "int"),
                ("Boys' schools", 9, "int"), ("Girls' schools", 9, "int")]
               + [(f"{label} students", 10, "int") for label, _, _ in bands]
               + [("Students enrolled", 11, "int")])
    last = table(ws, 4, columns, rows + [punjab])
    for c in range(1, len(columns) + 1):
        head_cell(ws, 3, c, f"Schools with {ceiling} or less" if c == 3 else None)
        ws.cell(row=last, column=c).font, ws.cell(row=last, column=c).fill = bold, total_fill
    ws.merge_cells(start_row=3, start_column=3, end_row=3, end_column=len(columns))
    ws.freeze_panes = "B5"
    printable(ws, "3:4")

    # 3. schools whose SIS total of 0 was replaced by the Grades figure
    if sis_zeros:
        ws = wb.create_sheet(SIS_ZERO)
        heading(ws, "Schools where SIS shows 0 students",
                f"Grades recorded students here on {grades_day}, so the Grades figure is used. "
                f"Those at {ceiling} or less are in the list.")
        columns = [("District", 21, "text"), ("Tehsil", 26, "text"), ("EMIS", 11, "code"),
                   ("School", 40, "text"), ("Wing on dashboard", 12, "text"),
                   (f"Grades enrollment ({grades_day})", 18, "int")]
        table(ws, 3, columns, [[s["district"], s["tehsil"], s["emis"], s["school"], s["wing"], s["total"]]
                               for s in sis_zeros])
        printable(ws, "3:3")

    # 4. notes
    ws = wb.create_sheet("Notes")
    heading(ws, "Notes")
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 18, 110
    lines = notes(schools, listed, sis_zeros, ceiling, source_line, grades_day)
    for r, (label, text) in enumerate(lines, 3):
        ws.cell(row=r, column=1, value=label).font = bold
        ws.cell(row=r, column=1).alignment = align["text"]
        ws.cell(row=r, column=2, value=text).alignment = align["text"]
    printable(ws)

    wb.save(path)


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--max", type=int, default=300, metavar="N",
                        help="highest enrollment to include (default: 300)")
    ceiling = parser.parse_args().max
    if ceiling < 1:
        parser.error("--max must be at least 1")

    source = selected_source()
    grades_day, grades_time = fetched_at("meta.json")
    source_line = ("Current enrollment from SIS, " + fetched_at("sis_enrollment.json")[1]
                   if source == "sis" else "Current enrollment from Grades, " + grades_time)

    schools = load_schools(source, grades_day)
    listed = sorted((s for s in schools if s["total"] <= ceiling),
                    key=lambda s: (s["district"], s["total"], s["school"]))
    sis_zeros = sorted((s for s in schools if s["fallback"] == SIS_ZERO),
                       key=lambda s: (s["district"], s["school"]))

    OUT.mkdir(exist_ok=True)
    stem = OUT / f"secondary_schools_{ceiling}_or_less"
    write_csv(stem.with_suffix(".csv"), listed)
    print(f"{len(listed):,} of {len(schools):,} schools have {ceiling} or fewer students "
          f"({len(sis_zeros)} with an SIS total of 0 use their Grades figure).")
    print(f"Wrote {stem.with_suffix('.csv').relative_to(ROOT)}")
    try:
        write_workbook(stem.with_suffix(".xlsx"), schools, listed, sis_zeros, ceiling, source_line, grades_day)
    except ImportError:
        sys.exit("ERROR: the workbook needs openpyxl. Install with: pip install openpyxl")
    print(f"Wrote {stem.with_suffix('.xlsx').relative_to(ROOT)}")


if __name__ == "__main__":
    main()

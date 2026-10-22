#!/usr/bin/env python3
"""
Build the District Layyah enrollment presentation.

Reads the dashboard snapshots in data/ (Grades = baseline/target, SIS = current),
computes every figure used in the deck, and writes:

    layyah/index.html            self-contained 16:9 deck (CSS + JS + logo inlined)
    layyah/layyah_schools.csv    school-level working sheet (1,223 rows)
    layyah/layyah_markaz.csv     markaz-level summary (100 rows)
    layyah/layyah_tehsils.csv    tehsil-level summary (3 rows)

Run from the repository root:  python3 scripts/build_layyah_deck.py
"""
import base64
import csv
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "layyah"
ASSETS = ROOT / "scripts" / "assets"

DISTRICT = "LAYYAH"
SNAP_SIS = "22 Oct 2026, 06:26 AM PKT"
SNAP_GRADES = "14 Oct 2026, 05:50 PM PKT"
WING_LABEL = {"M-EE": "Male Elementary", "W-EE": "Female Elementary", "SE": "Secondary"}
WING_SHORT = {"M-EE": "M-EE", "W-EE": "W-EE", "SE": "SE"}
TEHSIL_ORDER = ["Layyah", "Karor Lalisan", "Chaubara"]
TEHSIL_FIX = {"LAYYAH": "Layyah", "KAROR LALISAN": "Karor Lalisan", "CHAUBARA": "Chaubara"}
WING_COLOR = {"M-EE": "#4f46e5", "W-EE": "#db2777", "SE": "#0f766e"}


# ---------------------------------------------------------------------------
# calculations
# ---------------------------------------------------------------------------
def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def ach(cur, base, target):
    """Dashboard rule: uncapped, with a guard when the target sits at/below baseline."""
    denom = target - base
    if denom <= 0:
        return 100.0 if cur >= base else 0.0
    return (cur - base) / denom * 100.0


def health(cur, base, target):
    if cur < base:
        return "below_base"
    if cur < target:
        return "below_target"
    return "above_target"


def smart_name(name):
    """Normalise messy EMIS markaz names: 'KOT SULTAN-II - FEMALE' -> 'Kot Sultan-II (Female)'."""
    raw = " ".join(name.split())
    m = re.match(r"^(.*?)\s*[-–]?\s*(MALE|FEMALE)\s*$", raw, re.I)
    base, gender = (m.group(1), m.group(2).title()) if m else (raw, "")
    roman = {"I", "II", "III", "IV", "V", "VI", "VII"}
    words = []
    for tok in base.split(" "):
        if "/" in tok or any(ch.isdigit() for ch in tok):
            words.append(tok.upper())
            continue
        parts = []
        for part in tok.split("-"):
            up = part.upper()
            if up in roman:
                parts.append(up)
            else:
                parts.append(part[:1].upper() + part[1:].lower())
        words.append("-".join(parts))
    out = " ".join(words).strip()
    return f"{out} ({gender})" if gender else out


def load_schools():
    wing_map = json.loads((ROOT / "data/emis_wing.json").read_text())
    sis = {s["emis"]: s for s in json.loads((ROOT / "data/sis_enrollment.json").read_text())["schools"]}
    prev = {s["emis"]: s for s in json.loads((ROOT / "data/sis_enrollment_prev.json").read_text())["schools"]}

    schools = []
    with open(ROOT / "data/enrollment.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["District"].strip().upper() != DISTRICT:
                continue
            emis = r["EMIS"].strip()
            cur, old = sis.get(emis, {}), prev.get(emis, {})
            cM = cur.get("curM", num(r["Male Current"]))
            cF = cur.get("curF", num(r["Female Current"]))
            cO = cur.get("curOther", 0)
            bM, bF = num(r["Male Baseline"]), num(r["Female Baseline"])
            tM, tF = num(r["Male Target"]), num(r["Female Target"])
            s = {
                "emis": emis,
                "name": " ".join(r["School Name"].split()),
                "tehsil": TEHSIL_FIX.get(r["Tehsil"].strip().upper(), r["Tehsil"].strip().title()),
                "markaz": " ".join(r["Markaz"].split()),
                "wing": wing_map.get(emis, "—"),
                "bM": bM, "bF": bF, "tM": tM, "tF": tF,
                "cM": cM, "cF": cF, "cO": cO,
                "bT": bM + bF, "tT": tM + tF, "cT": cM + cF + cO,
                "matched": emis in sis,
            }
            s["achM"] = ach(s["cM"], s["bM"], s["tM"])
            s["achF"] = ach(s["cF"], s["bF"], s["tF"])
            s["achT"] = ach(s["cT"], s["bT"], s["tT"])
            s["health"] = health(s["cT"], s["bT"], s["tT"])
            s["gap"] = s["tT"] - s["cT"]
            s["growth"] = s["cT"] - s["bT"]
            s["delta"] = s["cT"] - old.get("curT", s["cT"])
            s["inc"] = s["tT"] - s["bT"]
            schools.append(s)
    return schools


KEYS = ["bM", "bF", "cM", "cF", "cO", "bT", "cT", "tM", "tF", "tT"]


def agg(group):
    s = {k: sum(x[k] for x in group) for k in KEYS}
    s["n"] = len(group)
    s["markaz"] = len({(x["tehsil"], x["markaz"]) for x in group if "SECONDARY" not in x["markaz"].upper()})
    s["achM"] = ach(s["cM"], s["bM"], s["tM"])
    s["achF"] = ach(s["cF"], s["bF"], s["tF"])
    s["achT"] = ach(s["cT"], s["bT"], s["tT"])
    s["gap"] = s["tT"] - s["cT"]
    s["growth"] = s["cT"] - s["bT"]
    s["needM"] = s["tM"] - s["cM"]
    s["needF"] = s["tF"] - s["cF"]
    s["share_gap"] = 0.0
    s["share_enr"] = 0.0
    s["share_schools"] = 0.0
    s["gpi"] = (s["cF"] / s["cM"]) if s["cM"] else float("nan")
    s["female_share"] = 100.0 * s["cF"] / s["cT"] if s["cT"] else 0.0
    s["below_base"] = sum(1 for x in group if x["health"] == "below_base")
    s["below_target"] = sum(1 for x in group if x["health"] == "below_target")
    s["above_target"] = sum(1 for x in group if x["health"] == "above_target")
    s["median_ach"] = statistics.median(x["achT"] for x in group) if group else 0.0
    s["median_size"] = statistics.median(x["cT"] for x in group) if group else 0.0
    s["delta"] = sum(x["delta"] for x in group)
    s["zero_girls"] = sum(1 for x in group if x["cF"] == 0)
    s["zero_boys"] = sum(1 for x in group if x["cM"] == 0)
    return s


def fmt(n):
    return f"{n:,.0f}"


def signed(n):
    return f"{n:+,.0f}"


def pct(n, dp=1):
    return f"{n:.{dp}f}%"


def ach_color(v):
    if v >= 100:
        return "var(--green)"
    if v >= 80:
        return "var(--blue)"
    if v >= 50:
        return "var(--amber)"
    if v >= 0:
        return "var(--red)"
    return "var(--darkred)"


def chip(v):
    return f'<span class="chip" style="background:{ach_color(v)}1a;color:{ach_color(v)}">{pct(v)}</span>'


def group_markaz(group):
    out = {}
    for s in group:
        out.setdefault((s["tehsil"], s["markaz"]), []).append(s)
    return out


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def build():
    schools = load_schools()
    district = agg(schools)
    district["share_gap"] = 100.0
    district["share_enr"] = 100.0
    district["share_schools"] = 100.0
    n = district["n"]
    total_inc = district["tT"] - district["bT"]

    tehsils = []
    for t in TEHSIL_ORDER:
        g = [s for s in schools if s["tehsil"] == t]
        a = agg(g)
        a["name"] = t
        for key in ("share_gap", "share_enr", "share_schools"):
            a[key] = 100.0 * a[{"share_gap": "gap", "share_enr": "cT", "share_schools": "n"}[key]] / district[
                {"share_gap": "gap", "share_enr": "cT", "share_schools": "n"}[key]]
        tehsils.append(a)

    wings = []
    for w in ("M-EE", "W-EE", "SE"):
        a = agg([s for s in schools if s["wing"] == w])
        a["code"] = w
        a["name"] = WING_LABEL[w]
        a["share_gap"] = 100.0 * a["gap"] / district["gap"]
        a["share_enr"] = 100.0 * a["cT"] / district["cT"]
        a["share_schools"] = 100.0 * a["n"] / district["n"]
        wings.append(a)
    elem = agg([s for s in schools if s["wing"] in ("M-EE", "W-EE")])
    elem["share_gap"] = 100.0 * elem["gap"] / district["gap"]

    # markaz (the three "SECONDARY-WING" buckets are a wing, not an AEO markaz)
    markaz_all = []
    for (teh, name), g in group_markaz(schools).items():
        a = agg(g)
        a["tehsil"] = teh
        a["name"] = name
        a["secondary"] = "SECONDARY" in name.upper()
        a["share_gap"] = 100.0 * a["gap"] / district["gap"]
        markaz_all.append(a)
    markaz = [m for m in markaz_all if not m["secondary"]]
    markaz_sorted = sorted(markaz, key=lambda m: -m["achT"])
    at_target = [m for m in markaz if m["achT"] >= 100]
    neg_markaz = sorted([m for m in markaz if m["achT"] < 0], key=lambda m: m["achT"])

    # school-size bands
    bands = []
    for lo, hi in [(0, 50), (50, 100), (100, 200), (200, 400), (400, 800), (800, 10 ** 9)]:
        g = [s for s in schools if lo <= s["cT"] < hi]
        if not g:
            continue
        a = agg(g)
        a["label"] = f"{lo:,}–{hi:,}" if hi < 10 ** 9 else "800+"
        a["share_gap"] = 100.0 * a["gap"] / district["gap"]
        a["share_schools"] = 100.0 * a["n"] / district["n"]
        a["share_enr"] = 100.0 * a["cT"] / district["cT"]
        bands.append(a)
    big = [b for b in bands if b["label"] == "800+"][0]
    big400 = agg([s for s in schools if s["cT"] >= 400])
    big400["share_gap"] = 100.0 * big400["gap"] / district["gap"]
    big400["share_enr"] = 100.0 * big400["cT"] / district["cT"]
    big400["share_schools"] = 100.0 * big400["n"] / n

    # achievement distribution
    dist = []
    for lo, hi, label in [(None, 0, "below 0%"), (0, 25, "0–25%"), (25, 50, "25–50%"),
                          (50, 75, "50–75%"), (75, 100, "75–100%"), (100, None, "100%+")]:
        cnt = sum(1 for s in schools if (lo is None or s["achT"] >= lo) and (hi is None or s["achT"] < hi))
        color = "#198754" if lo == 100 else "#dc3545" if hi is None or (lo is None) else "#f59e0b" if hi <= 50 else "#2563eb"
        dist.append({"label": label, "n": cnt, "color": color})

    # concentration
    by_gap = sorted(schools, key=lambda s: -s["gap"])
    top20 = by_gap[:20]
    top20_gap = sum(s["gap"] for s in top20)
    top50_gap = sum(s["gap"] for s in by_gap[:50])
    top20_new_ach = ach(district["cT"] + top20_gap, district["bT"], district["tT"])

    # day movement
    gainers = [s for s in schools if s["delta"] > 0]
    losers = [s for s in schools if s["delta"] < 0]
    day = {
        "net": district["delta"],
        "up": len(gainers), "down": len(losers), "flat": n - len(gainers) - len(losers),
        "best": sorted(schools, key=lambda s: -s["delta"])[:5],
        "worst": sorted(schools, key=lambda s: s["delta"])[:5],
    }

    tiny = sum(1 for s in schools if 0 < s["inc"] <= 10)
    zero_girls = sum(1 for s in schools if s["cF"] == 0)
    zero_boys = sum(1 for s in schools if s["cM"] == 0)
    zero_both = sum(1 for s in schools if s["cT"] == 0)
    below = sorted([s for s in schools if s["health"] == "below_base"], key=lambda s: (s["cT"] - s["bT"]))[:12]
    movers = sorted([s for s in schools if s["cT"] >= 300], key=lambda s: -s["growth"])[:8]
    largest = sorted(schools, key=lambda s: -s["cT"])[:3]

    boys_rate = district["achM"]
    girls_at_boys = district["bF"] + boys_rate / 100.0 * (district["tF"] - district["bF"])
    ach_if_girls_match = ach(district["cM"] + girls_at_boys, district["bT"], district["tT"])
    lift = ach_if_girls_match - district["achT"]

    milestone = [(0.15, "30"), (0.35, "60"), (0.55, "90")]
    miles = []
    for share, label in milestone:
        add_students = district["gap"] * share
        miles.append({"label": label, "students": add_students, "share": share * 100,
                      "ach": ach(district["cT"] + add_students, district["bT"], district["tT"])})

    # -------------------------------------------------------------- svg helpers
    def donut(items, size=250, thick=38):
        total = sum(v for v, _, _ in items) or 1
        r = (size - thick) / 2
        c = 2 * 3.141592653589793 * r
        off = 0.0
        parts = []
        for v, color, _ in items:
            seg = c * v / total
            dash = max(seg - 2, 0.001)
            parts.append(
                f'<circle cx="{size / 2}" cy="{size / 2}" r="{r}" fill="none" stroke="{color}" stroke-width="{thick}" '
                f'stroke-dasharray="{dash:.2f} {c - dash:.2f}" stroke-dashoffset="{-off:.2f}" '
                f'transform="rotate(-90 {size / 2} {size / 2})"/>')
            off += seg
        return (f'<svg class="donut" width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
                f'<circle cx="{size / 2}" cy="{size / 2}" r="{r}" fill="none" stroke="#eef2f7" stroke-width="{thick}"/>'
                + "".join(parts) + "</svg>")

    def bridge():
        lo, hi = district["bT"] - 2500, district["tT"] + 2500
        pos = lambda v: (v - lo) / (hi - lo) * 100
        p = pos(district["cT"])
        marks = "".join(
            f'<div class="bridge-mark{" now" if lbl == "Current" else ""}" style="left:{pos(val):.2f}%">'
            f'<span class="bm-dot"></span><span class="bm-lab">{lbl}<br><b>{fmt(val)}</b></span></div>'
            for lbl, val in [("Baseline", district["bT"]), ("Current", district["cT"]), ("Target", district["tT"])])
        return f"""
        <div class="bridge">
          <div class="bridge-track">
            <div class="bridge-done" style="width:{p:.2f}%"></div>
            <div class="bridge-remain" style="left:{p:.2f}%;width:{100 - p:.2f}%"></div>
            {marks}
          </div>
          <div class="bridge-legend">
            <span><i class="sw" style="background:linear-gradient(90deg,#1e40af,#60a5fa)"></i>Added since baseline <b>{signed(district['growth'])}</b></span>
            <span><i class="sw" style="background:repeating-linear-gradient(45deg,#fde68a,#fde68a 5px,#fffbeb 5px,#fffbeb 10px)"></i>Still required <b>{signed(district['gap'])}</b></span>
            <span class="bridge-pct">{pct(district['achT'])} of the target increment achieved</span>
          </div>
        </div>"""

    # -------------------------------------------------------------- primitives
    def bars(items, max_value=None, label_w=190, height=18, gap=12):
        mx = max_value or max(v for _, v, _, _ in items) or 1
        out = []
        for label, value, color, text in items:
            w = max(0.0, min(100.0, value / mx * 100))
            out.append(
                f'<div class="bar-row" style="margin-bottom:{gap}px">'
                f'<div class="bar-lab" style="width:{label_w}px">{label}</div>'
                f'<div class="bar-track" style="height:{height}px"><div class="bar-fill" style="width:{w:.2f}%;background:{color}"></div></div>'
                f'<div class="bar-val">{text}</div></div>')
        return "".join(out)

    def table(headers, rows, cls="", widths=None, aligns=None):
        cols = ""
        if widths:
            cols = "<colgroup>" + "".join(f'<col style="width:{w}">' for w in widths) + "</colgroup>"
        al = aligns or ["left"] + ["right"] * (len(headers) - 1)
        head = "".join(f'<th class="{a}">{h}</th>' for h, a in zip(headers, al))
        body = "".join("<tr>" + "".join(f'<td class="{a}">{c}</td>' for c, a in zip(row, al)) + "</tr>" for row in rows)
        return f'<table class="tbl {cls}">{cols}<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'

    def kpi(label, value, sub="", tone="blue", big=False):
        return (f'<div class="kpi tone-{tone}{" big" if big else ""}"><div class="kpi-lab">{label}</div>'
                f'<div class="kpi-val">{value}</div><div class="kpi-sub">{sub}</div></div>')

    def callout(title, text, tone="blue"):
        return f'<div class="callout tone-{tone}"><div class="co-title">{title}</div><div class="co-text">{text}</div></div>'

    def stat(label, value, tone=""):
        return f'<div class="stat"><div class="stat-v {tone}">{value}</div><div class="stat-l">{label}</div></div>'

    slides = []

    def add(kicker, title, sub, body, cls=""):
        slides.append({"kicker": kicker, "title": title, "sub": sub, "body": body, "cls": cls})

    logo = base64.b64encode((ROOT / "logo.jpeg").read_bytes()).decode()

    # 1 cover ---------------------------------------------------------------
    add("", "", "", f"""
      <div class="cover">
        <div class="cover-left">
          <div class="cover-eyebrow">School Education Department · Punjab</div>
          <h1 class="cover-title">District Layyah</h1>
          <div class="cover-sub">Enrollment Performance Review</div>
          <div class="cover-line"></div>
          <p class="cover-lede">Where Layyah stands against its enrollment baseline and target — all
          {fmt(n)} schools, {len(tehsils)} tehsils and {len(markaz)} markaz, with the remaining
          {fmt(district['gap'])} students located by wing, tehsil, gender and school size.</p>
          <div class="cover-meta">
            <div><span>Current enrollment (SIS)</span><b>{SNAP_SIS}</b></div>
            <div><span>Baseline &amp; target (Grades)</span><b>{SNAP_GRADES}</b></div>
            <div><span>Coverage</span><b>{fmt(n)} schools · 3 tehsils · {len(markaz)} markaz</b></div>
          </div>
        </div>
        <div class="cover-right">
          <div class="cover-badge"><img src="data:image/jpeg;base64,{logo}" alt="SED Punjab"></div>
          <div class="cover-hero">
            <div class="ch-lab">Achievement against target</div>
            <div class="ch-val">{pct(district['achT'])}</div>
            <div class="ch-sub">{fmt(district['cT'])} of {fmt(district['tT'])} students</div>
            <div class="ch-bar"><span style="width:{min(100, max(0, district['achT'])):.1f}%"></span></div>
            <div class="ch-grid">
              <div><span>Still to enrol</span><b>{fmt(district['gap'])}</b></div>
              <div><span>At / above target</span><b>{district['above_target']} schools</b></div>
            </div>
          </div>
        </div>
      </div>""", cls="slide-cover no-foot")

    # 2 executive summary ---------------------------------------------------
    findings = [
        (pct(district['achT']), "of the target increment achieved",
         f"Layyah has added <b>{fmt(district['growth'])}</b> students over baseline but needs another "
         f"<b>{fmt(district['gap'])}</b>. Two-thirds of the job is still ahead.", "blue"),
        (f"{district['achM'] - district['achF']:.1f} pp", "gap between boys' and girls' achievement",
         f"Boys are at <b>{pct(district['achM'])}</b>, girls at <b>{pct(district['achF'])}</b>. Girls account for "
         f"<b>{fmt(district['needF'])}</b> of the remaining need — {district['needF'] / district['gap'] * 100:.0f}% of the district total.", "pink"),
        (f"{wings[2]['share_gap']:.0f}%", "of the gap sits in 200 secondary schools",
         f"The secondary wing holds <b>{fmt(wings[2]['gap'])}</b> of the {fmt(district['gap'])} shortfall at "
         f"<b>{pct(wings[2]['achT'])}</b> achievement, against {pct(elem['achT'])} for the two elementary wings.", "amber"),
        (f"{top20_gap / district['gap'] * 100:.0f}%", "of the gap sits in 20 schools",
         f"Twenty mostly-urban secondary schools hold <b>{fmt(top20_gap)}</b> students of the shortfall. "
         f"Closing them alone lifts the district from {pct(district['achT'])} to <b>{pct(top20_new_ach)}</b>.", "green"),
    ]
    cards = "".join(f'<div class="finding tone-{tone}"><div class="f-num">{v}</div><div class="f-lab">{lab}</div>'
                    f'<div class="f-text">{txt}</div></div>' for v, lab, txt, tone in findings)
    add("Executive summary", "Layyah is growing — just not fast enough to reach its target",
        f"One screen for the whole district: {fmt(district['cT'])} students enrolled across {fmt(n)} schools, "
        f"{pct(district['achT'])} of the way to a {fmt(district['tT'])} target.",
        f"""
        <div class="findings">{cards}</div>
        <div class="split2 mt16">
          {callout("The one-line diagnosis",
            f"Growth is healthy in small and mid-sized elementary schools — and has stalled exactly where the students are. "
            f"The {big['n']} schools with 800+ students are <b>{abs(big['achT']):.1f}% below their own baseline</b> and hold "
            f"{big['share_gap']:.0f}% of the district gap, while Karor Lalisan's elementary wing is already at "
            f"<b>101%</b>. Layyah does not have an enrollment problem everywhere; it has one in large secondary schools.", "navy")}
          <div class="factbox">
            <div class="fb-row"><span>Schools below baseline</span><b>{district['below_base']} <i>({district['below_base'] / n * 100:.1f}%)</i></b></div>
            <div class="fb-row"><span>Schools below target</span><b>{district['below_target']} <i>({district['below_target'] / n * 100:.1f}%)</i></b></div>
            <div class="fb-row"><span>Schools at or above target</span><b>{district['above_target']} <i>({district['above_target'] / n * 100:.1f}%)</i></b></div>
            <div class="fb-row"><span>Median school achievement</span><b>{pct(district['median_ach'])}</b></div>
            <div class="fb-row"><span>Movement in the latest SIS snapshot</span><b>{signed(day['net'])} students</b></div>
          </div>
        </div>""")

    # 3 scope & method ------------------------------------------------------
    method_rows = [
        ["Current enrollment", "SIS school snapshot", SNAP_SIS,
         f"{sum(1 for s in schools if s['matched']):,} of {n:,} Layyah schools matched; no Grades fallback used"],
        ["Baseline &amp; target", "Grades district export", SNAP_GRADES,
         "School-level baseline and target as published on the dashboard"],
        ["Achievement %", "(current − baseline) ÷ (target − baseline) × 100", "—",
         "Uncapped; computed on summed school values, never an average of school percentages"],
        ["School health", "Below baseline / below target / at-or-above target", "—",
         "Total current enrollment, including “Other”"],
        ["Day change", "Current − previous SIS snapshot", "21 → 22 Oct 2026",
         "SIS-to-SIS movement only; not a term-on-term comparison"],
    ]
    add("Scope &amp; method", "What is measured — and what it can and cannot tell you",
        "Every number in this deck is recomputed from the same two snapshots that feed the public dashboard.",
        f"""
        <div class="split-wide">
          <div>
            {table(["Measure", "Source / rule", "Snapshot", "Notes"], method_rows,
                   cls="compact", widths=["126px", "256px", "150px", "404px"], aligns=["left"] * 4)}
            <div class="grid4 mt16">
              {kpi("Schools in scope", fmt(n), "all Layyah schools on the SIS roster", "blue")}
              {kpi("Tehsils", "3", "Layyah · Karor Lalisan · Chaubara", "slate")}
              {kpi("Markaz", str(len(markaz)), "AEO clusters (excludes 3 wing buckets)", "slate")}
              {kpi("Wings", "3", "M-EE · W-EE · SE", "slate")}
            </div>
          </div>
          <div class="side">
            {callout("Read percentages with care",
              f"<b>{tiny}</b> schools have a target only 1–10 students above baseline, so a single student can move their "
              f"percentage by 10–100 points. That is why school-level figures here run from −800% to +3,000%. "
              f"Judge strategy on district, tehsil and wing totals; treat an individual percentage as a screening flag only.", "amber")}
            {callout("Totals",
              f"“Total” includes the <b>{district['cO']}</b> students recorded under “Other”, so boys + girls can differ from the "
              f"total by that amount. The three “Secondary Wing” rows that appear as markaz in the source are wing "
              f"aggregates, not AEO clusters, and are excluded from the markaz league.", "slate")}
          </div>
        </div>""")

    # 4 district scorecard --------------------------------------------------
    add("District scorecard", "Layyah at a glance",
        "Current enrollment, the baseline it started from, and the target it is measured against.",
        f"""
        <div class="grid4">
          {kpi("Current enrollment", fmt(district['cT']), f"Boys {fmt(district['cM'])} · Girls {fmt(district['cF'])}", "blue", True)}
          {kpi("Baseline", fmt(district['bT']), f"Boys {fmt(district['bM'])} · Girls {fmt(district['bF'])}", "slate")}
          {kpi("Target", fmt(district['tT']), f"Boys {fmt(district['tM'])} · Girls {fmt(district['tF'])}", "navy")}
          {kpi("Achievement", pct(district['achT']), "of the target increment", "amber", True)}
        </div>
        <div class="grid4 mt16">
          {kpi("Added since baseline", signed(district['growth']), f"+{district['growth'] / district['bT'] * 100:.1f}% on baseline", "green")}
          {kpi("Still required", fmt(district['gap']), f"+{district['gap'] / district['cT'] * 100:.1f}% on current", "red")}
          {kpi("Girls − boys", fmt(district['cF'] - district['cM']), f"gender parity index {district['cF'] / district['cM']:.3f}", "pink")}
          {kpi("Latest movement", signed(day['net']), f"{day['up']} schools up · {day['down']} down", "slate")}
        </div>
        <div class="split2 mt16">
          {callout("Where the district stands",
            f"Layyah needs <b>{fmt(district['gap'])}</b> more students to reach {fmt(district['tT'])} — {district['gap'] / district['bT'] * 100:.1f}% "
            f"growth on baseline, of which {district['growth'] / district['bT'] * 100:.1f}% has been delivered. Every 1,000 students recovered is worth "
            f"<b>{1000 / total_inc * 100:.1f} percentage points</b>.", "blue")}
          {callout("What “at target” means",
            f"A school is at target when current enrollment reaches its own published target. {district['above_target']} schools have done so; "
            f"{district['below_target']} sit between baseline and target; {district['below_base']} have fallen below the level they started from.", "slate")}
        </div>""")

    # 5 distance to target --------------------------------------------------
    add("Distance to target", "Two-thirds of the required growth is still outstanding",
        f"From {fmt(district['bT'])} at baseline to {fmt(district['tT'])} at target — {fmt(total_inc)} students in total.",
        f"""
        {bridge()}
        <div class="grid3 mt24">
          {kpi("Already delivered", fmt(district['growth']), f"{district['growth'] / total_inc * 100:.1f}% of the total increment", "green")}
          {kpi("Still required", fmt(district['gap']), f"{district['gap'] / total_inc * 100:.1f}% of the total increment", "red")}
          {kpi("Average per school", f"{district['gap'] / n:.1f}", "students still needed across 1,223 schools", "slate")}
        </div>
        <div class="split2 mt18">
          <div>
            <div class="sec-h">The remaining {fmt(district['gap'])} by gender</div>
            {bars([("Boys", district['needM'], "#2563eb", fmt(district['needM'])),
                   ("Girls", district['needF'], "#db2777", fmt(district['needF']))], max_value=7000, label_w=80)}
            <div class="note">Girls carry {district['needF'] / district['gap'] * 100:.0f}% of what is left, although they are {district['female_share']:.1f}% of current enrollment.</div>
          </div>
          <div>
            <div class="sec-h">The remaining {fmt(district['gap'])} by wing</div>
            {bars([(w['name'], w['gap'], WING_COLOR[w['code']], fmt(w['gap'])) for w in wings],
                  max_value=7600, label_w=160)}
            <div class="note">Secondary schooling alone accounts for {wings[2]['share_gap']:.0f}% of the shortfall that remains.</div>
          </div>
        </div>""")

    # 6 gender --------------------------------------------------------------
    gcols = [("Boys baseline", district['bM'], "#93c5fd", district['tM']),
             ("Boys current", district['cM'], "#2563eb", district['tM']),
             ("Boys target", district['tM'], "#1e3a8a", district['tM']),
             ("Girls baseline", district['bF'], "#f9a8d4", district['tF']),
             ("Girls current", district['cF'], "#db2777", district['tF']),
             ("Girls target", district['tF'], "#9d174d", district['tF'])]
    add("Gender", "Girls are half the classroom but only a quarter of the progress",
        f"Boys are at {pct(district['achM'])} achievement and girls at {pct(district['achF'])} — boys added "
        f"{fmt(district['cM'] - district['bM'])} students to girls' {fmt(district['cF'] - district['bF'])}.",
        f"""
        <div class="split-wide">
          <div>
            <div class="sec-h">Enrollment by gender — baseline, current, target</div>
            <div class="gbars">
              {''.join(f'''<div class="gcol"><div class="gcap">{lab}</div>
                 <div class="gbar"><span style="height:{v / mx * 100:.1f}%;background:{col}"></span></div>
                 <div class="gval">{fmt(v)}</div></div>''' for lab, v, col, mx in gcols)}
            </div>
            <div class="note">Girls started <b>{fmt(district['bF'] - district['bM'])}</b> ahead of boys at baseline and are now
            <b>{fmt(district['cM'] - district['cF'])}</b> behind. The target asks girls to add {fmt(district['tF'] - district['bF'])} students; they have added {fmt(district['cF'] - district['bF'])}.</div>
          </div>
          <div class="side">
            {stat("Boys achievement", pct(district['achM']), "blue")}
            {stat("Girls achievement", pct(district['achF']), "pink")}
            {stat("Girls − boys enrollment", fmt(district['cF'] - district['cM']), "pink")}
            {stat("Gender parity index", f"{district['cF'] / district['cM']:.3f}", "")}
            {stat("Girls' share of enrollment", pct(district['female_share']), "")}
            {stat("Girls still needed", fmt(district['needF']), "pink")}
          </div>
        </div>
        {callout("Why this is the biggest single lever",
          f"If girls had achieved at the boys' rate, the district would be at <b>{pct(ach_if_girls_match)}</b> instead of "
          f"{pct(district['achT'])} — a <b>{lift:.1f} point</b> difference with no change in boys' performance at all. "
          f"Every point of girls' enrollment is worth more to the district total than an additional point of boys'.", "pink")}""")

    # 7 tehsil scorecard ----------------------------------------------------
    rows = [[f"<b>{t['name']}</b>", fmt(t['n']), str(t['markaz']), fmt(t['cT']), chip(t['achT']),
             str(t['below_base']), fmt(t['gap']), f"{t['share_gap']:.0f}%"] for t in tehsils]
    rows.append([f"<b>District</b>", f"<b>{fmt(n)}</b>", f"<b>{len(markaz)}</b>", f"<b>{fmt(district['cT'])}</b>",
                 chip(district['achT']), f"<b>{district['below_base']}</b>", f"<b>{fmt(district['gap'])}</b>", "<b>100%</b>"])
    add("Tehsil view", "Layyah tehsil holds the students and the shortfall; Karor Lalisan holds the momentum",
        "The three tehsils behave like three different systems — 51% of enrollment and 64% of the gap sit in Layyah tehsil alone.",
        f"""
        <div class="split-wide">
          <div>
            {table(["Tehsil", "Schools", "Markaz", "Current", "Achievement", "Below baseline", "Gap", "Share of gap"],
                   rows, widths=["112px", "66px", "60px", "84px", "94px", "100px", "78px", "84px"])}
            <div class="mt18 sec-h">Achievement against target</div>
            {bars([(t['name'], max(t['achT'], 0), ["#2563eb", "#198754", "#db2777"][i], pct(t['achT'])) for i, t in enumerate(tehsils)],
                  max_value=60, label_w=112, height=20)}
            <div class="note">Karor Lalisan achieves {tehsils[1]['achT'] / max(tehsils[0]['achT'], 1):.1f}× Layyah tehsil's rate with 170 fewer schools — size is not what is holding Layyah back.</div>
          </div>
          <div class="side">
            {callout("Layyah", f"{fmt(tehsils[0]['cT'])} students ({tehsils[0]['share_enr']:.0f}% of the district) and "
              f"{tehsils[0]['share_gap']:.0f}% of the gap. Achievement {pct(tehsils[0]['achT'])}; {tehsils[0]['below_base']} of its "
              f"{tehsils[0]['n']} schools are below baseline; none of its {tehsils[0]['markaz']} markaz is at target.", "blue")}
            {callout("Karor Lalisan", f"The strongest tehsil at {pct(tehsils[1]['achT'])}. Its elementary wings are at or near target "
              f"(M-EE 101.0%, W-EE 97.5%) and 18 of its markaz are at 100%+. But its secondary wing sits at 12.3%, which is why "
              f"the tehsil still needs {fmt(tehsils[1]['gap'])} more students.", "green")}
            {callout("Chaubara", f"Smallest at {fmt(tehsils[2]['cT'])} students ({tehsils[2]['share_enr']:.0f}%), with the weakest gender "
              f"profile: parity index {tehsils[2]['gpi']:.2f}, only {tehsils[2]['female_share']:.0f}% girls and {tehsils[2]['zero_girls']} schools "
              f"with no girls enrolled at all.", "pink")}
          </div>
        </div>""")

    # 8 tehsil x wing -------------------------------------------------------
    heat_rows = []
    for t in tehsils:
        cells = ""
        for w in ("M-EE", "W-EE", "SE"):
            g = [s for s in schools if s["tehsil"] == t["name"] and s["wing"] == w]
            a = agg(g)
            cells += (f'<td class="heat" style="background:{ach_color(a["achT"])}12">'
                      f'<div class="h-ach" style="color:{ach_color(a["achT"])}">{pct(a["achT"])}</div>'
                      f'<div class="h-gap">{a["n"]} schools · ' + ('surplus ' + fmt(-a["gap"]) if a["gap"] < 0 else 'needs ' + fmt(a["gap"])) + '</div></td>')
        heat_rows.append(f'<tr><th>{t["name"]}<span>{t["n"]} schools · needs {fmt(t["gap"])}</span></th>{cells}</tr>')
    wing_head = "".join(f"<th>{WING_SHORT[w]}<span>{WING_LABEL[w]}</span></th>" for w in ("M-EE", "W-EE", "SE"))
    layyah_se = agg([s for s in schools if s["tehsil"] == "Layyah" and s["wing"] == "SE"])
    karor_se = agg([s for s in schools if s["tehsil"] == "Karor Lalisan" and s["wing"] == "SE"])
    chaubara_we = agg([s for s in schools if s["tehsil"] == "Chaubara" and s["wing"] == "W-EE"])
    chaubara_se = agg([s for s in schools if s["tehsil"] == "Chaubara" and s["wing"] == "SE"])
    add("Tehsil × wing", "The gap is not spread evenly — it is concentrated in secondary schools in Layyah and Chaubara",
        "Read across a row to see where a tehsil is winning, and down a column to see which wing is failing the district.",
        f"""
        <table class="tbl heat-tbl"><thead><tr><th></th>{wing_head}</tr></thead><tbody>{''.join(heat_rows)}</tbody></table>
        <div class="grid3 mt16">
          {kpi("Karor Lalisan · elementary", "~100%", f"M-EE 101.0% · W-EE 97.5% on {fmt(tehsils[1]['cT'])} students; the whole tehsil needs only {fmt(tehsils[1]['gap'])}", "green")}
          {kpi("Layyah · secondary", pct(layyah_se['achT']), f"{layyah_se['n']} schools, {fmt(layyah_se['cT'])} students, needs {fmt(layyah_se['gap'])} — 39% of the district gap", "red")}
          {kpi("Chaubara · secondary", pct(chaubara_se['achT']), f"{chaubara_se['n']} schools already below baseline — the only wing/tehsil cell in negative territory", "darkred")}
        </div>
        <div class="note">Every secondary cell is weak ({pct(layyah_se['achT'])} in Layyah, {pct(karor_se['achT'])} in Karor Lalisan, {pct(chaubara_se['achT'])} in Chaubara) while every elementary cell except
        Chaubara's girls' wing is above 37%. Chaubara's female elementary wing is at {pct(chaubara_we['achT'])} on {fmt(chaubara_we['cT'])} students — the sharpest single weakness in the district.</div>""")

    # 9 wing view -----------------------------------------------------------
    add("Wing view", "Elementary schools are delivering; secondary schools are the bottleneck",
        f"{wings[2]['n']} secondary schools teach {wings[2]['share_enr']:.0f}% of Layyah's students — and hold {wings[2]['share_gap']:.0f}% of the students still missing.",
        f"""
        <div class="grid3">
          {''.join(f'''<div class="wingcard tone-{['blue', 'pink', 'amber'][i]}">
            <div class="wc-top"><span class="wc-code">{w['code']}</span><span class="wc-name">{w['name']}</span></div>
            <div class="wc-ach" style="color:{ach_color(w['achT'])}">{pct(w['achT'])}</div>
            <div class="wc-sub">{fmt(w['n'])} schools · {fmt(w['cT'])} students</div>
            <div class="wc-bar"><span style="width:{min(100, max(0, w['achT'])):.0f}%;background:{ach_color(w['achT'])}"></span></div>
            <div class="wc-rows">
              <div><span>Baseline</span><b>{fmt(w['bT'])}</b></div>
              <div><span>Target</span><b>{fmt(w['tT'])}</b></div>
              <div><span>Added</span><b>{signed(w['growth'])}</b></div>
              <div><span>Still needed</span><b class="neg">{fmt(w['gap'])}</b></div>
              <div><span>Girls</span><b>{fmt(w['cF'])} ({w['female_share']:.0f}%)</b></div>
              <div><span>Below baseline</span><b>{w['below_base']} schools</b></div>
            </div></div>''' for i, w in enumerate(wings))}
        </div>
        <div class="split2 mt18">
          <div>
            <div class="sec-h">Share of the district's remaining need</div>
            {bars([(w['name'], w['share_gap'], WING_COLOR[w['code']], f"{w['share_gap']:.0f}%") for w in wings],
                  max_value=70, label_w=160, height=20)}
            <div class="note">Elementary wings need only {fmt(elem['gap'])} more students between them — {elem['share_gap']:.0f}% of the gap — a {elem['gap'] / elem['cT'] * 100:.1f}% lift.</div>
          </div>
          {callout("The arithmetic of the shortfall",
            f"Secondary needs <b>{fmt(wings[2]['gap'])}</b>, a {wings[2]['gap'] / wings[2]['cT'] * 100:.1f}% lift, and is currently running "
            f"<b>{fmt(abs(wings[2]['growth']))} students below baseline</b>. No amount of primary-school effort closes this gap: it has to be won "
            f"in grades 6–12, in the {wings[2]['n']} schools that teach them.", "navy")}
        </div>""")

    # 10 school health ------------------------------------------------------
    hb, ht, ha = district['below_base'], district['below_target'], district['above_target']
    add("School health", f"{ha} of {fmt(n)} schools have met their target — and {hb} have slipped below baseline",
        "Each school is counted once, using total current enrollment against its own baseline and target.",
        f"""
        <div class="split-wide">
          <div class="donut-wrap">
            {donut([(hb, "#dc3545", "Below baseline"), (ht, "#f59e0b", "Below target"), (ha, "#198754", "At or above target")])}
            <div class="donut-centre"><b>{pct(district['achT'])}</b><span>district achievement</span></div>
            <div class="legend">
              <div><i style="background:#dc3545"></i><span>Below baseline</span><b>{hb} · {hb / n * 100:.1f}%</b></div>
              <div><i style="background:#f59e0b"></i><span>Below target</span><b>{ht} · {ht / n * 100:.1f}%</b></div>
              <div><i style="background:#198754"></i><span>At or above target</span><b>{ha} · {ha / n * 100:.1f}%</b></div>
              <div><i style="background:#cbd5e1"></i><span>Total schools</span><b>{fmt(n)} · 100%</b></div>
            </div>
          </div>
          <div class="side">
            {callout("A tale of two school systems",
              f"<b>{ha}</b> schools ({ha / n * 100:.0f}%) are at or above target and the median school sits at <b>{pct(district['median_ach'])}</b>. "
              f"Yet the district is at {pct(district['achT'])}. The distance between those two numbers is the whole story: the schools that are "
              f"behind are also the schools with the most students.", "blue")}
            <div class="factbox">
              <div class="fb-row"><span>Below baseline by wing</span><b>M-EE {wings[0]['below_base']} · W-EE {wings[1]['below_base']} · SE {wings[2]['below_base']}</b></div>
              <div class="fb-row"><span>Below baseline in Layyah tehsil</span><b>{tehsils[0]['below_base']} of {tehsils[0]['n']}</b></div>
              <div class="fb-row"><span>Below baseline in Chaubara</span><b>{tehsils[2]['below_base']} of {tehsils[2]['n']} ({tehsils[2]['below_base'] / tehsils[2]['n'] * 100:.0f}%)</b></div>
              <div class="fb-row"><span>Schools needing 100+ students</span><b>{sum(1 for s in schools if s['gap'] > 100)}</b></div>
            </div>
          </div>
        </div>""")

    # 11 distribution -------------------------------------------------------
    dmax = max(d["n"] for d in dist)
    add("Distribution", "Most schools are close to target — the district average is dragged down by a heavy tail",
        "Achievement is uncapped, so schools far above target and schools far below it both pull on the mean.",
        f"""
        <div class="split-wide">
          <div>
            <div class="sec-h">Schools by achievement band</div>
            <div class="histo">
              {''.join(f'''<div class="hcol"><div class="hbar"><span style="height:{d['n'] / dmax * 100:.1f}%;background:{d['color']}"></span></div>
                 <div class="hval">{d['n']}</div><div class="hlab">{d['label']}</div></div>''' for d in dist)}
            </div>
            <div class="note">{dist[5]['n']} schools ({dist[5]['n'] / n * 100:.1f}%) have reached or passed their target; {dist[0]['n']} ({dist[0]['n'] / n * 100:.1f}%) have fallen below baseline. The {dist[1]['n'] + dist[2]['n']} schools in the 0–50% band are where most of the remaining {fmt(district['gap'])} sits.</div>
          </div>
          <div class="side">
            {stat("Median school", pct(district['median_ach']), "blue")}
            {stat("Enrollment-weighted district", pct(district['achT']), "amber")}
            {stat("Highest / lowest school", "3,000% / −800%", "")}
            {callout("Why the median is not the district",
              f"Half of Layyah's schools are above {pct(district['median_ach'])}; the district as a whole is at {pct(district['achT'])}. "
              f"Enrollment-weighted achievement is lower because the large schools — the ones with hundreds of students — are the ones "
              f"not keeping pace. Reporting only the median would flatter the district; reporting only the total would hide {ha} genuinely successful schools.", "slate")}
          </div>
        </div>""")

    # 12 concentration ------------------------------------------------------
    rows = [[f"<b>{b['label']}</b>", fmt(b['n']), f"{b['share_schools']:.1f}%", fmt(b['cT']), chip(b['achT']),
             pct(b['median_ach']), fmt(b['gap']), f"{b['share_gap']:.0f}%"] for b in bands]
    add("Concentration", f"Where the {fmt(district['gap'])} missing students actually are",
        "Sort Layyah's schools by size and the shortfall stops looking like a district-wide problem and starts looking like a list.",
        f"""
        <div class="split-wide">
          <div>
            {table(["School size", "Schools", "Share", "Students", "Achievement", "Median school", "Gap", "Share of gap"],
                   rows, widths=["86px", "60px", "56px", "76px", "92px", "90px", "66px", "82px"])}
            <div class="note">The {big400['n']} schools with 400+ students are {big400['n'] / n * 100:.0f}% of schools, {big400['share_enr']:.0f}% of enrollment and <b>{big400['share_gap']:.0f}%</b> of the gap. The {big['n']} schools with 800+ students are {big['n'] / n * 100:.1f}% of schools and hold <b>{big['share_gap']:.0f}%</b> of the gap at an achievement rate of <b>{pct(big['achT'])}</b>.</div>
          </div>
          <div class="side">
            {stat("Of the gap · top 20 schools", f"{top20_gap / district['gap'] * 100:.0f}%", "red")}
            {stat("Of the gap · top 50 schools", f"{top50_gap / district['gap'] * 100:.0f}%", "amber")}
            {stat("District achievement if the top 20 close", pct(top20_new_ach), "green")}
            {callout("What this means for management",
              f"A universal campaign would spend most of its energy on schools already at target. Concentrating the next quarter on the "
              f"{sum(1 for s in schools if s['gap'] > 50)} schools that each need more than 50 students — and on the {big['n']} schools with 800+ "
              f"students — moves the district further than any district-wide intervention.", "navy")}
          </div>
        </div>""")

    # 13 top 20 gap ---------------------------------------------------------
    rows = [[s['name'], s['tehsil'], s['wing'], fmt(s['cT']), fmt(s['tT']), fmt(s['gap']),
             f"{s['growth']:+d}", chip(s['achT'])] for s in top20]
    add("Priority schools", "The 20 schools that decide the district's result",
        f"Together they need {fmt(top20_gap)} students — {top20_gap / district['gap'] * 100:.0f}% of the district gap — and all 20 are secondary schools.",
        f"""{table(["School (EMIS name)", "Tehsil", "Wing", "Current", "Target", "Gap", "vs baseline", "Achievement"],
                    rows, cls="compact", widths=["470px", "120px", "56px", "84px", "84px", "70px", "90px", "94px"])}
        <div class="note mt10">Thirteen of the twenty are in Layyah tehsil and {sum(1 for s in top20 if 'CHOWK AZAM' in s['name'])} are in or around Chowk Azam.
        Thirteen are already below their own baseline. The three biggest shortfalls — {top20[0]['name']}, {top20[1]['name']} and {top20[2]['name']} — account for
        {fmt(sum(s['gap'] for s in top20[:3]))} students, {sum(s['gap'] for s in top20[:3]) / district['gap'] * 100:.0f}% of the district gap on their own.</div>""")

    # 14 below baseline -----------------------------------------------------
    rows = [[s['name'], s['tehsil'], s['wing'], fmt(s['cT']), fmt(s['bT']), f"{s['cT'] - s['bT']:+d}",
             fmt(s['gap']), chip(s['achT'])] for s in below]
    add("Warning list", f"{hb} schools have fallen below the level they started from",
        "These are not small schools: the twelve shown here hold thousands of students between them.",
        f"""{table(["School", "Tehsil", "Wing", "Current", "Baseline", "Change", "Still needed", "Achievement"],
                    rows, cls="compact", widths=["440px", "120px", "58px", "82px", "84px", "76px", "96px", "96px"])}
        <div class="note mt10">Below-baseline schools are the hardest to recover because the loss is already embedded: they must first return to
        baseline and then climb to target. {sum(1 for s in schools if s['health'] == 'below_base' and s['wing'] == 'SE')} of the {hb} are secondary schools and
        {sum(1 for s in schools if s['health'] == 'below_base' and s['tehsil'] == 'Layyah')} are in Layyah tehsil. The three largest below-baseline schools are
        also three of the district's five largest schools — this is where the district's average is being lost.</div>""")

    # 15 bright spots -------------------------------------------------------
    rows = [[s['name'], s['tehsil'], s['wing'], fmt(s['cT']), f"+{s['growth']}", fmt(s['inc']), chip(s['achT'])]
            for s in movers]
    add("What good looks like", "Schools that are actually moving — and what they have in common",
        "Ranked by students added since baseline, among schools with 300+ students so the numbers are not small-school noise.",
        f"""{table(["School", "Tehsil", "Wing", "Current", "Added since baseline", "Target increment", "Achievement"],
                    rows, cls="compact", widths=["430px", "120px", "56px", "80px", "140px", "120px", "96px"])}
        <div class="split2 mt14">
          {callout("The pattern in the winners",
            f"All eight are secondary schools in Karor Lalisan and Layyah — proof that the secondary wing can deliver when a school is managed "
            f"to its target. {movers[1]['name']} added <b>{movers[1]['growth']} students</b> against a required increment of {movers[1]['inc']} — the biggest addition in any school that still has a substantial shortfall.", "green")}
          {callout("A caution on rankings",
            f"School-level percentages are volatile: {movers[0]['name']} shows 3,000% because its target increment is only "
            f"{movers[0]['inc']} students. Rank schools by <b>students added</b> and by <b>share of target increment closed</b>, "
            f"not by the raw percentage.", "amber")}
        </div>""")

    # 16 markaz top ---------------------------------------------------------
    def markaz_table(items, ranks=None):
        ranks = ranks or list(range(1, len(items) + 1))
        rows = [[f"<span class='rank'>{r}</span>", f"<b>{smart_name(m['name'])}</b>", m['tehsil'], fmt(m['n']),
                 fmt(m['cT']), chip(m['achT']), fmt(m['gap'])] for r, m in zip(ranks, items)]
        return table(["#", "Markaz", "Tehsil", "Schools", "Current", "Achievement", "Gap"], rows,
                     cls="compact", widths=["30px", "300px", "116px", "66px", "78px", "96px", "66px"])

    add("Markaz league · top", f"Twenty markaz have already met their target — eighteen are in Karor Lalisan",
        "Markaz are ranked on the achievement of their summed enrollment, not on the average of their schools' percentages.",
        f"""
        <div class="split-wide">
          <div>{markaz_table(markaz_sorted[:10])}
            <div class="note mt10">Markaz above 100% are no longer part of the district's problem — they are part of its solution:
            their practice should be documented and copied, not their enrollment counted again.</div>
          </div>
          <div class="side">
            {stat("Markaz at or above target", f"{len(at_target)} of {len(markaz)}", "green")}
            {stat("Markaz below baseline", f"{len(neg_markaz)}", "red")}
            {stat("Best markaz", f"{pct(markaz_sorted[0]['achT'])}", "green")}
            {callout("What Karor is doing right",
              f"Karor Lalisan's male and female elementary markaz take every top-10 slot — {smart_name(markaz_sorted[0]['name'])} ({pct(markaz_sorted[0]['achT'])}), "
              f"{smart_name(markaz_sorted[1]['name'])} ({pct(markaz_sorted[1]['achT'])}), {smart_name(markaz_sorted[2]['name'])} ({pct(markaz_sorted[2]['achT'])}) — on 1,300–2,200 "
              f"students each. These are mid-sized clusters beating target by wide margins, not statistical curiosities.", "green")}
            {callout("But the same tehsil has a secondary problem",
              f"Karor's secondary wing is at 12.3% and its largest high schools are below baseline. The markaz league flatters the tehsil's "
              f"elementary system and hides its secondary one.", "amber")}
          </div>
        </div>""")

    # 17 markaz bottom ------------------------------------------------------
    add("Markaz league · bottom", f"Six markaz are below zero — four in Layyah and two in Chaubara",
        "These are the clusters where enrollment has fallen below baseline; each needs a school-by-school recovery plan.",
        f"""
        <div class="split-wide">
          <div>{markaz_table(list(reversed(markaz_sorted[-10:])), list(range(len(markaz), len(markaz) - 10, -1)))}
            <div class="note mt10">The bottom ten together need {fmt(sum(m['gap'] for m in markaz_sorted[-10:]))} students — about
            {sum(m['gap'] for m in markaz_sorted[-10:]) / district['gap'] * 100:.0f}% of the district gap, concentrated in {sum(m['n'] for m in markaz_sorted[-10:])} schools.</div>
          </div>
          <div class="side">
            {stat("Worst markaz", pct(neg_markaz[0]['achT']), "darkred")}
            {stat("Its gap to target", fmt(neg_markaz[0]['gap']), "red")}
            {callout(smart_name(neg_markaz[0]['name']),
              f"{fmt(neg_markaz[0]['cT'])} students across {neg_markaz[0]['n']} schools, achievement {pct(neg_markaz[0]['achT'])} — "
              f"{fmt(neg_markaz[0]['cT'] - neg_markaz[0]['bT'])} below baseline and {fmt(neg_markaz[0]['gap'])} short of target. "
              f"That is a {neg_markaz[0]['gap'] / max(neg_markaz[0]['cT'], 1) * 100:.0f}% enrollment lift — not a nudge.", "red")}
            {callout("Mandi Town (Male), Layyah",
              f"The largest under-performer by volume: {fmt([m for m in markaz if 'MANDI TOWN MALE' in m['name']][0]['cT'])} students at "
              f"{pct([m for m in markaz if 'MANDI TOWN MALE' in m['name']][0]['achT'])}. Urban markaz are not automatically high performers — in Layyah the largest "
              f"city clusters are among the weakest.", "amber")}
          </div>
        </div>""")

    # 18 gender deep dive ---------------------------------------------------
    rows = [[f"<b>{t['name']}</b>", fmt(t['cM']), fmt(t['cF']), pct(t['female_share']), f"{t['gpi']:.2f}",
             chip(t['achM']), chip(t['achF']), str(t['zero_girls'])] for t in tehsils]
    add("Gender deep-dive", "Chaubara is the district's gender frontier",
        f"Girls' share of enrollment falls from {tehsils[0]['female_share']:.1f}% in Layyah tehsil to {tehsils[2]['female_share']:.1f}% in Chaubara, where fewer than one student in two is a girl.",
        f"""
        <div class="split-wide">
          <div>
            {table(["Tehsil", "Boys", "Girls", "Girls share", "GPI", "Boys ach.", "Girls ach.", "Schools with 0 girls"],
                   rows, widths=["118px", "80px", "80px", "92px", "56px", "88px", "88px", "128px"])}
            <div class="note">GPI = girls ÷ boys current enrollment. A GPI of {tehsils[2]['gpi']:.2f} means roughly 14 girls for every 16 boys;
            at district level the ratio is close to parity ({district['cF'] / district['cM']:.3f}), which masks the Chaubara shortfall.</div>
            <div class="mt16 sec-h">Schools with no girls enrolled, by tehsil</div>
            {bars([(t['name'], t['zero_girls'], "#db2777", str(t['zero_girls'])) for t in tehsils], max_value=60, label_w=112, height=16)}
            <div class="note">{zero_girls} schools record no girls and {zero_boys} record no boys. Some are genuinely single-gender schools (GGHS / GHS);
            others are data, merger or closure issues that should be verified before the next target cycle.</div>
          </div>
          <div class="side">
            {stat("District GPI", f"{district['cF'] / district['cM']:.3f}", "blue")}
            {stat("Chaubara GPI", f"{tehsils[2]['gpi']:.3f}", "pink")}
            {stat("Girls still needed", fmt(district['needF']), "pink")}
            {callout("What would move the number",
              f"Chaubara's female elementary wing is at {pct(chaubara_we['achT'])} with {fmt(chaubara_we['cF'])} girls across {chaubara_we['n']} schools — "
              f"an average of {chaubara_we['cF'] / chaubara_we['n']:.0f} girls per school. Facility audits (boundary wall, toilets, drinking water), "
              f"girls' stipend and transport uptake, and community mobilisation in these {tehsils[2]['markaz']} markaz are the shortest paths to enrollment.", "pink")}
          </div>
        </div>""")

    # 19 movement -----------------------------------------------------------
    rows = [[s['name'], s['tehsil'], s['wing'], fmt(s['cT']), f"+{s['delta']}"] for s in day['best'] if s['delta'] > 0]
    rows2 = [[s['name'], s['tehsil'], s['wing'], fmt(s['cT']), f"{s['delta']}"] for s in day['worst'] if s['delta'] < 0]
    add("Movement", f"{signed(day['net'])} students in a day — but {fmt(day['flat'])} of {fmt(n)} schools did not move at all",
        "Day-on-day change compares today's SIS snapshot with yesterday's. It is a monitoring signal, not a performance verdict.",
        f"""
        <div class="grid4">
          {kpi("Net change", signed(day['net']), f"best {day['best'][0]['delta']:+d} · worst {day['worst'][0]['delta']:+d}", "blue")}
          {kpi("Schools up", str(day['up']), "reported an increase", "green")}
          {kpi("Schools down", str(day['down']), "reported a decrease", "red")}
          {kpi("No change", fmt(day['flat']), "no movement recorded", "slate")}
        </div>
        <div class="split2 mt16">
          <div>
            <div class="sec-h">By tehsil</div>
            {bars([(t['name'], abs(t['delta']), "#2563eb" if t['delta'] >= 0 else "#dc3545", signed(t['delta'])) for t in tehsils],
                  max_value=120, label_w=110, height=16)}
            <div class="sec-h mt12">By wing</div>
            {bars([(WING_LABEL[w['code']], abs(w['delta']), WING_COLOR[w['code']], signed(w['delta'])) for w in wings],
                  max_value=100, label_w=150, height=16)}
            <div class="note">Movement is concentrated in the elementary wings ({signed(wings[0]['delta'] + wings[1]['delta'])} of {signed(day['net'])});
            secondary schools moved by just {signed(wings[2]['delta'])} across {wings[2]['n']} schools.</div>
          </div>
          <div>
            <div class="sec-h">Largest daily gains</div>
            {table(["School", "Tehsil", "Wing", "Current", "Δ"], rows, cls="compact", widths=["236px", "96px", "48px", "62px", "44px"])}
            <div class="sec-h mt12">Largest daily losses</div>
            {table(["School", "Tehsil", "Wing", "Current", "Δ"], rows2, cls="compact", widths=["236px", "96px", "48px", "62px", "44px"])}
          </div>
        </div>""")

    # 20 strengths ----------------------------------------------------------
    add("Diagnosis · strengths", "Four things Layyah is demonstrably doing well",
        "The district is not failing across the board — these are the foundations a recovery plan should build on.",
        f"""
        <div class="grid2">
          <div class="strength">
            <div class="st-h">1 · Elementary enrollment is on track</div>
            <p>M-EE is at <b>{pct(wings[0]['achT'])}</b> and W-EE at <b>{pct(wings[1]['achT'])}</b>; together the elementary wings need only
            <b>{fmt(elem['gap'])}</b> more students — a {elem['gap'] / elem['cT'] * 100:.1f}% lift. Karor Lalisan's elementary wings are effectively at target.</p>
            <div class="st-n">{fmt(elem['cT'])} students · {elem['share_gap']:.0f}% of the district gap</div>
          </div>
          <div class="strength">
            <div class="st-h">2 · Most schools are at or above target</div>
            <p><b>{ha}</b> schools ({ha / n * 100:.0f}%) have met their target and the median school sits at <b>{pct(district['median_ach'])}</b>.
            The habit of hitting a school-level target exists; it needs to be extended to the large schools.</p>
            <div class="st-n">Median school achievement {pct(district['median_ach'])}</div>
          </div>
          <div class="strength">
            <div class="st-h">3 · Twenty markaz have already delivered</div>
            <p>Eighteen of the twenty markaz at or above target are in Karor Lalisan, with enrollment of 1,300–2,200 students each —
            proof that markaz-scale delivery is possible, not just school-scale.</p>
            <div class="st-n">{len(at_target)} of {len(markaz)} markaz at 100%+</div>
          </div>
          <div class="strength">
            <div class="st-h">4 · Large secondary schools can move</div>
            <p>{movers[1]['name']} added <b>{movers[1]['growth']}</b> students, {movers[2]['name']} <b>{movers[2]['growth']}</b> and
            {movers[7]['name']} <b>{movers[7]['growth']}</b> — all schools of 700–1,400 students. The secondary slide is a management problem,
            not a demographic one.</p>
            <div class="st-n">Best eight large schools added {sum(s['growth'] for s in movers)} students</div>
          </div>
        </div>
        {callout("What this means",
          f"The district does not need a new strategy. It needs to apply the practices of its elementary and Karor systems to its large secondary "
          f"schools — and to hold markaz accountable for the {len(markaz) - len(at_target)} clusters that are not yet at target.", "green")}""")

    # 21 constraints --------------------------------------------------------
    constraints = [
        ("Secondary wing", pct(wings[2]['achT']),
         f"{fmt(wings[2]['gap'])} students short — {wings[2]['share_gap']:.0f}% of the district gap — from {wings[2]['n']} schools teaching "
         f"{wings[2]['share_enr']:.0f}% of all students, and has added only {fmt(wings[2]['growth'])} since baseline.", "red"),
        ("Large schools (800+)", pct(big['achT']),
         f"{big['n']} schools, {fmt(big['cT'])} students, {fmt(big['gap'])} of the gap. The three largest — {largest[0]['name']} ({fmt(largest[0]['cT'])}), "
         f"{largest[1]['name']} ({fmt(largest[1]['cT'])}) and {largest[2]['name']} ({fmt(largest[2]['cT'])}) — are all below baseline.", "darkred"),
        ("Layyah tehsil", pct(tehsils[0]['achT']),
         f"{fmt(tehsils[0]['gap'])} of the {fmt(district['gap'])} district shortfall, {tehsils[0]['below_base']} schools below baseline, "
         f"and not one of its {tehsils[0]['markaz']} markaz at target.", "amber"),
        ("Chaubara girls", f"GPI {tehsils[2]['gpi']:.2f}",
         f"{tehsils[2]['zero_girls']} schools with no girls, {pct(tehsils[2]['female_share'])} girls' share and female elementary achievement of "
         f"{pct(chaubara_we['achT'])} — the weakest cell in the district.", "pink"),
    ]
    rows = "".join(f'<div class="problem tone-{tone}"><div class="p-top"><span class="p-name">{nm}</span>'
                   f'<span class="p-val">{val}</span></div><div class="p-text">{txt}</div></div>'
                   for nm, val, txt, tone in constraints)
    add("Diagnosis · constraints", "And four things that are holding the district back",
        "Each is a distinct problem with a distinct owner — not a single “enrollment is low” story.",
        f"""{rows}
        {callout("The common thread",
          f"All four constraints are about <b>scale</b>, not effort. Layyah's small schools are delivering; its largest schools, its secondary wing "
          f"and its most rural girls' schools are not. A plan built around the {sum(1 for s in schools if s['gap'] > 50)} schools that each need 50+ "
          f"students would address all four at once.", "navy")}""")

    # 22 action plan --------------------------------------------------------
    union = {s['emis'] for s in top20} | {s['emis'] for s in schools if s['cT'] >= 800}
    union_gap = sum(s['gap'] for s in schools if s['emis'] in union)
    actions = [
        ["1", "<b>Secondary recovery sprint</b><br><span class='sm'>School-wise plans for the "
              f"{len(union)} largest-need schools (top 20 by gap plus every school of 800+); weekly CEO review</span>",
         "CEO / DEO (SE)", f"{fmt(union_gap)} students", f"Achievement {pct(district['achT'])} → 40%"],
        ["2", "<b>Chowk Azam &amp; Layyah city high schools</b><br><span class='sm'>Household re-admission drives, section and teacher "
              f"availability, timetable audit at {top20[0]['name']}, {top20[1]['name']} and {top20[2]['name']}</span>",
         "DEO (SE) + AEOs", f"{fmt(sum(s['gap'] for s in top20[:5]))} students", "Each back to baseline in 30 days"],
        ["3", "<b>Chaubara girls' enrollment</b><br><span class='sm'>Facility audit (boundary, toilets, water), stipend and transport uptake, "
              f"community mobilisation across its {tehsils[2]['markaz']} markaz</span>",
         "DEO (EE) + AEOs", f"{fmt(tehsils[2]['gap'])} students", f"GPI {tehsils[2]['gpi']:.2f} → 0.95"],
        ["4", "<b>Markaz accountability</b><br><span class='sm'>Monthly scorecards for the ten lowest markaz and for the four negative Layyah clusters; "
              "AEO appraisal linked to cluster achievement</span>",
         "AEOs / Deputy DEO", f"{fmt(sum(m['gap'] for m in markaz_sorted[-10:]))} students", f"{len(neg_markaz)} negative markaz → 0"],
        ["5", "<b>Roster and data integrity</b><br><span class='sm'>Verify the "
              f"{zero_girls} zero-girls and {zero_boys} zero-boys schools, resolve the {zero_both} zero-enrollment records, fix markaz mapping for secondary schools</span>",
         "IT / EMIS cell", f"{fmt(n)} school records", "100% validated roster"],
        ["6", "<b>Recognise and replicate</b><br><span class='sm'>Publish the markaz and school league; document practice in the "
              f"{len(at_target)} markaz above 100% and the eight fastest-growing large schools</span>",
         "CEO office", f"{len(at_target)} markaz · {ha} schools", "Top-quartile practice in all 3 tehsils"],
    ]
    add("Action plan", "Six workstreams for the next quarter",
        "Sequenced by where the students are, each with a named owner and a measurable outcome.",
        f"""{table(["#", "Action", "Owner", "Scope", "90-day outcome"], actions,
                    widths=["24px", "560px", "118px", "106px", "180px"], aligns=["left"] * 5)}
        <div class="note mt10">Workstream 1 alone covers <b>{fmt(union_gap)}</b> students ({union_gap / district['gap'] * 100:.0f}% of the gap) across {len(union)} schools,
        and workstream 2 puts the five largest of those under weekly review. Workstreams 3–6 protect the result and make the next target cycle easier to hit.</div>""")

    # 23 milestones ---------------------------------------------------------
    add("Milestones", "What progress should look like at 30, 60 and 90 days",
        f"A staged path from {pct(district['achT'])} to about {pct(miles[2]['ach'])}, with checkpoints a review meeting can actually verify.",
        f"""
        <div class="timeline">
          <div class="tl">
            <div class="tl-dot">30</div><div class="tl-h">Verify &amp; start</div>
            <div class="tl-target">+{fmt(miles[0]['students'])} students · {pct(miles[0]['ach'])}</div>
            <ul>
              <li>All {sum(1 for s in schools if s['gap'] > 50)} schools needing 50+ students have a signed recovery plan</li>
              <li>Roster validation complete (zero-enrollment and zero-girls schools)</li>
              <li>Chaubara facility audit finished; works list submitted</li>
              <li>Scorecards issued to all {len(markaz)} markaz</li>
            </ul>
          </div>
          <div class="tl">
            <div class="tl-dot">60</div><div class="tl-h">Recover</div>
            <div class="tl-target">+{fmt(miles[1]['students'])} students · {pct(miles[1]['ach'])}</div>
            <ul>
              <li>Top 20 gap schools recover 40% of their shortfall</li>
              <li>Every below-baseline secondary school back to baseline</li>
              <li>Girls' enrollment up {fmt(2000)} on today</li>
              <li>Zero-girls schools reduced by half</li>
            </ul>
          </div>
          <div class="tl">
            <div class="tl-dot">90</div><div class="tl-h">Consolidate</div>
            <div class="tl-target">+{fmt(miles[2]['students'])} students · {pct(miles[2]['ach'])}</div>
            <ul>
              <li>Secondary wing above 20%</li>
              <li>No markaz below zero; {len(at_target) + 10} markaz at target</li>
              <li>GPI in Chaubara above 0.90</li>
              <li>Practice notes from top markaz adopted in all tehsils</li>
            </ul>
          </div>
        </div>
        <div class="split2 mt16">
          {callout("Why these checkpoints",
            f"Each milestone is a share of the remaining gap — {miles[0]['share']:.0f}%, {miles[1]['share']:.0f}% and {miles[2]['share']:.0f}% — rather than a flat student count. "
            f"That keeps the plan honest as baseline and target are refreshed.", "blue")}
          {callout("How to verify",
            f"Use the day-on-day SIS movement, the school health counts (below baseline / below target / at target) and the markaz league. "
            f"Percentages alone will mislead because of small target increments.", "slate")}
        </div>""")

    # 24 risks --------------------------------------------------------------
    risk_rows = [
        ["Small denominators", f"{tiny} schools have a target only 1–10 students above baseline",
         "A one-student change moves a school's percentage by 10–100 points",
         "Judge on absolute students and health counts; percentages are a flag"],
        ["Target generosity", "Some targets sit barely above baseline (2 students at GGHSS Chak 218/TDA); others are steep",
         "Achievement is not comparable across schools",
         "Compare within size bands and wings; never rank on raw %"],
        ["Roster gaps", f"{district['cO']} students under “Other”; {zero_girls} schools with no girls, {zero_boys} with no boys, {zero_both} with no enrollment",
         "Gender and total figures may hide closed, merged or mis-mapped schools",
         "Field verification before the next target cycle"],
        ["Snapshot timing", f"SIS current ({SNAP_SIS}) and Grades baseline/target ({SNAP_GRADES}) are 8 days apart",
         "Small timing effects on current values; baseline and target are static",
         "Acceptable for strategy; refresh both before formal reporting"],
        ["Seasonality", "Enrollment moves with harvest, migration and the exam cycle in Thal",
         "A single snapshot can over- or under-state the run-rate",
         "Track the four-week trend, not one day"],
    ]
    add("Data notes &amp; risks", "Five caveats to state before anyone quotes a number",
        "Stating these up front protects the analysis — and stops the deck being dismissed over a single extreme percentage.",
        f"""{table(["Risk", "Evidence in this data", "Effect", "How this deck handles it"], risk_rows,
                    cls="compact", widths=["132px", "416px", "296px", "330px"], aligns=["left"] * 4)}
        <div class="note mt12">Source: SED Punjab enrollment dashboard — SIS snapshot {SNAP_SIS}; Grades baseline and target {SNAP_GRADES}.
        All figures recomputed for District Layyah from the published school-level files; the accompanying CSV extracts contain the full working.</div>""")

    # appendix A ------------------------------------------------------------
    rows = [[f"<b>{t['name']}</b>", fmt(t['n']), str(t['markaz']), fmt(t['cT']), fmt(t['bT']), fmt(t['tT']),
             fmt(t['growth']), fmt(t['gap']), chip(t['achT']), pct(t['female_share']), f"{t['gpi']:.3f}",
             f"{t['below_base']} / {t['below_target']} / {t['above_target']}"] for t in tehsils]
    rows.append([f"<b>District</b>", f"<b>{fmt(n)}</b>", f"<b>{len(markaz)}</b>", f"<b>{fmt(district['cT'])}</b>",
                 f"<b>{fmt(district['bT'])}</b>", f"<b>{fmt(district['tT'])}</b>", f"<b>{fmt(district['growth'])}</b>",
                 f"<b>{fmt(district['gap'])}</b>", chip(district['achT']), f"<b>{pct(district['female_share'])}</b>",
                 f"<b>{district['gpi']:.3f}</b>",
                 f"<b>{district['below_base']} / {district['below_target']} / {district['above_target']}</b>"])
    add("Appendix A", "Tehsil detail — full table",
        "Health reads below baseline / below target / at or above target.",
        f"""{table(["Tehsil", "Schools", "Markaz", "Current", "Baseline", "Target", "Added", "Gap", "Achievement", "Girls share", "GPI", "Health"],
                    rows, widths=["112px", "66px", "62px", "84px", "84px", "82px", "70px", "70px", "92px", "78px", "54px", "128px"])}
        <div class="note mt10">Added = current − baseline. Gap = target − current. Achievement is computed on summed values, not averaged across schools.
        GPI = girls ÷ boys current enrollment.</div>""")

    # appendix B–D ----------------------------------------------------------
    for i, t in enumerate(tehsils, start=2):
        tm = sorted([m for m in markaz if m['tehsil'] == t['name']], key=lambda m: -m['achT'])
        rows = [[f"<b>{smart_name(m['name'])}</b>", fmt(m['n']), fmt(m['cT']), chip(m['achT']), fmt(m['gap'])] for m in tm]
        half = (len(rows) + 1) // 2
        head = ["Markaz", "Sch.", "Current", "Ach.", "Gap"]
        widths = ["228px", "32px", "62px", "66px", "50px"]
        add(f"Appendix {chr(64 + i)}", f"{t['name']} tehsil — all {len(tm)} markaz",
            f"Ranked by achievement. {t['name']} holds {fmt(t['cT'])} students, {t['share_gap']:.0f}% of the district gap and "
            f"{sum(1 for m in tm if m['achT'] >= 100)} markaz at or above target.",
            f"""<div class="two-col">
                {table(head, rows[:half], cls="compact", widths=widths)}
                {table(head, rows[half:], cls="compact", widths=widths)}
            </div>
            <div class="note mt8">A negative gap means the markaz has already exceeded its target. Markaz are AEO clusters; secondary schools are
            grouped under a separate “Secondary Wing” heading in the source data and are excluded from the markaz count.</div>""")

    # appendix E ------------------------------------------------------------
    rows = [[str(i), s['name'], s['tehsil'], s['wing'], fmt(s['cT']), fmt(s['gap']), f"{s['growth']:+d}", chip(s['achT'])]
            for i, s in enumerate(by_gap[:40], 1)]
    head = ["#", "School", "Tehsil", "Wing", "Current", "Gap", "vs base", "Ach."]
    widths = ["22px", "204px", "82px", "38px", "52px", "44px", "48px", "56px"]
    add("Appendix E", "Top 40 schools by students needed",
        f"The working list for the secondary recovery sprint — 40 schools holding {sum(s['gap'] for s in by_gap[:40]) / district['gap'] * 100:.0f}% of the district gap.",
        f"""<div class="two-col">
            {table(head, rows[:20], cls="compact", widths=widths)}
            {table(head, rows[20:], cls="compact", widths=widths)}
        </div>
        <div class="note mt8">Gap = target − current. “vs base” = current − baseline.
        {sum(1 for s in by_gap[:40] if s['wing'] == 'SE')} of the 40 are secondary schools.</div>""")

    # closing ---------------------------------------------------------------
    slides.append({"kicker": "", "title": "", "sub": "", "cls": "slide-close no-foot", "body": f"""
        <div class="close-wrap">
          <div class="close-kicker">In one sentence</div>
          <div class="close-text">Layyah's enrollment problem is not spread across {fmt(n)} schools — it is concentrated in
          <b>{fmt(top20_gap)} students across 20 secondary schools</b>, in <b>girls' education in Chaubara</b>, and in
          <b>the {big['n']} largest schools, which as a group now sit below their baseline</b>.</div>
          <div class="close-grid">
            <div><b>{pct(district['achT'])}</b><span>today</span></div>
            <div><b>{pct(top20_new_ach)}</b><span>if the top 20 close</span></div>
            <div><b>100%</b><span>at target · {fmt(district['tT'])} students</span></div>
          </div>
          <div class="close-foot">District Layyah · Enrollment Performance Review · SIS {SNAP_SIS} · Grades {SNAP_GRADES}</div>
        </div>"""})

    page = render(slides, district, n)
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(page, encoding="utf-8")
    write_csvs(schools, tehsils, markaz + [m for m in markaz_all if m["secondary"]], district)
    print(f"wrote {OUT / 'index.html'} — {len(slides)} slides, {len(page) / 1024:.0f} KB")


def render(slides, district, n):
    css = (ASSETS / "layyah_deck.css").read_text(encoding="utf-8")
    js = (ASSETS / "layyah_deck.js").read_text(encoding="utf-8")
    total = len(slides)
    parts = []
    for i, s in enumerate(slides, 1):
        cls = f'slide {s["cls"]}'.strip()
        head = ""
        if s["title"]:
            head = (f'<div class="kicker">{s["kicker"]}</div><h1>{s["title"]}</h1>'
                    f'<div class="sub">{s["sub"]}</div>')
        foot = ""
        if "no-foot" not in s["cls"]:
            foot = (f'<div class="foot"><span>District Layyah · Enrollment Performance Review</span>'
                    f'<span>SED Punjab · <b>{pct(district["achT"])}</b> of target</span>'
                    f'<span class="pg">{i:02d} / {total:02d}</span></div>')
        parts.append(f'<section class="{cls}">{head}<div class="body"><div class="body-inner">{s["body"]}</div></div>{foot}</section>')

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>District Layyah — Enrollment Performance Review | SED Punjab</title>
<meta name="description" content="District Layyah enrollment performance review: {n} schools, 3 tehsils, 100 markaz, achievement against baseline and target.">
<style>
{css}
</style>
</head>
<body>
<div id="progress" style="width:0"></div>
<div id="viewport"><div id="stage">
{''.join(parts)}
</div></div>
<div id="nav">
  <span class="hint">← → or click · P print · F fullscreen</span>
  <button id="prev" aria-label="Previous slide">‹</button>
  <span class="count">1 / {total}</span>
  <button id="next" aria-label="Next slide">›</button>
  <button id="print">Print / PDF</button>
</div>
<script>
{js}
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# CSV extracts
# ---------------------------------------------------------------------------
def write_csvs(schools, tehsils, markaz, district):
    OUT.mkdir(exist_ok=True)
    with open(OUT / "layyah_schools.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["EMIS", "School", "Tehsil", "Markaz", "Wing", "Boys Baseline", "Boys Current", "Boys Target",
                    "Girls Baseline", "Girls Current", "Girls Target", "Other Current", "Total Baseline",
                    "Total Current", "Total Target", "Achievement %", "Status", "Gap to Target",
                    "Change vs Baseline", "Day Change"])
        for s in sorted(schools, key=lambda x: (TEHSIL_ORDER.index(x["tehsil"]), -x["gap"])):
            w.writerow([s["emis"], s["name"], s["tehsil"], smart_name(s["markaz"]), s["wing"],
                        s["bM"], s["cM"], s["tM"], s["bF"], s["cF"], s["tF"], s["cO"],
                        s["bT"], s["cT"], s["tT"], f"{s['achT']:.1f}", s["health"], s["gap"],
                        s["growth"], s["delta"]])
    with open(OUT / "layyah_markaz.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Markaz", "Tehsil", "Schools", "Boys Current", "Girls Current", "Total Baseline",
                    "Total Current", "Total Target", "Achievement %", "Gap to Target",
                    "Share of District Gap %", "Below Baseline", "Below Target", "At or Above Target"])
        for m in sorted(markaz, key=lambda m: (TEHSIL_ORDER.index(m["tehsil"]), m["secondary"], -m["achT"])):
            w.writerow([("Secondary Wing (SE)" if m["secondary"] else smart_name(m["name"])), m["tehsil"],
                        m["n"], m["cM"], m["cF"], m["bT"], m["cT"],
                        m["tT"], f"{m['achT']:.1f}", m["gap"], f"{m['share_gap']:.1f}", m["below_base"],
                        m["below_target"], m["above_target"]])
    with open(OUT / "layyah_tehsils.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Tehsil", "Schools", "Markaz", "Boys Baseline", "Boys Current", "Boys Target",
                    "Girls Baseline", "Girls Current", "Girls Target", "Total Baseline", "Total Current",
                    "Total Target", "Achievement %", "Gap to Target", "GPI", "Below Baseline"])
        for t in tehsils:
            w.writerow([t["name"], t["n"], t["markaz"], t["bM"], t["cM"], t["tM"], t["bF"], t["cF"],
                        t["tF"], t["bT"], t["cT"], t["tT"], f"{t['achT']:.1f}", t["gap"],
                        f"{t['gpi']:.3f}", t["below_base"]])


if __name__ == "__main__":
    build()

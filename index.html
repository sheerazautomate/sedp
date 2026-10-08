/* ============================================================================
 * fetch-data.js — Grades data loader for the SED Punjab Enrollment Dashboard
 * ----------------------------------------------------------------------------
 * Single data source: the Grades `districts-enrollment` CSV export, committed
 * daily by the GitHub Actions worker (`scripts/fetch_grades.py`):
 *
 *   data/enrollment.csv       latest snapshot (REQUIRED)
 *   data/enrollment_prev.csv  the current PKT day's midnight reference
 *                            snapshot (optional; for day-change Δ)
 *   data/emis_wing.json       one-time {EMIS: Wing} lookup (optional)
 *   data/meta.json            {fetched_at_pkt, rows, ...} (optional)
 *
 * Grades export columns (exact headers, see screenshot-verified list):
 *   Sr.# | District | Tehsil | Markaz | EMIS | School Name |
 *   Male Baseline | Male Current | Male Target |
 *   Female Baseline | Female Current | Female Target |
 *   Total Baseline | Total Current | Total Target | Achievement %
 *
 * Verified formula:  Achievement % = (Current - Baseline) / (Target - Baseline) * 100
 * (NT-style with NT = Target - Baseline). It is computed here for every school
 * (Male, Female and Total) and for every group aggregate (from summed values).
 * It is deliberately UNCLAMPED: above 100% means the target was exceeded and a
 * negative value means enrollment fell below baseline. The export's own
 * "Achievement %" column (which is clamped to 0-100) is NOT used for display.
 * There is NO second "% Ach" metric.
 *
 * Totals: Baseline and Target totals are Male + Female. Total Current is the
 * export's own figure, which also counts the "Other" category (children
 * reported as Other by school heads, with no Male/Female column). The
 * difference is kept per school as `curOther` and shown on the dashboard, so
 * Current Male + Female + Other = Total Current.
 *
 * Day change: compared against data/enrollment_prev.csv. The loader reports
 * `report.delta = {state, reason, refDate}` with state "ok" | "warn" | "error":
 *   error  prev file missing/unreadable, or > 2% of schools absent from it
 *   warn   prev file exists but meta.ref_date_pkt is not today's PKT date
 * (the dashboard shows N/A on "error" and an amber note on "warn").
 *
 * Wing resolution per school: emis_wing.json lookup -> Markaz-name keyword
 * fallback (Female/Male; "female" tested BEFORE "male" since it contains the
 * substring) -> "Unknown". Only schools whose resolved wing is SE, M-EE, or
 * W-EE are kept; Male / Female / Unknown (and any other label) are dropped.
 *
 * Usage (plain <script> include, no modules so it works on GitHub Pages):
 *   const { rows, meta, report } = await loadGradesData();
 * ========================================================================== */

const GRADES_PATHS = {
  current: "data/enrollment.csv",
  prev: "data/enrollment_prev.csv",
  wing: "data/emis_wing.json",
  meta: "data/meta.json",
};

/* Header matching: headers are normalized (lowercase, strip % . # and all
 * whitespace/underscores) then looked up in these alias lists. */
function normHeader(h) {
  return String(h || "")
    .toLowerCase()
    .replace(/[%#.\u00a0]/g, "")
    .replace(/[\s_]+/g, "");
}

const HEADER_ALIASES = {
  district: ["district", "dname", "districtname"],
  tehsil: ["tehsil", "tname", "tehsilname"],
  markaz: ["markaz", "mname", "markazname"],
  emis: ["emis", "emiscode"],
  school: ["schoolname", "school", "sname"],
  male_baseline: ["malebaseline", "baselineboys", "boysbaseline", "mbaseline", "mbase"],
  male_current: ["malecurrent", "currentboys", "boyscurrent", "mcurrent", "mcurr"],
  male_target: ["maletarget", "boystarget", "targetboys", "mtarget", "mtarg"],
  female_baseline: ["femalebaseline", "baselinegirls", "girlsbaseline", "fbaseline", "fbase"],
  female_current: ["femalecurrent", "currentgirls", "girlscurrent", "fcurrent", "fcurr"],
  female_target: ["femaletarget", "girlstarget", "targetgirls", "ftarget", "ftarg"],
  /* Baseline/Target totals are derived as M+F (they always equal the file's
   * own totals). Total Current is taken from the file because it includes the
   * "Other" category - see the header comment. */
  total_baseline: ["totalbaseline", "baselinetotal", "totalbase"],
  total_current: ["totalcurrent", "currenttotal", "currentenrolment", "currentenrollment", "totalcurr"],
  total_target: ["totaltarget", "targettotal", "targettedenrolment", "targetedenrolment", "targetedenrollment", "targettedenrollment", "totaltarg"],
  /* School-level Total achievement; Male/Female are always computed. */
  ach: ["achievement", "ach", "achnt", "ntach", "achievementpct"],
};

const DERIVABLE_TOTALS = ["total_baseline", "total_current", "total_target"];

/* ------------------------------------------------------------------ */
/* Small utilities                                                     */
/* ------------------------------------------------------------------ */

function normalizeEmis(v) {
  return String(v == null ? "" : v).trim().replace(/\.0$/, "");
}

/** Counts: blank/dash -> 0, strip thousands separators, round to int. */
function parseCount(v) {
  if (v == null) return 0;
  const s = String(v).trim().replace(/,/g, "");
  if (s === "" || s === "-" || s === "--") return 0;
  const n = Number(s);
  return Number.isFinite(n) ? Math.round(n) : 0;
}

/** Percentages: strip %/commas; unparseable -> null (caller computes). */
function parsePct(v) {
  if (v == null) return null;
  const s = String(v).trim().replace(/%/g, "").replace(/,/g, "");
  if (s === "" || s === "-") return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/**
 * Achievement % = (cur - bas) / (tar - bas) * 100, deliberately UNCLAMPED.
 * No-growth-asked rows (target <= baseline): staying at/above baseline = 100,
 * dropping below baseline = 0.
 */
function computeAch(cur, bas, tar) {
  const denom = tar - bas;

  if (denom <= 0) return cur >= bas ? 100 : 0;

  return ((cur - bas) / denom) * 100;
}

/** Minimal RFC-4180-ish CSV parser (quotes, escaped quotes, CRLF). */
function parseCSV(text) {
  const rows = [];
  let row = [], cur = "", q = false;
  const t = String(text == null ? "" : text);
  for (let i = 0; i < t.length; i++) {
    const c = t[i];
    if (q) {
      if (c === '"') {
        if (t[i + 1] === '"') { cur += '"'; i++; }
        else q = false;
      } else cur += c;
    } else if (c === '"') q = true;
    else if (c === ",") { row.push(cur); cur = ""; }
    else if (c === "\n") { row.push(cur); rows.push(row); row = []; cur = ""; }
    else if (c === "\r") { /* skip */ }
    else cur += c;
  }
  if (cur !== "" || row.length) { row.push(cur); rows.push(row); }
  return rows.filter((r) => r.some((c) => String(c).trim() !== ""));
}

/** Map normalized header cells to field names. Throws listing what's off. */
function mapColumns(headerCells) {
  const idx = {};
  Object.keys(HEADER_ALIASES).forEach((f) => { idx[f] = -1; });
  headerCells.forEach((cell, i) => {
    const n = normHeader(cell);
    for (const field of Object.keys(HEADER_ALIASES)) {
      if (HEADER_ALIASES[field].indexOf(n) !== -1 && idx[field] === -1) {
        idx[field] = i;
      }
    }
  });
  const missing = Object.keys(idx).filter(
    (f) => idx[f] === -1 && DERIVABLE_TOTALS.indexOf(f) === -1 && f !== "ach"
  );
  if (missing.length) {
    throw new Error(
      "Unrecognized enrollment.csv header. Missing columns: " +
      missing.join(", ") +
      ". Found headers: [" + headerCells.join(" | ") + "]"
    );
  }
  return idx;
}

function cell(row, i) {
  return i >= 0 && i < row.length ? row[i] : "";
}

/* ------------------------------------------------------------------ */
/* Wing resolution                                                     */
/* ------------------------------------------------------------------ */

const RE_FEMALE = /(female|women|girl|girls)|\(\s*f\s*\)/;
const RE_MALE = /(^|[^a-z])(male|men|boy|boys)([^a-z]|$)|\(\s*m\s*\)/;

/** Grades wing labels we trust. Male / Female / Unknown (and anything else) are dropped. */
const ALLOWED_WINGS = { SE: true, "M-EE": true, "W-EE": true };

function resolveWing(emis, markaz, wingMap) {
  if (wingMap) {
    const hit = wingMap[emis];
    if (hit != null && String(hit).trim() !== "") return String(hit).trim();
  }
  const m = " " + String(markaz || "").toLowerCase() + " ";
  if (RE_FEMALE.test(m)) return "Female"; /* BEFORE male: "female" contains "male" */
  if (RE_MALE.test(m)) return "Male";
  return "Unknown";
}

/* ------------------------------------------------------------------ */
/* Day-change reference health                                         */
/* ------------------------------------------------------------------ */

/* More than this share of schools missing from the previous-day snapshot
 * means the reference is incomplete and the day change cannot be trusted. */
const MAX_MISSING_PREV_RATIO = 0.02;

function pktToday() {
  return new Date(Date.now() + 5 * 3600 * 1000).toISOString().slice(0, 10);
}

function assessDelta(prevText, prevOk, missingPrev, total, meta) {
  if (!prevText) {
    return { state: "error", reason: "Previous-day enrollment was not fetched (file missing)." };
  }
  if (!prevOk) {
    return { state: "error", reason: "Previous-day enrollment was not fetched properly (file unreadable)." };
  }
  if (total > 0 && missingPrev / total > MAX_MISSING_PREV_RATIO) {
    return {
      state: "error",
      reason: "Previous-day enrollment is incomplete (" + missingPrev.toLocaleString() +
        " of " + total.toLocaleString() + " schools missing).",
    };
  }
  const refDate = meta && meta.ref_date_pkt ? String(meta.ref_date_pkt) : null;
  if (refDate && refDate !== pktToday()) {
    return { state: "warn", refDate, reason: "Today's reference snapshot has not been fetched yet." };
  }
  return { state: "ok", refDate };
}

/* ------------------------------------------------------------------ */
/* Main loader                                                         */
/* ------------------------------------------------------------------ */

async function fetchText(path, required) {
  let resp;
  try {
    resp = await fetch(path, { cache: "no-store" });
  } catch (e) {
    if (required) throw new Error("Could not load " + path + " (" + e.message + ")");
    return null;
  }
  if (!resp.ok) {
    if (required) {
      throw new Error(
        "Missing " + path + " (HTTP " + resp.status + "). " +
        "Run the 'Fetch Grades enrollment' workflow (or copy the Grades " +
        "districts-enrollment export to " + path + ")."
      );
    }
    return null;
  }
  return resp.text();
}

function parseEnrollmentTable(text) {
  const grid = parseCSV(text);
  if (grid.length < 2) throw new Error("enrollment CSV has no data rows.");
  const idx = mapColumns(grid[0]);
  const out = [];
  for (let r = 1; r < grid.length; r++) {
    const row = grid[r];
    const basM = parseCount(cell(row, idx.male_baseline));
    const curM = parseCount(cell(row, idx.male_current));
    const tarM = parseCount(cell(row, idx.male_target));
    const basF = parseCount(cell(row, idx.female_baseline));
    const curF = parseCount(cell(row, idx.female_current));
    const tarF = parseCount(cell(row, idx.female_target));
    out.push({
      d: String(cell(row, idx.district)).trim(),
      t: String(cell(row, idx.tehsil)).trim(),
      m: String(cell(row, idx.markaz)).trim(),
      emis: normalizeEmis(cell(row, idx.emis)),
      school: String(cell(row, idx.school)).trim(),
      basM, curM, tarM, basF, curF, tarF,
      // Grades includes an "Other" category in Total Current that is not
      // represented by the Male/Female columns. Preserve the official total
      // and expose the difference (curOther) instead of silently discarding it.
      basT: basM + basF,
      curT: idx.total_current === -1 ? curM + curF : parseCount(cell(row, idx.total_current)),
      curOther: (idx.total_current === -1 ? curM + curF : parseCount(cell(row, idx.total_current))) - curM - curF,
      tarT: tarM + tarF,
      achFile: idx.ach === -1 ? null : parsePct(cell(row, idx.ach)),
    });
  }
  return out.filter((s) => s.d !== "" || s.emis !== "");
}

async function loadGradesData() {
  const currentText = await fetchText(GRADES_PATHS.current, true);
  const [prevText, wingText, metaText] = await Promise.all([
    fetchText(GRADES_PATHS.prev, false),
    fetchText(GRADES_PATHS.wing, false),
    fetchText(GRADES_PATHS.meta, false),
  ]);

  /* The day's midnight reference snapshot, keyed by EMIS (same layout as
     current). Syncs through the day leave it pinned so Δ = since midnight. */
  let prevMap = {};
  let prevOk = false;
  if (prevText) {
    try {
      parseEnrollmentTable(prevText).forEach((s) => {
        if (s.emis) prevMap[s.emis] = { curM: s.curM, curF: s.curF, curT: s.curT };
      });
      prevOk = Object.keys(prevMap).length > 0;
    } catch (e) {
      console.warn("[grades] ignoring unreadable prev snapshot:", e.message);
    }
  }

  let wingMap = {};
  if (wingText) {
    try { wingMap = JSON.parse(wingText) || {}; }
    catch (e) { console.warn("[grades] ignoring unreadable wing map:", e.message); }
  }

  let meta = null;
  if (metaText) {
    try { meta = JSON.parse(metaText); } catch (e) { /* ignore */ }
  }

  const parsed = parseEnrollmentTable(currentText);
  let missingPrev = 0, unknownWing = 0, droppedWing = 0;
  const wingValues = {};
  const rows = [];
  parsed.forEach((s) => {
    s.w = resolveWing(s.emis, s.m, wingMap);
    if (s.w === "Unknown") unknownWing++;
    if (!ALLOWED_WINGS[s.w]) {
      droppedWing++;
      return;
    }
    const p = prevMap[s.emis];
    if (p) { s.prevM = p.curM; s.prevF = p.curF; s.prevT = p.curT; }
    /* Not in the reference (e.g. a brand-new school): treat as unchanged so a
       missing row never shows up as a full-enrollment "increase". */
    else { s.prevM = s.curM; s.prevF = s.curF; s.prevT = s.curT; missingPrev++; }
    wingValues[s.w] = (wingValues[s.w] || 0) + 1;
    /* Single % metric: same unclamped formula for Total, M and F. */
    s.achT = computeAch(s.curT, s.basT, s.tarT);
    s.achM = computeAch(s.curM, s.basM, s.tarM);
    s.achF = computeAch(s.curF, s.basF, s.tarF);
    delete s.achFile;
    rows.push(s);
  });

  const report = {
    rows: rows.length,
    parsed: parsed.length,
    droppedWing,
    missingPrev,
    unknownWing,
    wings: Object.keys(wingValues).sort(),
    hasPrev: !!prevText,
    delta: assessDelta(prevText, prevOk, missingPrev, rows.length, meta),
    hasWingMap: Object.keys(wingMap).length > 0,
  };
  console.info("[grades] loaded", report);
  if (report.delta.state !== "ok") console.warn("[grades] day change " + report.delta.state + ": " + report.delta.reason);
  if (droppedWing) {
    console.warn("[grades] dropped " + droppedWing +
      " schools whose Wing is not SE / M-EE / W-EE (Male, Female, Unknown, etc.).");
  }
  return { rows, meta, report };
}

/* Export for browsers (<script> tag) and for node-based tests alike. */
globalThis.GradesLoader = {
  loadGradesData, computeAch, parseCSV, mapColumns, resolveWing,
  normalizeEmis, parseCount, parsePct, assessDelta, GRADES_PATHS, HEADER_ALIASES, ALLOWED_WINGS,
};

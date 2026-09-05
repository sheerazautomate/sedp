/* ============================================================================
 * fetch-data.js — Grades data loader for the SED Punjab Enrollment Dashboard
 * ----------------------------------------------------------------------------
 * Single data source: the Grades `districts-enrollment` CSV export, committed
 * daily by the GitHub Actions worker (`scripts/fetch_grades.py`):
 *
 *   data/enrollment.csv       latest snapshot (REQUIRED)
 *   data/enrollment_prev.csv  yesterday's snapshot (optional; for day Δ)
 *   data/emis_wing.json       one-time {EMIS: Wing} lookup (optional)
 *   data/meta.json            {fetched_at_pkt, rows, ...} (optional)
 *
 * Grades export columns (exact headers, see screenshot-verified list):
 *   Sr.# | District | Tehsil | Markaz | EMIS | School Name |
 *   Male Baseline | Male Current | Male Target |
 *   Female Baseline | Female Current | Female Target |
 *   Total Baseline | Total Current | Total Target | Achievement %
 *
 * Verified formula:  Achievement % = (Current - Baseline) / (Target - Baseline)
 * (NT-style with NT = Target - Baseline). The file's Achievement % is used
 * as-is for each school's Total; Male/Female and all group aggregates are
 * computed with the same formula. There is NO second "% Ach" metric anymore.
 *
 * Wing resolution per school: emis_wing.json lookup -> Markaz-name keyword
 * fallback (Female/Male; "female" tested BEFORE "male" since it contains the
 * substring) -> "Unknown".
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
  /* Totals are derived as M+F if the export ever drops these columns. */
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
 * Achievement % with the verified Grades formula.
 * fileVal (the export's Achievement %) wins when present; otherwise compute.
 * No-growth-asked rows (target <= baseline): staying at/above baseline = 100.
 */
function computeAch(cur, bas, tar, fileVal) {
  if (Number.isFinite(fileVal)) return fileVal;
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
      basT: idx.total_baseline === -1 ? basM + basF : parseCount(cell(row, idx.total_baseline)),
      curT: idx.total_current === -1 ? curM + curF : parseCount(cell(row, idx.total_current)),
      tarT: idx.total_target === -1 ? tarM + tarF : parseCount(cell(row, idx.total_target)),
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

  /* Yesterday's currents by EMIS (same export layout). */
  let prevMap = {};
  if (prevText) {
    try {
      parseEnrollmentTable(prevText).forEach((s) => {
        if (s.emis) prevMap[s.emis] = { curM: s.curM, curF: s.curF, curT: s.curT };
      });
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

  const rows = parseEnrollmentTable(currentText);
  let missingPrev = 0, unknownWing = 0;
  const wingValues = {};
  rows.forEach((s) => {
    const p = prevMap[s.emis];
    if (p) { s.prevM = p.curM; s.prevF = p.curF; s.prevT = p.curT; }
    else { s.prevM = 0; s.prevF = 0; s.prevT = 0; missingPrev++; }
    s.w = resolveWing(s.emis, s.m, wingMap);
    if (s.w === "Unknown") unknownWing++;
    wingValues[s.w] = (wingValues[s.w] || 0) + 1;
    /* Single % metric: file value for Total, same formula for M/F. */
    s.achT = computeAch(s.curT, s.basT, s.tarT, s.achFile);
    s.achM = computeAch(s.curM, s.basM, s.tarM, null);
    s.achF = computeAch(s.curF, s.basF, s.tarF, null);
    delete s.achFile;
  });

  const report = {
    rows: rows.length,
    missingPrev,
    unknownWing,
    wings: Object.keys(wingValues).sort(),
    hasPrev: !!prevText,
    hasWingMap: Object.keys(wingMap).length > 0,
  };
  console.info("[grades] loaded", report);
  if (unknownWing) {
    console.warn("[grades] " + unknownWing + " schools fell back to Markaz-name Wing detection.");
  }
  return { rows, meta, report };
}

/* Export for browsers (<script> tag) and for node-based tests alike. */
globalThis.GradesLoader = {
  loadGradesData, computeAch, parseCSV, mapColumns, resolveWing,
  normalizeEmis, parseCount, parsePct, GRADES_PATHS, HEADER_ALIASES,
};

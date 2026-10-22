# District Layyah — enrollment presentation

A 31-slide, 16:9 presentation on District Layyah's enrollment performance, built from the same
data that feeds the district dashboard, and reported strictly in the district's administrative
hierarchy:

```
District Layyah
├── Wing 1 · M-EE (Male Elementary)      556 schools → 3 tehsils → 57 markaz → schools
├── Wing 2 · W-EE (Female Elementary)    467 schools → 3 tehsils → 43 markaz → schools
└── Wing 3 · SE   (Secondary)            200 high schools → one district block
```

The wing sits **above** the tehsil, so results are read wing-first. M-EE and W-EE carry the full
tehsil and markaz layers; the secondary wing is a single block of high schools and is **never split
tehsil-wise** — it is reported once for the district, as it is administered.

| File | What it is |
|---|---|
| `index.html` | The deck. Self-contained — CSS, JavaScript and the SED logo are inlined, so it works offline and can be emailed as one file. |
| `layyah_schools.csv` | School-level working sheet: all 1,223 schools with wing, reporting level, tehsil, markaz, baseline, current, target, achievement, health, gap and day change. Secondary schools are marked “— (no markaz layer)”. |
| `layyah_markaz.csv` | The 100 elementary AEO markaz (57 M-EE, 43 W-EE) with wing, tehsil and share of the elementary and district gaps. No secondary rows. |
| `layyah_levels.csv` | District totals at every reporting level — three wings, three elementary tehsils, elementary subtotal, secondary block, district. Reconciles exactly. |
| `layyah_secondary.csv` | The secondary block: all 200 high schools, ranked by students needed, with location kept for reference only. |
| `presenter-notes.md` | Slide-by-slide talking points, timing and answers to likely questions. |

Open `index.html` in any modern browser and present directly. `←` / `→` (or click) to move,
`P` to print, `F` for fullscreen. Printing produces one 13.33 × 7.5 in page per slide — use
“Save as PDF” for a shareable copy.

## Data and method

* **Current enrollment** — SIS school snapshot, 22 Oct 2026 06:26 AM PKT (`data/sis_enrollment.json`).
* **Baseline and target** — Grades district export, 14 Oct 2026 05:50 PM PKT (`data/enrollment.csv`).
* **Achievement** — (current − baseline) ÷ (target − baseline) × 100, uncapped, computed on summed
  school values exactly as the dashboard does. Not an average of school percentages.
* **Wing** — from `data/emis_wing.json` (M-EE, W-EE, SE).
* **Markaz** — the three “Secondary Wing” rows in the source are wing aggregates, not AEO clusters.
  They are excluded, leaving 100 real markaz, all inside M-EE or W-EE.

### Reconciliation

| Level | Schools | Students | Gap |
|---|---|---|---|
| M-EE + W-EE (elementary) | 1,023 | 159,979 | 3,627 |
| SE (secondary block) | 200 | 106,838 | 7,011 |
| **District** | **1,223** | **266,817** | **10,638** |

The three elementary tehsils (495 + 368 + 160 schools) sum to the elementary subtotal; the subtotal
plus the secondary block equals the district.

## Regenerating

```bash
python3 scripts/build_layyah_deck.py
```

The script recomputes every number from `data/` and rewrites `layyah/index.html` and the four
CSVs. If the source snapshots are refreshed, update `SNAP_SIS` / `SNAP_GRADES` at the top of the
script so the cover and footers stay accurate. Slide styling lives in
`scripts/assets/layyah_deck.css` and the viewer in `scripts/assets/layyah_deck.js`; both are
inlined into the output.

The deck includes a safety net that shrinks a slide's content slightly if it would overflow its
16:9 frame, so edits to text do not silently clip.

# District Layyah — enrollment presentation

A 30-slide, 16:9 presentation on District Layyah's enrollment performance, built from the same
data that feeds the district dashboard.

| File | What it is |
|---|---|
| `index.html` | The deck. Self-contained — CSS, JavaScript and the SED logo are inlined, so it works offline and can be emailed as one file. |
| `layyah_schools.csv` | School-level working sheet: all 1,223 schools with baseline, current, target, achievement, health, gap and day change. |
| `layyah_markaz.csv` | All 100 AEO markaz with the same measures plus share of the district gap, and the three secondary-wing rows so the file reconciles to the district total (103 rows). |
| `layyah_tehsils.csv` | The three tehsils. |
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
* **Markaz** — the three “Secondary Wing” rows in the source are wing aggregates, not AEO clusters,
  and are excluded, leaving 100 markaz.

## Regenerating

```bash
python3 scripts/build_layyah_deck.py
```

The script recomputes every number from `data/` and rewrites `layyah/index.html` and the three
CSVs. If the source snapshots are refreshed, update `SNAP_SIS` / `SNAP_GRADES` at the top of the
script so the cover and footers stay accurate. Slide styling lives in
`scripts/assets/layyah_deck.css` and the viewer in `scripts/assets/layyah_deck.js`; both are
inlined into the output.

The deck includes a safety net that shrinks a slide's content slightly if it would overflow its
16:9 frame, so edits to text do not silently clip.

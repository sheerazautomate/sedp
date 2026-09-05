# `data/` contract (worker-managed files)

The dashboard (`index.html` + `fetch-data.js`) reads these files with **no
live login**. All files here except this README are written by automation.

| File | Writer | Purpose |
|---|---|---|
| `enrollment.csv` | `fetch-enrollment.yml` (daily) | Raw Grades `districts-enrollment` export. Latest snapshot. |
| `enrollment_prev.csv` | `fetch-enrollment.yml` (daily) | Yesterday's snapshot. Matched by EMIS for day-over-day Δ. |
| `meta.json` | `fetch-enrollment.yml` (daily) | `{fetched_at_utc, fetched_at_pkt, rows, bytes, source}` for the "last sync" label. |
| `emis_wing.json` | `wing-map-once.yml` (**once**) | Static `{EMIS: Wing}` lookup restoring the Wing dimension the Grades export lacks. |

Do not hand-edit these files — the next worker run overwrites them (except
`emis_wing.json`, which is only rebuilt when the one-time workflow runs).

## Secrets required

`Settings -> Secrets and variables -> Actions`:

- `GRADES_EMAIL`
- `GRADES_PASSWORD`

## Testing the login without committing

`Actions -> Fetch Grades enrollment -> Run workflow` after adding secrets,
or locally: `GRADES_EMAIL=.. GRADES_PASSWORD=.. python scripts/fetch_grades.py --dry-run`

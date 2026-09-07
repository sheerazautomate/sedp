# `data/` contract (worker-managed files)

The dashboard (`index.html` + `fetch-data.js`) reads these files with **no
live login**. All files here except this README are written by automation.

| File | Writer | Purpose |
|---|---|---|
| `enrollment.csv` | `fetch-enrollment.yml` (2-hourly) | Raw Grades `districts-enrollment` export. Latest (current) snapshot. |
| `enrollment_prev.csv` | `fetch-enrollment.yml` (first run of each PKT day) | **Midnight reference** snapshot for the current PKT day. Pinned on the day's first successful run and left untouched by the rest of that day's syncs. Matched by EMIS for the day-change Δ. |
| `meta.json` | `fetch-enrollment.yml` (each run) | `{fetched_at_utc, fetched_at_pkt, ref_date_pkt, sync_type, rows, bytes, source}` for the "last sync" label. `sync_type` is `reference` on the day's first run, `sync` afterwards. |
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

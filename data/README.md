# `data/` contract

The dashboard (`index.html` + `fetch-data.js`) reads these files directly. The
Grades and SIS workflows update their own snapshots; `source.json` and
`notice.json` are hand-edited configuration files.

| File | Writer | Purpose |
|---|---|---|
| `enrollment.csv` | `fetch-enrollment.yml` (2-hourly) | Latest Grades export. Supplies school dimensions and the baseline, target, and (when Grades is selected) current enrollment. |
| `enrollment_prev.csv` | `fetch-enrollment.yml` (first successful run of each PKT day) | Grades reference snapshot for the day's Δ. |
| `meta.json` | `fetch-enrollment.yml` | Grades sync timestamp, reference date, and source metadata. |
| `sis_enrollment.json` | `fetch-sis-enrollment.yml` (2-hourly) | Latest SIS male/female/other/total current-enrollment counts keyed by EMIS. |
| `sis_enrollment_prev.json` | `fetch-sis-enrollment.yml` (first successful run of each PKT day) | SIS reference snapshot for the day's Δ. |
| `sis_meta.json` | `fetch-sis-enrollment.yml` | SIS sync timestamp, reference date, coverage, and source metadata. |
| `school_ids.jsonl` | Maintained DTMS mapping | EMIS-to-SIS district/tehsil/markaz/school IDs used by the scraper. |
| `emis_wing.json` | `wing-map-once.yml` (**once**) | Static `{EMIS: Wing}` lookup; restores the Wing dimension missing from the Grades export. |
| `source.json` | **Hand-edited by the dashboard owner** | Chooses `grades` or `sis` as the current-enrollment source. |
| `notice.json` | **Hand-edited by the dashboard owner** | Optional startup notice modal. |

## Selecting the active data source

Edit `data/source.json`, then commit/publish the change:

```json
{
  "source": "sis"
}
```

Set `"source"` to `"sis"` or `"grades"`. A missing or invalid selector
safely defaults to Grades. The dashboard's sync chip says **Synced from SIS**
or **Synced from Grades** and shows that source's last sync time.

- **Grades mode:** baseline, target, current enrollment, and the reference Δ all
  come from the Grades files.
- **SIS mode:** baseline, target, district/tehsil/markaz, school, and Wing remain
  from the latest Grades export; current male/female/other/total enrollment
  comes from the SIS snapshot. SIS Δ compares with the first successful SIS
  scrape of the current PKT day.
- If SIS is selected before the first snapshot exists, the dashboard temporarily
  displays Grades data with a warning; it does not label that as an SIS sync.
- Schools absent from the SIS snapshot retain their Grades current value so
  provincial totals do not silently drop. The sync status and warning banner
  disclose how many schools use this fallback.

The SIS fetcher reads `school_ids.jsonl` and calls the public
`/dashboard_revamp/get_gender_summary_pie` endpoint once per mapped school (about
38,128 SIS requests per full run with the current file). If a school's response
is all zero, it checks that EMIS against the live DTMS endpoint; when the IDs
have changed, it retries with the current IDs for that run and adjusts that
school's same-day reference to avoid a false day-change spike. The refreshed
IDs are used in-memory for that run; `school_ids.jsonl` remains the maintained
input file. It uses six concurrent workers with retries; if more than 0.5% of
mapped schools fail, the workflow keeps the previous snapshot. No SIS credentials or
browser-session cookies are stored. The workflow is scheduled every two hours
and can also be run manually from **Actions → Fetch SIS enrollment**. A manual
`dry_run` validates the mapping file without contacting SIS or writing data.

The DTMS mapping currently has a few entries with `status: "missing"`; those
cannot be queried by school ID and will use the Grades current value in SIS
mode. Other temporary SIS request failures are retried. If too many requests
fail, the workflow exits without replacing the last successful SIS snapshot.

## Startup notice (`notice.json`)

Controls the blocking popup shown when the dashboard loads. With
`"enabled": false`, nothing is shown. Example:

```json
{
  "enabled": true,
  "id": "2026-10-15-sis-backup",
  "type": "warning",
  "title": "SIS Backup Data Active",
  "message": "Current enrollment is from SIS; baseline and targets remain from the latest Grades snapshot.",
  "durationSeconds": 30
}
```

- `enabled` — `true` shows the modal, `false` hides it.
- `id` — use a new unique ID for each notice so it appears again in a browser
  session that saw an earlier notice.
- `type` — `info`, `warning`, or `critical`.
- `title` / `message` — plain text shown in the modal.
- `durationSeconds` — auto-close time (default `30`).

When enabled, the small light beside the sync chip stays red after the popup is
dismissed, so the notice remains visible.

## Grades workflow secrets

`Settings -> Secrets and variables -> Actions`:

- `GRADES_EMAIL`
- `GRADES_PASSWORD`

The SIS workflow is public-data-only and requires no login secrets.

# `data/` contract (worker-managed files)

The dashboard (`index.html` + `fetch-data.js`) reads these files with **no
live login**. All files here except this README and `notice.json` are written
by automation.

| File | Writer | Purpose |
|---|---|---|
| `enrollment.csv` | `fetch-enrollment.yml` (2-hourly) | Raw Grades `districts-enrollment` export. Latest (current) snapshot. |
| `enrollment_prev.csv` | `fetch-enrollment.yml` (first run of each PKT day) | **Midnight reference** snapshot for the current PKT day. Pinned on the day's first successful run and left untouched by the rest of that day's syncs. Matched by EMIS for the day-change Δ. |
| `meta.json` | `fetch-enrollment.yml` (each run) | `{fetched_at_utc, fetched_at_pkt, ref_date_pkt, sync_type, rows, bytes, source}` for the "last sync" label. `sync_type` is `reference` on the day's first run, `sync` afterwards. |
| `emis_wing.json` | `wing-map-once.yml` (**once**) | Static `{EMIS: Wing}` lookup restoring the Wing dimension the Grades export lacks. |
| `notice.json` | **Hand-edited by the dashboard owner** | Optional startup notice modal (see below). Never written by automation. |

Do not hand-edit the worker-managed files — the next worker run overwrites
them (except `emis_wing.json`, which is only rebuilt when the one-time
workflow runs). `notice.json` is the exception: edit it by hand.

## Startup notice (`notice.json`)

Controls the blocking popup shown when the dashboard loads. With
`"enabled": false` (the default) **nothing is shown at all**.

To inform users about a problem (data delayed, dashboard issue,
maintenance…), edit `data/notice.json`, commit and push:

```json
{
  "enabled": true,
  "id": "2026-10-15-data-delay",
  "type": "warning",
  "title": "Enrollment Data Delayed",
  "message": "Today's enrollment figures may not be up to date. Please check back later.",
  "durationSeconds": 30
}
```

- `enabled` — `true` shows the modal, `false` hides it completely.
- `id` — give **each new notice a new unique id**. The notice is shown only
  once per browser session, and a changed `id` is what makes an updated
  notice appear again for users who already saw the previous one.
- `type` — `info` (blue), `warning` (amber) or `critical` (red).
- `title` / `message` — plain text shown in the modal.
- `durationSeconds` — auto-close time (default `30`).

When shown, the modal blocks the dashboard behind it, displays a countdown
bar ("Auto-closing in 30s"), and can be closed early with the Close / ×
buttons or Escape; clicking outside it does not dismiss it. To stop showing
it, set `"enabled": false` and push again.

While `"enabled": true`, the small light beside the masthead's
`Last sync: … • N schools` chip also turns **red** instead of green. Unlike
the modal it is not limited to once per session — it stays red on every
visit until the notice is switched off, so users can still see the data is
flagged as not updating after they dismiss the popup. Setting
`"enabled": false` turns the light green again.

## Secrets required

`Settings -> Secrets and variables -> Actions`:

- `GRADES_EMAIL`
- `GRADES_PASSWORD`

## Testing the login without committing

`Actions -> Fetch Grades enrollment -> Run workflow` after adding secrets,
or locally: `GRADES_EMAIL=.. GRADES_PASSWORD=.. python scripts/fetch_grades.py --dry-run`

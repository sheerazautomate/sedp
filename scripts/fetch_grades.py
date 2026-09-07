#!/usr/bin/env python3
"""
Grades enrollment fetcher (runs in GitHub Actions, which has internet access).

Logs into the Grades portal and downloads the districts-enrollment CSV export
into data/enrollment.csv (kept fresh by 2-hourly syncs).

Reference (start-of-day) snapshot: the FIRST successful run of each PKT day
pins its freshly downloaded snapshot to data/enrollment_prev.csv and records
ref_date_pkt in data/meta.json. Every later run that day only refreshes
data/enrollment.csv and leaves the reference untouched, so the dashboard's
"Day change" compares current enrollment against that day's midnight snapshot
(the previous enrollment reference) for the whole day.

Required env vars (set as GitHub Actions secrets -- NEVER commit values):

Required env vars (set as GitHub Actions secrets -- NEVER commit values):
  GRADES_EMAIL       portal login email
  GRADES_PASSWORD    portal login password

Optional env vars:
  GRADES_LOGIN_URL     default https://grades.pesrp.edu.pk/login
  GRADES_EXPORT_URL    default https://grades.pesrp.edu.pk/districts-enrollment/export?district_id=&tehsil_id=&markaz_id=&schoolemis=
  GRADES_EMAIL_FIELD   default "email"      (login form field name)
  GRADES_PASSWORD_FIELD default "password"  (login form field name)
  GRADES_VERIFY_SSL    default "true"       (set "false" only if the portal's
                                            TLS chain breaks inside CI)
  DATA_DIR             default "data"       (relative to repo root)
  MIN_BYTES            default "50000"      (sanity floor: a full-province
                                            export must be bigger than this)
  FORCE_REFERENCE      default ""           ("true" -> pin this run as the day's
                                            reference even mid-day, e.g. if the
                                            first run of the day failed)

Usage:
  python scripts/fetch_grades.py            # fetch + rotate + write files
  python scripts/fetch_grades.py --dry-run  # login + report export size only

Exit codes: 0 ok, 1 config error, 2 login failed, 3 download/validation failed.
"""

import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is not installed. Run: pip install requests",
          file=sys.stderr)
    sys.exit(1)

LOGIN_URL = os.environ.get("GRADES_LOGIN_URL",
                            "https://grades.pesrp.edu.pk/login")
EXPORT_URL = os.environ.get(
    "GRADES_EXPORT_URL",
    "https://grades.pesrp.edu.pk/districts-enrollment/export"
    "?district_id=&tehsil_id=&markaz_id=&schoolemis=")
EMAIL_FIELD = os.environ.get("GRADES_EMAIL_FIELD", "email")
PASSWORD_FIELD = os.environ.get("GRADES_PASSWORD_FIELD", "password")
VERIFY_SSL = os.environ.get("GRADES_VERIFY_SSL", "true").lower() not in (
    "0", "false", "no")
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MIN_BYTES = int(os.environ.get("MIN_BYTES", "50000"))

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def log(msg):
    print(f"[fetch_grades] {msg}", flush=True)


def get_csrf_token(html):
    """Extract a Laravel-style CSRF token from a login page, if present."""
    m = re.search(
        r'name=["\']_token["\'][^>]*value=["\']([^"\']+)["\']', html)
    if m:
        return m.group(1)
    m = re.search(
        r'<meta\s+name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
        html)
    return m.group(1) if m else None


def looks_logged_out(html, url):
    """Heuristic: are we still looking at the login page?"""
    if "/login" in (url or ""):
        return True
    low = html[:5000].lower()
    return ('name="password"' in low and
            ('name="email"' in low or 'name="username"' in low) and
            'logout' not in low)


def login(session, email, password):
    """Return True on success, False on bad credentials/unexpected flow."""
    log(f"GET {LOGIN_URL}")
    r = session.get(LOGIN_URL, timeout=30, verify=VERIFY_SSL,
                    headers={"User-Agent": UA})
    r.raise_for_status()
    token = get_csrf_token(r.text)
    log("CSRF token found." if token else "No CSRF token (plain form).")

    payload = {EMAIL_FIELD: email, PASSWORD_FIELD: password}
    if token:
        payload["_token"] = token
    headers = {"User-Agent": UA, "Referer": LOGIN_URL}
    if token:
        headers["X-CSRF-TOKEN"] = token

    last_err = None
    for attempt in range(1, 4):
        try:
            log(f"POST login (attempt {attempt})")
            resp = session.post(LOGIN_URL, data=payload, headers=headers,
                                timeout=30, verify=VERIFY_SSL,
                                allow_redirects=True)
            if resp.status_code in (419, 429):
                last_err = f"HTTP {resp.status_code}"
                time.sleep(2 * attempt)
                continue
            if looks_logged_out(resp.text, resp.url):
                # Surface a hint from the page (validation errors etc.)
                snippet = re.sub(r"\s+", " ",
                                 resp.text[:1500].replace("\n", " "))
                last_err = (f"still on login page ({resp.url}). "
                            f"Snippet: {snippet[:300]}")
                return False
            log(f"Login OK (landed on {resp.url})")
            return True
        except requests.RequestException as exc:  # transient network issue
            last_err = repr(exc)
            log(f"Login request failed: {exc}")
            time.sleep(2 * attempt)
    log(f"Login failed: {last_err}")
    return False


def download_export(session):
    """Download the CSV export. Returns bytes. Raises on failure."""
    last_err = None
    for attempt in range(1, 4):
        try:
            log(f"GET export (attempt {attempt})")
            r = session.get(EXPORT_URL, timeout=120, verify=VERIFY_SSL,
                            headers={"User-Agent": UA,
                                     "Referer": LOGIN_URL,
                                     "Accept": "text/csv,*/*"})
            r.raise_for_status()
            body = r.content
            ctype = r.headers.get("Content-Type", "")
            if "text/html" in ctype and len(body) < MIN_BYTES:
                last_err = ("server returned HTML instead of CSV "
                            "(session probably expired)")
                time.sleep(2 * attempt)
                continue
            return body
        except requests.RequestException as exc:
            last_err = repr(exc)
            log(f"Export request failed: {exc}")
            time.sleep(3 * attempt)
    raise RuntimeError(f"export download failed: {last_err}")


def validate_csv(body):
    """Sanity checks: size, decodability, header row, data rows."""
    if len(body) < MIN_BYTES:
        raise ValueError(
            f"export too small ({len(body)} bytes < MIN_BYTES={MIN_BYTES})")
    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = body.decode("cp1252")  # tolerate Windows-encoded exports
    lines = text.splitlines()
    if len(lines) < 2:
        raise ValueError("export has no data rows")
    header = next(csv.reader([lines[0]]))
    if len(header) < 5 or not any("emis" in (c or "").lower()
                                  for c in header):
        raise ValueError(f"unexpected header row: {lines[0][:200]}")
    # Count non-empty data rows cheaply.
    rows = sum(1 for ln in lines[1:] if ln.strip())
    if rows < 1000:
        raise ValueError(f"suspiciously few data rows: {rows}")
    log(f"Validated CSV: {len(header)} cols, ~{rows} rows, "
        f"{len(body)} bytes")
    return rows


def main():
    dry_run = "--dry-run" in sys.argv
    email = os.environ.get("GRADES_EMAIL", "").strip()
    password = os.environ.get("GRADES_PASSWORD", "")
    if not email or not password:
        print("ERROR: GRADES_EMAIL / GRADES_PASSWORD env vars are required.",
              file=sys.stderr)
        return 1

    session = requests.Session()
    try:
        if not login(session, email, password):
            print("ERROR: login failed (bad credentials or form changed).",
                  file=sys.stderr)
            return 2
        body = download_export(session)
        rows = validate_csv(body)
    except Exception as exc:  # noqa: BLE001 - report and exit non-zero
        print(f"ERROR: {exc}", file=sys.stderr)
        return 3

    if dry_run:
        log(f"DRY RUN ok: {rows} rows, {len(body)} bytes. Nothing written.")
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cur_path = DATA_DIR / "enrollment.csv"
    prev_path = DATA_DIR / "enrollment_prev.csv"

    now_utc = dt.datetime.now(dt.timezone.utc)
    pkt = now_utc + dt.timedelta(hours=5)
    today_pkt = pkt.strftime("%Y-%m-%d")

    # First successful run of a new PKT day becomes the midnight reference for
    # that whole day. We key off the PKT date in meta.json (not the wall clock)
    # so the snapshot is still taken even when GitHub Actions delays the
    # scheduled run by minutes or hours past 00:00.
    last_ref = None
    meta_path = DATA_DIR / "meta.json"
    if meta_path.exists():
        try:
            last_ref = json.loads(meta_path.read_text()).get("ref_date_pkt")
        except Exception:
            last_ref = None
    is_reference = last_ref != today_pkt
    force_ref = os.environ.get("FORCE_REFERENCE", "").strip().lower() in (
        "1", "true", "yes")
    if force_ref:
        is_reference = True

    if is_reference:
        prev_path.write_bytes(body)
        log(f"REFERENCE run: pinned this snapshot to {prev_path} for {today_pkt}")
    else:
        log(f"SYNC run: refreshing {cur_path}; reference {prev_path} left untouched")
    cur_path.write_bytes(body)
    log(f"Wrote {cur_path} ({len(body)} bytes)")

    meta = {
        "fetched_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fetched_at_pkt": pkt.strftime("%Y-%m-%d %I:%M %p PKT"),
        "ref_date_pkt": today_pkt,
        "sync_type": "reference" if is_reference else "sync",
        "rows": rows,
        "bytes": len(body),
        "source": "grades.pesrp.edu.pk districts-enrollment export",
    }
    meta_path.write_text(json.dumps(meta, indent=2))
    log(f"Wrote meta.json {meta['fetched_at_pkt']} ({meta['sync_type']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

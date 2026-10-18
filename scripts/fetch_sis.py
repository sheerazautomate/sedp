#!/usr/bin/env python3
"""Fetch school-level gender-wise current enrollment from the public SIS dashboard.

The DTMS mapping in data/school_ids.jsonl supplies each school's SIS district,
tehsil, markaz and school IDs. For each mapped school, this script calls the
same endpoint used by the SIS dashboard:
  POST /dashboard_revamp/get_gender_summary_pie

No SIS login is used. Each worker owns a separate requests session so it can
safely follow SIS's rotating CSRF token without sharing cookies between threads.

Output files:
  data/sis_enrollment.json       latest successful scrape
  data/sis_enrollment_prev.json  first successful scrape of each PKT day
  data/sis_meta.json             latest fetch + reference-date metadata

The dashboard joins these current values to Grades baseline/target data by EMIS.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: 'requests' is required. Install with: pip install requests",
          file=sys.stderr)
    raise SystemExit(1)

BASE_URL = os.environ.get("SIS_BASE_URL", "https://sis.pesrp.edu.pk").rstrip("/")
DASHBOARD_URL = BASE_URL + "/dashboard"
DTMS_URL = BASE_URL + "/dashboard/get_dtms_by_emis_code"
GENDER_URL = BASE_URL + "/dashboard_revamp/get_gender_summary_pie"
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
IDS_PATH = Path(os.environ.get("SIS_IDS_PATH", str(DATA_DIR / "school_ids.jsonl")))
CURRENT_PATH = DATA_DIR / "sis_enrollment.json"
PREV_PATH = DATA_DIR / "sis_enrollment_prev.json"
META_PATH = DATA_DIR / "sis_meta.json"

DEFAULT_WORKERS = 6
DEFAULT_MAX_FAILURE_RATIO = 0.005  # keep the previous committed snapshot if >0.5% fail
DEFAULT_TIMEOUT = 40
MAX_RETRIES = 3
MAX_CONSECUTIVE_FAILURES = 12
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:153.0) "
    "Gecko/20100101 Firefox/153.0"
)


def log(message: str) -> None:
    print(f"[fetch_sis] {message}", flush=True)


def normalize_emis(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return re.sub(r"\.0$", "", text)


def parse_count(value: Any) -> int:
    if value is None:
        return 0
    text = str(value).strip().replace(",", "")
    if text in ("", "-", "--"):
        return 0
    try:
        number = float(text)
    except (TypeError, ValueError):
        raise ValueError(f"not a numeric enrollment count: {value!r}")
    if number < 0:
        raise ValueError(f"enrollment count cannot be negative: {value!r}")
    return int(round(number))


def load_school_ids(path: Path) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Read JSONL mappings, returning usable records and skipped status counts."""
    if not path.exists():
        raise FileNotFoundError(f"DTMS mapping file not found: {path}")

    schools: list[dict[str, str]] = []
    skipped: dict[str, int] = {}
    seen: set[str] = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"Expected an object at {path}:{line_number}")

            status = str(item.get("status") or "unknown").strip().lower()
            if status != "ok":
                skipped[status] = skipped.get(status, 0) + 1
                continue

            emis = normalize_emis(item.get("emis_code") or item.get("emis_code_api"))
            fields = {
                "emis": emis,
                "district": str(item.get("district_id") or "").strip(),
                "tehsil": str(item.get("tehsil_id") or "").strip(),
                "markaz": str(item.get("markaz_id") or "").strip(),
                "school": str(item.get("school_id") or "").strip(),
            }
            missing = [key for key, value in fields.items() if not value]
            if missing:
                raise ValueError(
                    f"Incomplete status=ok mapping at {path}:{line_number}; "
                    f"missing {', '.join(missing)}"
                )
            if emis in seen:
                raise ValueError(f"Duplicate EMIS code {emis!r} in {path}:{line_number}")
            seen.add(emis)
            schools.append(fields)

    if not schools:
        raise ValueError(f"No usable status=ok school mappings found in {path}")
    return schools, skipped


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": DASHBOARD_URL,
    })
    return session


def find_csrf_token(session: requests.Session, seed_emis: str) -> str:
    """Initialize a public SIS session and get its CSRF token from the cookie."""
    response = session.get(
        DTMS_URL,
        params={"s_id_emis_code": seed_emis},
        timeout=(10, DEFAULT_TIMEOUT),
    )
    response.raise_for_status()
    token = session.cookies.get("csrf_cookie_name")

    # Fallback for a deployment that only initializes its CSRF cookie on /dashboard.
    if not token:
        page = session.get(DASHBOARD_URL, timeout=(10, DEFAULT_TIMEOUT))
        page.raise_for_status()
        token = session.cookies.get("csrf_cookie_name")
        if not token:
            match = re.search(
                r'name=["\']csrf_test_name["\'][^>]*value=["\']([^"\']+)',
                page.text,
                flags=re.IGNORECASE,
            )
            token = match.group(1) if match else None
    if not token:
        raise RuntimeError("SIS did not provide a CSRF token for a new session")
    return str(token)


def fetch_one(
    session: requests.Session,
    csrf_token: str,
    school: dict[str, str],
    seed_emis: str,
) -> tuple[dict[str, Any], str]:
    """Fetch one school's male/female/other/total current enrollment."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        # Prefer the token returned by the preceding SIS response. The cookie is
        # the initial source of truth and is refreshed below if a request fails.
        csrf_token = csrf_token or session.cookies.get("csrf_cookie_name")
        payload = {
            "district": school["district"],
            "tehsil": school["tehsil"],
            "markaz": school["markaz"],
            "school": school["school"],
            "s_id_emis_code": "",
            "csrf_test_name": csrf_token,
        }
        try:
            response = session.post(
                GENDER_URL,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Referer": DASHBOARD_URL,
                },
                timeout=(10, DEFAULT_TIMEOUT),
            )
            if response.status_code in (403, 419):
                raise RuntimeError(f"SIS rejected the CSRF token (HTTP {response.status_code})")
            response.raise_for_status()
            try:
                body = response.json()
            except ValueError as exc:
                raise RuntimeError("SIS returned a non-JSON gender summary") from exc
            if not isinstance(body, dict) or "male_count" not in body or "female_count" not in body:
                raise RuntimeError("SIS gender summary is missing male_count or female_count")

            male = parse_count(body.get("male_count"))
            female = parse_count(body.get("female_count"))
            other = parse_count(body.get("other_count"))
            total_value = body.get("total")
            total = (
                parse_count(total_value)
                if total_value is not None and str(total_value).strip() not in ("", "-", "--")
                else male + female + other
            )
            # Preserve the API total even if it differs from M+F+Other.
            record = {
                "emis": school["emis"],
                "curM": male,
                "curF": female,
                "curOther": other,
                "curT": total,
            }
            rotated = body.get("csrf_test_name") or session.cookies.get("csrf_cookie_name")
            if not rotated:
                raise RuntimeError("SIS response did not provide a renewed CSRF token")
            return record, str(rotated)
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            last_error = exc
            # The response may already have rotated the cookie, including on an
            # error page. Prefer it; otherwise establish a fresh session token.
            refreshed = session.cookies.get("csrf_cookie_name")
            if refreshed and str(refreshed) != str(csrf_token):
                csrf_token = str(refreshed)
            elif attempt < MAX_RETRIES:
                csrf_token = find_csrf_token(session, seed_emis)
            if attempt < MAX_RETRIES:
                time.sleep(min(8, 2 ** (attempt - 1)))

    raise RuntimeError(str(last_error or "unknown SIS request error"))


def pkt_now() -> tuple[dt.datetime, str]:
    now_utc = dt.datetime.now(dt.timezone.utc)
    pkt = now_utc + dt.timedelta(hours=5)
    return pkt, pkt.strftime("%Y-%m-%d")


def atomic_write_json(path: Path, payload: dict[str, Any], *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    if compact:
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    else:
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    temp.write_text(text + "\n", encoding="utf-8")
    os.replace(temp, path)


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def scrape(
    schools: list[dict[str, str]],
    skipped: dict[str, int],
    workers: int,
    delay: float,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
    tasks: queue.Queue[dict[str, str]] = queue.Queue()
    for school in schools:
        tasks.put(school)

    successes: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, str]] = []
    lock = threading.Lock()
    stop = threading.Event()
    progress = {"processed": 0, "succeeded": 0, "failed": 0}

    def worker(worker_number: int) -> None:
        seed_emis = schools[worker_number % len(schools)]["emis"]
        session = make_session()
        try:
            token = find_csrf_token(session, seed_emis)
        except Exception as exc:  # noqa: BLE001 - startup failure is fatal to the scrape
            with lock:
                failures.append({"emis": seed_emis, "error": f"session init: {exc}"})
            stop.set()
            return

        consecutive_failures = 0
        try:
            while not stop.is_set():
                try:
                    school = tasks.get_nowait()
                except queue.Empty:
                    break
                try:
                    record, token = fetch_one(session, token, school, seed_emis)
                    with lock:
                        successes[school["emis"]] = record
                    consecutive_failures = 0
                except Exception as exc:  # noqa: BLE001 - report and continue on individual schools
                    with lock:
                        failures.append({"emis": school["emis"], "error": str(exc)[:240]})
                    consecutive_failures += 1
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        log(f"Worker {worker_number + 1}: {MAX_CONSECUTIVE_FAILURES} consecutive failures; stopping workers")
                        stop.set()
                finally:
                    with lock:
                        progress["processed"] += 1
                        if school["emis"] in successes:
                            progress["succeeded"] += 1
                        else:
                            progress["failed"] += 1
                        processed = progress["processed"]
                        if processed % 1000 == 0:
                            log(
                                f"Progress {processed:,}/{len(schools):,}: "
                                f"{progress['succeeded']:,} ok, {progress['failed']:,} failed"
                            )
                if delay > 0:
                    time.sleep(delay)
        finally:
            session.close()

    worker_count = max(1, min(int(workers), len(schools)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(worker, i) for i in range(worker_count)]
        for future in concurrent.futures.as_completed(futures):
            future.result()

    attempted = progress["processed"]
    unprocessed = len(schools) - attempted
    if unprocessed:
        failures.extend(
            {"emis": "", "error": f"scrape stopped before {unprocessed:,} mapped schools were attempted"}
            for _ in range(1)
        )
    failure_count = len(schools) - len(successes)
    return list(successes.values()), failures, {
        "mapped": len(schools),
        "processed": attempted,
        "succeeded": len(successes),
        "failed": failure_count,
        "unmapped": sum(skipped.values()),
        "skipped_statuses": skipped,
        "workers": worker_count,
    }


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    try:
        workers = int(os.environ.get("SIS_WORKERS", str(DEFAULT_WORKERS)))
        if workers < 1 or workers > 32:
            raise ValueError("SIS_WORKERS must be between 1 and 32")
        delay = float(os.environ.get("SIS_REQUEST_DELAY_SECONDS", "0"))
        if delay < 0:
            raise ValueError("SIS_REQUEST_DELAY_SECONDS cannot be negative")
        max_failure_ratio = float(os.environ.get(
            "SIS_MAX_FAILURE_RATIO", str(DEFAULT_MAX_FAILURE_RATIO)
        ))
        if not 0 <= max_failure_ratio < 1:
            raise ValueError("SIS_MAX_FAILURE_RATIO must be from 0 up to (but not including) 1")

        schools, skipped = load_school_ids(IDS_PATH)
        log(
            f"Loaded {len(schools):,} usable DTMS mappings from {IDS_PATH}; "
            f"skipped statuses: {skipped or 'none'}"
        )
        if dry_run:
            log("DRY RUN: mappings validated; no SIS requests and no files written.")
            return 0

        records, failures, stats = scrape(schools, skipped, workers, delay)
        allowed_failures = max(10, int(stats["mapped"] * max_failure_ratio))
        if stats["failed"] > allowed_failures:
            examples = "; ".join(
                f"{item.get('emis') or 'unprocessed'}: {item['error']}"
                for item in failures[:5]
            )
            raise RuntimeError(
                f"SIS scrape incomplete: {stats['failed']:,}/{stats['mapped']:,} mapped schools "
                f"failed (allowed {allowed_failures:,}). Previous snapshot was left unchanged. "
                f"Examples: {examples}"
            )
        if not records:
            raise RuntimeError("SIS returned no school enrollment records; previous snapshot was left unchanged")

        pkt, today_pkt = pkt_now()
        now_utc = dt.datetime.now(dt.timezone.utc)
        current_payload: dict[str, Any] = {
            "fetched_at_utc": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fetched_at_pkt": pkt.strftime("%Y-%m-%d %I:%M %p PKT"),
            "source": "sis.pesrp.edu.pk dashboard_revamp/get_gender_summary_pie",
            "requested": stats["mapped"],
            "school_count": len(records),
            "failed": stats["failed"],
            "unmapped": stats["unmapped"],
            "schools": sorted(records, key=lambda item: item["emis"]),
        }

        previous_meta = read_json(META_PATH) or {}
        force_reference = os.environ.get("FORCE_REFERENCE", "").strip().lower() in (
            "1", "true", "yes"
        )
        is_reference = (
            force_reference
            or previous_meta.get("ref_date_pkt") != today_pkt
            or not PREV_PATH.exists()
        )
        if is_reference:
            atomic_write_json(PREV_PATH, current_payload, compact=True)
            log(f"Pinned SIS reference snapshot to {PREV_PATH} for PKT date {today_pkt}")

        atomic_write_json(CURRENT_PATH, current_payload, compact=True)
        meta = {
            "fetched_at_utc": current_payload["fetched_at_utc"],
            "fetched_at_pkt": current_payload["fetched_at_pkt"],
            "ref_date_pkt": today_pkt if is_reference else previous_meta.get("ref_date_pkt"),
            "sync_type": "reference" if is_reference else "sync",
            "source": current_payload["source"],
            "rows": len(records),
            "requested": stats["mapped"],
            "failed": stats["failed"],
            "unmapped": stats["unmapped"],
            "skipped_statuses": stats["skipped_statuses"],
            "workers": stats["workers"],
            "bytes": CURRENT_PATH.stat().st_size,
            "failure_examples": failures[:10],
        }
        atomic_write_json(META_PATH, meta)
        log(
            f"SIS sync complete: {len(records):,}/{stats['mapped']:,} mapped schools saved; "
            f"{stats['failed']:,} failed, {stats['unmapped']:,} unmapped; "
            f"{current_payload['fetched_at_pkt']}"
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - CI should surface a concise failure
        log(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

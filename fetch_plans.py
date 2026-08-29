"""
Discovers and downloads EHC Winterthur "Wochenplan" training-schedule PDFs
from the club's WordPress REST API.

The endpoint returns clean structured JSON (source_url, filename, title,
modified) and was verified to be more reliable than scraping the
/artikel/trainingsplaene/ HTML page.
"""

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

MEDIA_API_URL = "https://ehc-winterthur.ch/wp-json/wp/v2/media"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
TIMEZONE = ZoneInfo("Europe/Zurich")

# Matches the week number out of filenames like "Wochenplan-34.pdf",
# "Wochenplan-34_NEU.pdf", "Wochenplan-34_Neu_1.pdf".
WEEK_NUMBER_RE = re.compile(r"^Wochenplan-(\d+)", re.IGNORECASE)


def week_key_from_name(filename: str) -> str:
    """Groups revisions of the same week's plan together by week number.

    A revised plan is republished under a new filename (e.g.
    "Wochenplan-34_Neu_1.pdf" superseding "Wochenplan-34.pdf") rather than
    overwriting the old one, so older revisions stick around unless
    de-duplicated by week number here.
    """
    match = WEEK_NUMBER_RE.match(filename)
    return match.group(1) if match else filename


def _week_key(entry: dict) -> str:
    return week_key_from_name(entry["filename"])


def latest_local_pdfs(download_dir: Path = DOWNLOAD_DIR) -> list[Path]:
    """The latest downloaded PDF per week, newest week first. Guards against a
    superseded revision still lingering on disk (fetch only downloads the
    latest, but never deletes the old file), keeping the most recently
    modified file per week number."""
    latest: dict[str, Path] = {}
    for path in download_dir.glob("Wochenplan-*.pdf"):
        key = week_key_from_name(path.name)
        current = latest.get(key)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            latest[key] = path
    return sorted(latest.values(), key=lambda p: week_key_from_name(p.name), reverse=True)


def list_wochenplan_pdfs() -> list[dict]:
    """Returns the latest media entry per Wochenplan week, newest first,
    restricted to the current and future weeks.

    Past weeks are skipped (their events wouldn't be synced anyway), and older
    revisions of the same week (superseded filenames) are dropped - only the
    most recently modified entry per week number is kept.
    """
    entries = []
    page = 1
    while True:
        resp = requests.get(
            MEDIA_API_URL,
            params={
                "media_type": "application",
                "search": "Wochenplan",
                "per_page": 100,
                "page": page,
            },
            timeout=30,
        )
        if resp.status_code == 400:
            # WordPress returns 400 once `page` exceeds the total page count.
            break
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        entries.extend(batch)
        page += 1

    pdfs = [e for e in entries if e.get("mime_type") == "application/pdf"]

    today = datetime.now(TIMEZONE).date()
    latest_per_week: dict[str, dict] = {}
    for entry in pdfs:
        match = WEEK_NUMBER_RE.match(entry["filename"])
        if match and not _week_is_current_or_future(int(match.group(1)), today):
            continue  # skip weeks that have already passed
        key = _week_key(entry)
        current = latest_per_week.get(key)
        if current is None or entry["modified"] > current["modified"]:
            latest_per_week[key] = entry

    result = list(latest_per_week.values())
    result.sort(key=lambda e: e["modified"], reverse=True)
    return result


def _week_is_current_or_future(week_num: int, today: date) -> bool:
    """Whether ISO week `week_num` is the current week or a future one.

    The filename only carries the week number, which restarts at 1 each new
    year, so week 2 in December means *next* January. Resolve the week to its
    occurrence nearest today (checking the previous/current/next year), then
    keep it if that week hasn't fully passed."""
    iso = today.isocalendar()
    current_monday = date.fromisocalendar(iso[0], iso[1], 1)

    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date.fromisocalendar(year, week_num, 1))
        except ValueError:
            pass  # e.g. week 53 in a year that only has 52
    if not candidates:
        return True  # unparseable - keep rather than risk dropping a real week

    resolved_monday = min(candidates, key=lambda d: abs((d - current_monday).days))
    return resolved_monday + timedelta(days=6) >= today  # Sunday not before today


def download_pdf(entry: dict, download_dir: Path = DOWNLOAD_DIR) -> Path:
    """Downloads a media entry's PDF, skipping it if already present (relevant
    only for local runs; on Lambda nothing persists between invocations)."""
    download_dir.mkdir(parents=True, exist_ok=True)
    dest = download_dir / entry["filename"]
    if dest.exists():
        return dest

    resp = requests.get(entry["source_url"], timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def fetch_all(download_dir: Path = DOWNLOAD_DIR) -> list[Path]:
    """Fetches the latest Wochenplan PDFs, downloading only those missing or
    newer than the local copy, continuing past any single download failure so
    one bad file doesn't hide the other weeks. Warns loudly per failure so a
    missing week is never silent."""
    pdfs = list_wochenplan_pdfs()
    paths = []
    for entry in pdfs:
        try:
            paths.append(download_pdf(entry, download_dir))
        except Exception as exc:
            print(f"  WARN: could not download {entry.get('filename', '?')}: {exc}")
    return paths


if __name__ == "__main__":
    paths = fetch_all()
    for path in paths:
        print(path)

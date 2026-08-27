"""
Discovers and downloads EHC Winterthur "Wochenplan" training-schedule PDFs
from the club's WordPress REST API.

The endpoint returns clean structured JSON (source_url, filename, title,
modified) and was verified to be more reliable than scraping the
/artikel/trainingsplaene/ HTML page.
"""

import re
from pathlib import Path

import requests

MEDIA_API_URL = "https://ehc-winterthur.ch/wp-json/wp/v2/media"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"

# Matches the week number out of filenames like "Wochenplan-34.pdf",
# "Wochenplan-34_NEU.pdf", "Wochenplan-34_Neu_1.pdf".
WEEK_NUMBER_RE = re.compile(r"^Wochenplan-(\d+)", re.IGNORECASE)


def _week_key(entry: dict) -> str:
    """Groups revisions of the same week's plan together.

    A revised plan is republished under a new filename (e.g.
    "Wochenplan-34_Neu_1.pdf" superseding "Wochenplan-34.pdf") rather than
    overwriting the old one, so older revisions stick around in the media
    library as obsolete clutter unless de-duplicated by week number here.
    """
    match = WEEK_NUMBER_RE.match(entry["filename"])
    return match.group(1) if match else entry["filename"]


def list_wochenplan_pdfs() -> list[dict]:
    """Returns the latest media entry per week's Wochenplan PDF, newest first.

    Older revisions of the same week (superseded filenames) are dropped -
    only the most recently modified entry per week number is kept.
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

    latest_per_week: dict[str, dict] = {}
    for entry in pdfs:
        key = _week_key(entry)
        current = latest_per_week.get(key)
        if current is None or entry["modified"] > current["modified"]:
            latest_per_week[key] = entry

    result = list(latest_per_week.values())
    result.sort(key=lambda e: e["modified"], reverse=True)
    return result


def download_pdf(entry: dict, download_dir: Path = DOWNLOAD_DIR) -> Path:
    """Downloads a single media entry's PDF, skipping it if already present."""
    download_dir.mkdir(parents=True, exist_ok=True)
    filename = entry["filename"]
    dest = download_dir / filename
    if dest.exists():
        return dest

    resp = requests.get(entry["source_url"], timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def fetch_all(download_dir: Path = DOWNLOAD_DIR) -> list[Path]:
    """Fetches all Wochenplan PDFs not already present locally."""
    pdfs = list_wochenplan_pdfs()
    return [download_pdf(entry, download_dir) for entry in pdfs]


if __name__ == "__main__":
    paths = fetch_all()
    for path in paths:
        print(path)

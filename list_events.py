"""
Dry-run: parse every downloaded Wochenplan, extract the configured teams'
events, and print them as text for verification. Writes the same listing to
events.txt. No Google Calendar calls.
"""

from pathlib import Path

from extract_events import Event, extract_events
from parse_plan import parse_week

try:
    from sync_configs import CONFIGS
except ImportError:  # fall back to the example so the script still runs
    from sync_configs_example import CONFIGS

DOWNLOAD_DIR = Path(__file__).parent / "downloads"
OUTPUT_FILE = Path(__file__).parent / "events.txt"


def _format_event(event: Event) -> str:
    when = event.day_date.strftime("%a %d.%m.%Y")
    if event.all_day:
        time = "all-day".ljust(11)
    else:
        time = f"{event.time_start}-{event.time_end}"
    lines = [f"  {when}  {time}  {event.summary}"]
    detail = []
    if event.opponent:
        detail.append(f"opponent={event.opponent}")
    if event.place:
        detail.append(f"place={event.place}")
    if event.garderobe:
        detail.append(f"Garderobe={event.garderobe}")
    if event.transport:
        detail.append(f"Trsp={event.transport}")
    if detail:
        lines.append("      " + "  ".join(detail))
    for note in event.notes:
        lines.append(f"      ({note})")
    return "\n".join(lines)


def main():
    pdfs = sorted(DOWNLOAD_DIR.glob("Wochenplan-*.pdf"))
    blocks: list[str] = []

    for config in CONFIGS:
        team = config["team"]
        blocks.append(f"===== {team}  ->  {config['calendar_id']} =====")
        for pdf in pdfs:
            week = parse_week(pdf)
            events = extract_events(week, config)
            if not events:
                continue
            blocks.append(f"\n{pdf.name}  ({len(events)} events)")
            for event in events:
                blocks.append(_format_event(event))
        blocks.append("")

    output = "\n".join(blocks)
    print(output)
    OUTPUT_FILE.write_text(output + "\n")


if __name__ == "__main__":
    main()

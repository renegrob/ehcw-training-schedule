"""
Dry-run: parse every downloaded Wochenplan, extract the configured teams'
events, and print them as text for verification. Writes the same listing to
events.txt. No Google Calendar calls.

Uses safe_extract, so a broken/renamed/reformatted PDF surfaces as a visible
⚠️ FEHLER event rather than silently producing nothing.
"""

from pathlib import Path

from extract_events import Event, safe_extract
from fetch_plans import latest_local_pdfs

try:
    from sync_configs import CONFIGS
except ImportError:  # fall back to the example so the script still runs
    from sync_configs_example import CONFIGS

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
    pdfs = sorted(latest_local_pdfs(), key=lambda p: p.name)
    blocks: list[str] = []
    error_count = 0

    for config in CONFIGS:
        team = config["team"]
        blocks.append(f"===== {team}  ->  {config['calendar_id']} =====")
        for pdf in pdfs:
            events = safe_extract(pdf, config)
            if not events:
                continue
            errors = sum(1 for e in events if e.is_error)
            error_count += errors
            suffix = f", {errors} FEHLER" if errors else ""
            blocks.append(f"\n{pdf.name}  ({len(events)} events{suffix})")
            for event in events:
                blocks.append(_format_event(event))
        blocks.append("")

    if error_count:
        blocks.append(f"⚠️  {error_count} FEHLER - bitte diese Wochen manuell prüfen.")
    else:
        blocks.append("Keine Fehler.")

    output = "\n".join(blocks)
    print(output)
    OUTPUT_FILE.write_text(output + "\n")


if __name__ == "__main__":
    main()

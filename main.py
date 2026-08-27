"""
Fetches the current Wochenplan PDFs and converts each to Markdown for manual
inspection. No calendar-sync or team/row extraction logic yet.
"""

from convert_to_markdown import convert_all
from fetch_plans import fetch_all


def main():
    pdf_paths = fetch_all()
    print(f"Fetched {len(pdf_paths)} Wochenplan PDF(s):")
    for path in pdf_paths:
        print(f"  {path}")

    md_paths = convert_all(pdf_paths)
    print(f"\nConverted {len(md_paths)} to Markdown:")
    for path in md_paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()

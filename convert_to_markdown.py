"""
Converts downloaded Wochenplan PDFs into Markdown tables.

Uses pdfplumber's vector-line-based table extraction rather than docling:
the Wochenplan grid is a real (non-scanned) PDF with actual vector
gridlines and embedded text, and docling's ML table-structure model
(even in ACCURATE mode) merges adjacent team rows together - e.g. "MHL"
and "U21 Top" collapse into one row. pdfplumber reads the vector grid
directly and separates every row correctly.

The full document (including the legend and the trailing "Bemerkungen"
remarks row) is kept, since later extraction needs both.
"""

from pathlib import Path

from parse_plan import extract_tables

MARKDOWN_DIR = Path(__file__).parent / "markdown"


def _forward_fill_rows(rows: list[list[str | None]]) -> list[list[str]]:
    """Fills merged cells (pdfplumber represents a spanned cell's extra grid
    positions as None) with the value from the cell above, so every row is
    self-contained once flattened into a markdown table row. A cell that is
    merely an empty string (a real, distinct cell with no text - e.g. no
    session that day) is left blank, not filled in."""
    filled: list[list[str]] = []
    for row in rows:
        filled_row = []
        for col_idx, cell in enumerate(row):
            if cell is None:
                above = filled[-1][col_idx] if filled else ""
                filled_row.append(above)
            else:
                filled_row.append(cell.replace("\n", " ").strip())
        filled.append(filled_row)
    return filled


def _rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    lines = []
    header = rows[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")
    for row in rows[1:]:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def convert_pdf(pdf_path: Path, markdown_dir: Path = MARKDOWN_DIR) -> Path:
    """Converts a single PDF to Markdown, skipping it if already converted."""
    markdown_dir.mkdir(parents=True, exist_ok=True)
    dest = markdown_dir / (pdf_path.stem + ".md")
    if dest.exists():
        return dest

    sections = []
    for raw_rows in extract_tables(pdf_path):
        filled_rows = _forward_fill_rows(raw_rows)
        sections.append(_rows_to_markdown(filled_rows))

    dest.write_text("\n\n".join(sections))
    return dest


def convert_all(pdf_paths: list[Path], markdown_dir: Path = MARKDOWN_DIR) -> list[Path]:
    return [convert_pdf(pdf_path, markdown_dir) for pdf_path in pdf_paths]


if __name__ == "__main__":
    import sys

    for arg in sys.argv[1:]:
        print(convert_pdf(Path(arg)))

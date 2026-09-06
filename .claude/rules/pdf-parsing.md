# PDF parsing

Use **pdfplumber**, not docling.

- The **Wochenplan** is a real (non-scanned) PDF with actual vector gridlines and
  embedded text. docling's ML table-structure model — even in ACCURATE mode — merged
  adjacent team rows (e.g. "MHL" and "U21 Top" collapsed into one). pdfplumber reads
  the vector grid directly and separates every row/column correctly. Don't swap the
  parser without re-checking row separation on a real Wochenplan.
- The **Spielplan** is a fixed-column report, *not* a vector table
  (`find_tables()` returns nothing). Columns are recovered from the header row's word
  x-positions in `parse_spielplan.py`. If layout handling changes, re-verify against a
  real Spielplan PDF (watch the glued "Spielrunde"/"Datum" column).

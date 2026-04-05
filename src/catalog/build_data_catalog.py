"""
Scan everything under data/raw/ and write a simple inventory to CSV.

Run from the project root (see README or comments at the bottom of this file).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Paths: find the project root from this file's location
# ---------------------------------------------------------------------------
# This file lives at:  <project>/src/catalog/build_data_catalog.py
# We go up three levels: catalog -> src -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Folder we scan (all files inside it, recursively)
RAW_ROOT = PROJECT_ROOT / "data" / "raw"

# Where the CSV report is written (folder must exist or we create it)
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "tables"
OUTPUT_CSV = OUTPUT_DIR / "data_catalog.csv"

# First-level folder names under data/raw/ that we treat as known groups
KNOWN_GROUPS = frozenset({"ddl", "documentation", "graph"})


def classify_top_level_group(relative_to_raw: Path) -> str:
    """
    Decide the 'top_level_group' from a path relative to data/raw/.

    Examples:
      ddl/foo.sql              -> "ddl"
      documentation/bar.txt    -> "documentation"
      graph/GRAPH_DATA_MODEL.md -> "graph"
      readme.md                -> "other"  (sits directly under raw, not in a known folder)
      some_new_folder/file.txt -> "other"
    """
    parts = relative_to_raw.parts
    if not parts:
        return "other"

    first = parts[0]
    if first in KNOWN_GROUPS:
        return first
    return "other"


def build_rows() -> list[dict[str, str]]:
    """
    Walk data/raw/ recursively and collect one dict per file.
    """
    rows: list[dict[str, str]] = []

    if not RAW_ROOT.is_dir():
        raise FileNotFoundError(
            f"Expected a folder at {RAW_ROOT!s}. "
            "Create data/raw/ or run this script from the correct project root."
        )

    # rglob("*") visits every file and folder under RAW_ROOT; we keep only files
    for path in sorted(RAW_ROOT.rglob("*")):
        if not path.is_file():
            continue

        # Path compared to RAW_ROOT, e.g. "ddl/Create_Table__....sql"
        rel_to_raw = path.relative_to(RAW_ROOT)

        rows.append(
            {
                # Location inside data/raw/ (forward slashes in CSV on every OS)
                "relative_path": rel_to_raw.as_posix(),
                "file_name": path.name,
                "extension": path.suffix.lower() if path.suffix else "",
                "top_level_group": classify_top_level_group(rel_to_raw),
            }
        )

    return rows


def main() -> None:
    rows = build_rows()

    # Turn the list of dicts into a table (DataFrame) and save as CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    # UTF-8 so names with special characters stay readable
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")

    print(f"Wrote {len(df)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

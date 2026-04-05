"""
Build a richer CSV inventory of everything under data/raw/.

Run from the project root:
    python src/catalog/build_source_inventory.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Same layout as build_data_catalog.py: this file is src/catalog/*.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAW_ROOT = PROJECT_ROOT / "data" / "raw"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "tables"
OUTPUT_CSV = OUTPUT_DIR / "source_inventory.csv"

# First segment under data/raw/ that we treat as a known group
KNOWN_GROUPS = frozenset({"ddl", "documentation", "graph"})

# Exact filename for the Neo4j graph spec (special case for inferred_source_type)
GRAPH_MODEL_FILE = "GRAPH_DATA_MODEL.md"


def classify_top_level_group(relative_to_raw: Path) -> str:
    """
    Map the first folder under data/raw/ to ddl | documentation | graph | other.
    Files sitting directly under raw/ (e.g. readme.md) are "other".
    """
    parts = relative_to_raw.parts
    if not parts:
        return "other"
    first = parts[0]
    if first in KNOWN_GROUPS:
        return first
    return "other"


def infer_inferred_table_name(path: Path) -> str:
    """
    Pull a logical name from common filename patterns; empty string if none applies.

    - Create_Table__T_NORM_CLAIM.sql  ->  T_NORM_CLAIM
    - Create_View__V_FOO.sql          ->  V_FOO
    - docs__T_NORM_CLAIM.txt          ->  T_NORM_CLAIM  (text after docs__)
    """
    stem = path.stem  # filename without extension
    name = path.name

    if name.endswith(".sql"):
        if stem.startswith("Create_Table__"):
            return stem[len("Create_Table__") :]
        if stem.startswith("Create_View__"):
            return stem[len("Create_View__") :]
        return ""

    if name.endswith(".txt") and stem.startswith("docs__"):
        return stem[len("docs__") :]

    return ""


def infer_inferred_source_type(path: Path) -> str:
    """
    High-level kind of source file. Order matters: graph model is markdown but special-cased first.
    """
    ext = path.suffix.lower()
    if path.name == GRAPH_MODEL_FILE:
        return "graph_model"
    if ext == ".sql":
        return "ddl"
    if ext == ".txt":
        return "documentation"
    if ext == ".md":
        return "markdown_doc"
    return "other"


def build_notes(path: Path, inferred_table_name: str, inferred_source_type: str) -> str:
    """
    Short human-readable hints for odd files or pattern mismatches.
    """
    name = path.name
    stem = path.stem
    ext = path.suffix.lower()

    if name == ".DS_Store":
        return "macOS folder metadata; usually ignored for analysis."

    if name == ".gitkeep":
        return "Placeholder so empty directories are tracked in git."

    if ext == ".sql" and not inferred_table_name:
        return "SQL file name does not match Create_Table__ or Create_View__ pattern."

    if ext == ".txt" and inferred_source_type == "documentation" and not inferred_table_name:
        return "Text file name does not start with docs__; treated as documentation by extension."

    if name == "readme.md":
        return "InvestigAI data catalog overview (markdown)."

    if name == GRAPH_MODEL_FILE:
        return "Neo4j LTC graph data model description."

    if inferred_source_type == "other":
        return f"No specific rule for extension {ext!r}; review manually."

    return ""


def scan_raw_tree() -> list[dict[str, str]]:
    """
    Walk data/raw/, return one row dict per file.
    """
    if not RAW_ROOT.is_dir():
        raise FileNotFoundError(
            f"Expected a folder at {RAW_ROOT}. "
            "Create data/raw/ or run this script from the correct project root."
        )

    rows: list[dict[str, str]] = []

    for path in sorted(RAW_ROOT.rglob("*")):
        if not path.is_file():
            continue

        rel_to_raw = path.relative_to(RAW_ROOT)
        ext = path.suffix.lower() if path.suffix else ""

        inferred_table_name = infer_inferred_table_name(path)
        inferred_source_type = infer_inferred_source_type(path)
        notes = build_notes(path, inferred_table_name, inferred_source_type)

        rows.append(
            {
                "relative_path": rel_to_raw.as_posix(),
                "file_name": path.name,
                "extension": ext,
                "top_level_group": classify_top_level_group(rel_to_raw),
                "inferred_table_name": inferred_table_name,
                "inferred_source_type": inferred_source_type,
                "notes": notes,
            }
        )

    return rows


def main() -> None:
    rows = scan_raw_tree()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_CSV, index=False, encoding="utf-8")
    print(f"Wrote {len(df)} rows to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()

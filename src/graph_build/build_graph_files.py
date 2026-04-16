"""
Build prototype graph files (nodes + edges) as CSV.

Loads the synthetic PoC seed extracts under ``data/interim/poc_v1_seed/`` and writes
UTF-8 ``data/processed/nodes.csv`` and ``data/processed/edges.csv``.

If a seed file is missing, a warning is printed and that partition is skipped (empty
DataFrame). Edges are emitted only when both endpoint node ids exist in the built
node set (so partial seeds do not create dangling references).

Claim → Policy edges are synthesized from ``t_norm_claim.csv`` (``POLICY_NUMBER`` join),
per ``docs/poc_v1_graph_mapping.md`` — not present as a crosswalk file.

Run:  python src/graph_build/build_graph_files.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

# Project root: src/graph_build -> src -> project
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DEFAULT_SEED_DIR = PROJECT_ROOT / "data" / "interim" / "poc_v1_seed"
SEED_DIR = DEFAULT_SEED_DIR

NODES_CSV = PROCESSED_DIR / "nodes.csv"
EDGES_CSV = PROCESSED_DIR / "edges.csv"

# Seed filenames (synthetic extracts)
SEED_PERSON = "t_resolved_person.csv"
SEED_BUSINESS = "t_resolved_business.csv"
SEED_POLICY = "t_norm_policy.csv"
SEED_CLAIM = "t_norm_claim.csv"
SEED_ADDRESS = "t_resolved_address.csv"
SEED_BANK_ACCOUNT = "t_resolved_bank_account.csv"
SEED_PERSON_ADDRESS = "t_resolved_person_address_crosswalk.csv"
SEED_BUSINESS_ADDRESS = "t_resolved_business_address_crosswalk.csv"
SEED_PERSON_PERSON = "t_resolved_person_person_crosswalk.csv"
SEED_PERSON_POLICY = "t_resolved_person_policy_crosswalk.csv"
SEED_PERSON_BANK = "t_resolved_person_bank_account_crosswalk.csv"

SOURCE_TABLE_PERSON = "T_RESOLVED_PERSON"
SOURCE_TABLE_BUSINESS = "T_RESOLVED_BUSINESS"
SOURCE_TABLE_POLICY = "T_NORM_POLICY"
SOURCE_TABLE_CLAIM = "T_NORM_CLAIM"
SOURCE_TABLE_ADDRESS = "T_RESOLVED_ADDRESS"
SOURCE_TABLE_BANK = "T_RESOLVED_BANK_ACCOUNT"

NODE_COLUMNS = ["node_id", "node_type", "label", "source_table", "properties_json"]
EDGE_COLUMNS = [
    "edge_id",
    "source_node_id",
    "target_node_id",
    "edge_type",
    "source_table",
    "properties_json",
]


def _node_row(
    node_id: str,
    node_type: str,
    label: str,
    source_table: str,
    properties: dict,
) -> dict:
    """One node record: properties stored as a JSON object string."""
    return {
        "node_id": node_id,
        "node_type": node_type,
        "label": label,
        "source_table": source_table,
        "properties_json": json.dumps(properties, ensure_ascii=False),
    }


def _edge_row(
    edge_id: str,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    source_table: str,
    properties: dict,
) -> dict:
    """One edge record: optional metadata on the relationship as JSON."""
    return {
        "edge_id": edge_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "edge_type": edge_type,
        "source_table": source_table,
        "properties_json": json.dumps(properties, ensure_ascii=False),
    }


def _json_friendly_value(value):
    """Convert a pandas cell to something json.dumps accepts (handle NaN / numpy types)."""
    if value is None:
        return None
    # numpy / pandas scalar → Python native (json.dumps does not accept np.int64, etc.)
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return _json_friendly_value(value.item())
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and pd.isna(value):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _row_to_properties_dict(row: pd.Series) -> dict:
    """All columns -> dict with JSON-safe values (keys = CSV header names)."""
    return {str(k): _json_friendly_value(row[k]) for k in row.index}


def _empty_nodes() -> pd.DataFrame:
    return pd.DataFrame(columns=NODE_COLUMNS)


def _empty_edges() -> pd.DataFrame:
    return pd.DataFrame(columns=EDGE_COLUMNS)


def _seed_csv_path(name: str) -> Path:
    return SEED_DIR / name


def read_seed_csv(
    filename: str,
    *,
    required_columns: list[str] | None = None,
    logical_name: str | None = None,
) -> pd.DataFrame | None:
    """
    Load a CSV from ``poc_v1_seed``. Returns None if the file is missing.
    Prints a clear warning on missing file, empty file, or missing required columns.
    """
    path = _seed_csv_path(filename)
    label = logical_name or filename
    if not path.is_file():
        print(f"Warning: seed file missing ({label}): {path}")
        return None
    df = pd.read_csv(path)
    if df.empty:
        print(f"Warning: seed file is empty ({label}): {path}")
        return None
    if required_columns:
        missing = [c for c in required_columns if c not in df.columns]
        if missing:
            print(
                f"Warning: seed file {path} missing columns {missing!r} — skipping {label}."
            )
            return None
    return df


# ---------------------------------------------------------------------------
# Stable node ids (prefix + business key)
# ---------------------------------------------------------------------------


def person_node_id(res_person_id) -> str:
    if res_person_id is None or (isinstance(res_person_id, float) and pd.isna(res_person_id)):
        raise ValueError("RES_PERSON_ID is missing")
    if isinstance(res_person_id, float) and res_person_id.is_integer():
        res_person_id = int(res_person_id)
    return f"person_{res_person_id}"


def business_node_id(res_business_id) -> str:
    if res_business_id is None or (isinstance(res_business_id, float) and pd.isna(res_business_id)):
        raise ValueError("RES_BUSINESS_ID is missing")
    if isinstance(res_business_id, float) and res_business_id.is_integer():
        res_business_id = int(res_business_id)
    return f"business_{res_business_id}"


def policy_node_id(policy_number: str) -> str:
    if policy_number is None or (isinstance(policy_number, float) and pd.isna(policy_number)):
        raise ValueError("POLICY_NUMBER is missing")
    p = str(policy_number).strip()
    if not p:
        raise ValueError("POLICY_NUMBER is empty")
    return f"policy_{p}"


def claim_node_id(claim_id) -> str:
    if claim_id is None or (isinstance(claim_id, float) and pd.isna(claim_id)):
        raise ValueError("CLAIM_ID is missing")
    return f"claim_{claim_id}"


def address_node_id(res_address_id) -> str:
    if res_address_id is None or (isinstance(res_address_id, float) and pd.isna(res_address_id)):
        raise ValueError("RES_ADDRESS_ID is missing")
    if isinstance(res_address_id, float) and res_address_id.is_integer():
        res_address_id = int(res_address_id)
    return f"address_{res_address_id}"


def bank_account_node_id(res_bank_account_id) -> str:
    if res_bank_account_id is None or (isinstance(res_bank_account_id, float) and pd.isna(res_bank_account_id)):
        raise ValueError("RES_BANK_ACCOUNT_ID is missing")
    if isinstance(res_bank_account_id, float) and res_bank_account_id.is_integer():
        res_bank_account_id = int(res_bank_account_id)
    return f"bank_{res_bank_account_id}"


# ---------------------------------------------------------------------------
# Node builders (one seed file each)
# ---------------------------------------------------------------------------


def build_person_nodes() -> pd.DataFrame:
    df = read_seed_csv(SEED_PERSON, required_columns=["RES_PERSON_ID"], logical_name="Person")
    if df is None:
        return _empty_nodes()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            node_id = person_node_id(row["RES_PERSON_ID"])
        except (ValueError, TypeError):
            print(f"Warning: skipping Person row with invalid RES_PERSON_ID: {row.get('RES_PERSON_ID', row)!r}")
            continue
        props = _row_to_properties_dict(row)
        label = "Person"
        fn, ln = props.get("FIRST_NAME"), props.get("LAST_NAME")
        if fn or ln:
            label = f"{fn or ''} {ln or ''}".strip() or "Person"
        out_rows.append(_node_row(node_id, "Person", label, SOURCE_TABLE_PERSON, props))
    if not out_rows:
        print(f"Warning: no valid Person rows after load — {SEED_DIR / SEED_PERSON}")
        return _empty_nodes()
    return pd.DataFrame(out_rows)


def build_business_nodes() -> pd.DataFrame:
    df = read_seed_csv(
        SEED_BUSINESS, required_columns=["RES_BUSINESS_ID"], logical_name="Business"
    )
    if df is None:
        return _empty_nodes()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            node_id = business_node_id(row["RES_BUSINESS_ID"])
        except (ValueError, TypeError):
            print(
                f"Warning: skipping Business row with invalid RES_BUSINESS_ID: {row.get('RES_BUSINESS_ID', row)!r}"
            )
            continue
        props = _row_to_properties_dict(row)
        name = props.get("BUSINESS_NAME") or "Business"
        out_rows.append(_node_row(node_id, "Business", str(name), SOURCE_TABLE_BUSINESS, props))
    return pd.DataFrame(out_rows)


def build_policy_nodes() -> pd.DataFrame:
    df = read_seed_csv(SEED_POLICY, required_columns=["POLICY_NUMBER"], logical_name="Policy")
    if df is None:
        return _empty_nodes()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            node_id = policy_node_id(row["POLICY_NUMBER"])
        except (ValueError, TypeError):
            print(
                f"Warning: skipping Policy row with invalid POLICY_NUMBER: {row.get('POLICY_NUMBER', row)!r}"
            )
            continue
        props = _row_to_properties_dict(row)
        pn = props.get("POLICY_NUMBER") or node_id
        out_rows.append(_node_row(node_id, "Policy", str(pn), SOURCE_TABLE_POLICY, props))
    return pd.DataFrame(out_rows)


def build_claim_nodes() -> pd.DataFrame:
    df = read_seed_csv(SEED_CLAIM, required_columns=["CLAIM_ID"], logical_name="Claim")
    if df is None:
        return _empty_nodes()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            node_id = claim_node_id(row["CLAIM_ID"])
        except (ValueError, TypeError):
            print(f"Warning: skipping Claim row with invalid CLAIM_ID: {row.get('CLAIM_ID', row)!r}")
            continue
        props = _row_to_properties_dict(row)
        cn = props.get("CLAIM_NUMBER") or node_id
        out_rows.append(_node_row(node_id, "Claim", str(cn), SOURCE_TABLE_CLAIM, props))
    return pd.DataFrame(out_rows)


def build_address_nodes() -> pd.DataFrame:
    df = read_seed_csv(
        SEED_ADDRESS, required_columns=["RES_ADDRESS_ID"], logical_name="Address"
    )
    if df is None:
        return _empty_nodes()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            node_id = address_node_id(row["RES_ADDRESS_ID"])
        except (ValueError, TypeError):
            print(
                f"Warning: skipping Address row with invalid RES_ADDRESS_ID: {row.get('RES_ADDRESS_ID', row)!r}"
            )
            continue
        props = _row_to_properties_dict(row)
        city = props.get("CITY") or ""
        st = props.get("STATE") or ""
        label = ", ".join(x for x in (city, st) if x) or "Address"
        out_rows.append(_node_row(node_id, "Address", label, SOURCE_TABLE_ADDRESS, props))
    return pd.DataFrame(out_rows)


def build_bank_account_nodes() -> pd.DataFrame:
    df = read_seed_csv(
        SEED_BANK_ACCOUNT,
        required_columns=["RES_BANK_ACCOUNT_ID"],
        logical_name="BankAccount",
    )
    if df is None:
        return _empty_nodes()
    out_rows: list[dict] = []
    for _, row in df.iterrows():
        try:
            node_id = bank_account_node_id(row["RES_BANK_ACCOUNT_ID"])
        except (ValueError, TypeError):
            print(
                "Warning: skipping BankAccount row with invalid RES_BANK_ACCOUNT_ID: "
                f"{row.get('RES_BANK_ACCOUNT_ID', row)!r}"
            )
            continue
        props = _row_to_properties_dict(row)
        acct = props.get("ACCOUNT_NUMBER")
        label = f"Bank {props.get('RES_BANK_ACCOUNT_ID')} ({acct})" if acct else f"Bank {props.get('RES_BANK_ACCOUNT_ID')}"
        out_rows.append(
            _node_row(node_id, "BankAccount", label, SOURCE_TABLE_BANK, props)
        )
    return pd.DataFrame(out_rows)


def build_all_nodes() -> pd.DataFrame:
    """Concatenate every node partition into one table."""
    parts = [
        build_person_nodes(),
        build_business_nodes(),
        build_policy_nodes(),
        build_claim_nodes(),
        build_address_nodes(),
        build_bank_account_nodes(),
    ]
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------------------
# Edge builders (crosswalks + synthesized claim → policy)
# ---------------------------------------------------------------------------


def build_edges_person_address(
    existing_node_ids: set[str], edge_id_start: int
) -> tuple[pd.DataFrame, int]:
    df = read_seed_csv(
        SEED_PERSON_ADDRESS,
        required_columns=["RES_PERSON_ID", "RES_ADDRESS_ID"],
        logical_name="Person–Address crosswalk",
    )
    if df is None:
        return _empty_edges(), edge_id_start
    rows: list[dict] = []
    eid = edge_id_start
    for _, row in df.iterrows():
        try:
            src = person_node_id(row["RES_PERSON_ID"])
            tgt = address_node_id(row["RES_ADDRESS_ID"])
        except (ValueError, TypeError):
            continue
        if src not in existing_node_ids or tgt not in existing_node_ids:
            continue
        ename = row["EDGE_NAME"] if "EDGE_NAME" in df.columns and pd.notna(row.get("EDGE_NAME")) else "LOCATED_IN"
        edge_type = str(ename).strip() or "LOCATED_IN"
        props = _row_to_properties_dict(row)
        rows.append(
            _edge_row(f"e_{eid:06d}", src, tgt, edge_type, "T_RESOLVED_PERSON_ADDRESS_CROSSWALK", props)
        )
        eid += 1
    return pd.DataFrame(rows), eid


def build_edges_business_address(
    existing_node_ids: set[str], edge_id_start: int
) -> tuple[pd.DataFrame, int]:
    df = read_seed_csv(
        SEED_BUSINESS_ADDRESS,
        required_columns=["RES_BUSINESS_ID", "RES_ADDRESS_ID"],
        logical_name="Business–Address crosswalk",
    )
    if df is None:
        return _empty_edges(), edge_id_start
    rows: list[dict] = []
    eid = edge_id_start
    for _, row in df.iterrows():
        try:
            src = business_node_id(row["RES_BUSINESS_ID"])
            tgt = address_node_id(row["RES_ADDRESS_ID"])
        except (ValueError, TypeError):
            continue
        if src not in existing_node_ids or tgt not in existing_node_ids:
            continue
        props = _row_to_properties_dict(row)
        rows.append(
            _edge_row(
                f"e_{eid:06d}",
                src,
                tgt,
                "LOCATED_IN",
                "T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK",
                props,
            )
        )
        eid += 1
    return pd.DataFrame(rows), eid


def build_edges_person_person(
    existing_node_ids: set[str], edge_id_start: int
) -> tuple[pd.DataFrame, int]:
    df = read_seed_csv(
        SEED_PERSON_PERSON,
        required_columns=["RES_PERSON_ID_SRC", "RES_PERSON_ID_TGT"],
        logical_name="Person–Person crosswalk",
    )
    if df is None:
        return _empty_edges(), edge_id_start
    rows: list[dict] = []
    eid = edge_id_start
    for _, row in df.iterrows():
        try:
            src = person_node_id(row["RES_PERSON_ID_SRC"])
            tgt = person_node_id(row["RES_PERSON_ID_TGT"])
        except (ValueError, TypeError):
            continue
        if src not in existing_node_ids or tgt not in existing_node_ids:
            continue
        ename = row["EDGE_NAME"] if "EDGE_NAME" in df.columns and pd.notna(row.get("EDGE_NAME")) else "RELATED_TO"
        edge_type = str(ename).strip() or "RELATED_TO"
        props = _row_to_properties_dict(row)
        rows.append(
            _edge_row(f"e_{eid:06d}", src, tgt, edge_type, "T_RESOLVED_PERSON_PERSON_CROSSWALK", props)
        )
        eid += 1
    return pd.DataFrame(rows), eid


def build_edges_person_policy(
    existing_node_ids: set[str], edge_id_start: int
) -> tuple[pd.DataFrame, int]:
    df = read_seed_csv(
        SEED_PERSON_POLICY,
        required_columns=["RES_PERSON_ID", "POLICY_NUMBER"],
        logical_name="Person–Policy crosswalk",
    )
    if df is None:
        return _empty_edges(), edge_id_start
    rows: list[dict] = []
    eid = edge_id_start
    for _, row in df.iterrows():
        try:
            src = person_node_id(row["RES_PERSON_ID"])
            tgt = policy_node_id(row["POLICY_NUMBER"])
        except (ValueError, TypeError):
            continue
        if src not in existing_node_ids or tgt not in existing_node_ids:
            continue
        ename = row["EDGE_NAME"] if "EDGE_NAME" in df.columns and pd.notna(row.get("EDGE_NAME")) else "IS_COVERED_BY"
        edge_type = str(ename).strip() or "IS_COVERED_BY"
        props = _row_to_properties_dict(row)
        rows.append(
            _edge_row(
                f"e_{eid:06d}", src, tgt, edge_type, "T_RESOLVED_PERSON_POLICY_CROSSWALK", props
            )
        )
        eid += 1
    return pd.DataFrame(rows), eid


def build_edges_person_bank_account(
    existing_node_ids: set[str], edge_id_start: int
) -> tuple[pd.DataFrame, int]:
    df = read_seed_csv(
        SEED_PERSON_BANK,
        required_columns=["RES_PERSON_ID", "RES_BANK_ACCOUNT_ID"],
        logical_name="Person–BankAccount crosswalk",
    )
    if df is None:
        return _empty_edges(), edge_id_start
    rows: list[dict] = []
    eid = edge_id_start
    for _, row in df.iterrows():
        try:
            src = person_node_id(row["RES_PERSON_ID"])
            tgt = bank_account_node_id(row["RES_BANK_ACCOUNT_ID"])
        except (ValueError, TypeError):
            continue
        if src not in existing_node_ids or tgt not in existing_node_ids:
            continue
        ename = row["EDGE_NAME"] if "EDGE_NAME" in df.columns and pd.notna(row.get("EDGE_NAME")) else "HOLD_BY"
        edge_type = str(ename).strip() or "HOLD_BY"
        props = _row_to_properties_dict(row)
        rows.append(
            _edge_row(
                f"e_{eid:06d}",
                src,
                tgt,
                edge_type,
                "T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK",
                props,
            )
        )
        eid += 1
    return pd.DataFrame(rows), eid


def build_edges_claim_to_policy(
    existing_node_ids: set[str], edge_id_start: int
) -> tuple[pd.DataFrame, int]:
    """
    Synthesize Claim → Policy edges from claim rows (POLICY_NUMBER), per graph mapping doc.
    """
    df = read_seed_csv(
        SEED_CLAIM, required_columns=["CLAIM_ID", "POLICY_NUMBER"], logical_name="Claim→Policy (from claims)"
    )
    if df is None:
        return _empty_edges(), edge_id_start
    rows: list[dict] = []
    eid = edge_id_start
    for _, row in df.iterrows():
        pol = row.get("POLICY_NUMBER")
        if pol is None or (isinstance(pol, float) and pd.isna(pol)):
            continue
        pol = str(pol).strip()
        if not pol:
            continue
        try:
            src = claim_node_id(row["CLAIM_ID"])
            tgt = policy_node_id(pol)
        except (ValueError, TypeError):
            continue
        if src not in existing_node_ids or tgt not in existing_node_ids:
            continue
        props = {"POLICY_NUMBER": pol, "note": "synthesized from T_NORM_CLAIM.POLICY_NUMBER"}
        rows.append(
            _edge_row(
                f"e_{eid:06d}",
                src,
                tgt,
                "IS_CLAIM_AGAINST_POLICY",
                SOURCE_TABLE_CLAIM,
                props,
            )
        )
        eid += 1
    return pd.DataFrame(rows), eid


def build_core_edges(nodes_df: pd.DataFrame) -> pd.DataFrame:
    """
    All relationship rows from seed crosswalks plus synthesized claim→policy edges.
    Drops edges whose endpoints are not present in ``nodes_df``.
    """
    existing = set(nodes_df["node_id"].astype(str)) if not nodes_df.empty else set()
    eid = 0
    parts: list[pd.DataFrame] = []

    for builder in (
        build_edges_person_address,
        build_edges_business_address,
        build_edges_person_person,
        build_edges_person_policy,
        build_edges_person_bank_account,
        build_edges_claim_to_policy,
    ):
        part, eid = builder(existing, eid)
        if not part.empty:
            parts.append(part)

    if not parts:
        return _empty_edges()
    return pd.concat(parts, ignore_index=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build graph CSV files from seed CSVs.")
    parser.add_argument(
        "--seed-dir",
        default=str(DEFAULT_SEED_DIR),
        help="Directory containing seed CSV files (defaults to poc_v1_seed).",
    )
    return parser.parse_args()


def main() -> None:
    global SEED_DIR
    args = _parse_args()
    SEED_DIR = Path(args.seed_dir).resolve()
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if not SEED_DIR.is_dir():
        print(f"Warning: seed directory missing — no loads will succeed: {SEED_DIR}")

    nodes_df = build_all_nodes()
    edges_df = build_core_edges(nodes_df)

    nodes_df.to_csv(NODES_CSV, index=False, encoding="utf-8")
    edges_df.to_csv(EDGES_CSV, index=False, encoding="utf-8")

    print(f"Wrote {len(nodes_df)} nodes -> {NODES_CSV}")
    print(f"Wrote {len(edges_df)} edges -> {EDGES_CSV}")


if __name__ == "__main__":
    main()

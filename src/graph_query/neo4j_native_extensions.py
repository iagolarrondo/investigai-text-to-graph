"""
Neo4j native paths for **extension** tools (``src/graph_query/generated/*.py``).

When ``NEO4J_READ_MODE=native``, each extension's ``run()`` dispatches here instead of
``get_graph()`` so logic runs on Aura (``:Entity`` / ``:GRAPH_EDGE``) using the same
conventions as ``neo4j_native_heavy`` (e.g. ``IS_CLAIM_AGAINST_POLICY``, ``HOLD_BY``).

Authoring adds ``native_ext_generated/<name>.py`` with ``run_native``; those modules are
loaded dynamically alongside the bundled implementations below.
"""

from __future__ import annotations

import importlib
import json
import sys
from collections import defaultdict
from typing import Any, Callable

_dynamic_native_cache: dict[str, Callable[[dict[str, Any]], str] | None] = {}

from src.graph_query.neo4j_native_heavy import _fetch_nodes_bulk
from src.graph_query.neo4j_native_reads import parse_properties_json
from src.graph_store.neo4j_read_session import run_read_query as rq


def _extract_phones(node_data: dict[str, Any]) -> set[str]:
    phones: set[str] = set()
    phone_keys = [k for k in node_data.keys() if "phone" in k.lower()]
    for k in phone_keys:
        val = node_data.get(k)
        if val and isinstance(val, str):
            digits = "".join(c for c in val if c.isdigit())
            if len(digits) >= 7:
                phones.add(digits)
    pj = node_data.get("properties_json")
    if isinstance(pj, str):
        props = parse_properties_json(pj)
        for k, v in props.items():
            if "phone" in k.lower() and isinstance(v, str):
                digits = "".join(c for c in v if c.isdigit())
                if len(digits) >= 7:
                    phones.add(digits)
    return phones


def native_claims_agent_insured_shared_bank(tool_input: dict[str, Any]) -> str:
    limit = min(max(int(tool_input.get("limit", 200)), 1), 1000)
    bank_rows = rq(
        """
        MATCH (p:Entity)-[r:GRAPH_EDGE]->(b:Entity)
        WHERE p.node_type = 'Person' AND b.node_type = 'BankAccount' AND r.edge_type = 'HOLD_BY'
        RETURN p.node_id AS pid, b.node_id AS bid
        """
    )
    person_to_banks: dict[str, set[str]] = defaultdict(set)
    for r in bank_rows:
        person_to_banks[str(r["pid"])].add(str(r["bid"]))
    claim_rows = rq("MATCH (c:Entity {node_type: 'Claim'}) RETURN c.node_id AS cid")
    results: list[dict[str, Any]] = []
    labels: dict[str, str] = {}

    def _lab(nid: str) -> str:
        if nid not in labels:
            lr = rq("MATCH (n:Entity {node_id: $id}) RETURN n.label AS l LIMIT 1", {"id": nid})
            labels[nid] = str(lr[0]["l"]) if lr else nid
        return labels[nid]

    for cr in claim_rows:
        if len(results) >= limit:
            break
        cid = str(cr["cid"])
        pol_rows = rq(
            """
            MATCH (c:Entity {node_id: $cid})-[r:GRAPH_EDGE]->(pol:Entity)
            WHERE r.edge_type = 'IS_CLAIM_AGAINST_POLICY' AND pol.node_type = 'Policy'
            RETURN pol.node_id AS pid LIMIT 1
            """,
            {"cid": cid},
        )
        if not pol_rows:
            continue
        pid = str(pol_rows[0]["pid"])
        party = rq(
            """
            MATCH (per:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
            WHERE per.node_type = 'Person' AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
            RETURN per.node_id AS per_id, r.edge_type AS et
            """,
            {"pid": pid},
        )
        agents = {str(r["per_id"]) for r in party if str(r["et"]) == "SOLD_POLICY"}
        insureds = {str(r["per_id"]) for r in party if str(r["et"]) == "IS_COVERED_BY"}
        if not agents or not insureds:
            continue
        for agent_id in agents:
            agent_banks = person_to_banks.get(agent_id, set())
            if not agent_banks:
                continue
            for insured_id in insureds:
                if insured_id == agent_id:
                    continue
                for bank_id in agent_banks & person_to_banks.get(insured_id, set()):
                    results.append(
                        {
                            "claim_id": cid,
                            "policy_id": pid,
                            "agent_id": agent_id,
                            "agent_name": _lab(agent_id),
                            "insured_id": insured_id,
                            "insured_name": _lab(insured_id),
                            "bank_account_id": bank_id,
                        }
                    )
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

    return json.dumps(
        {"match_count": len(results), "truncated": len(results) >= limit, "matches": results},
        default=str,
    )


def native_claims_agent_insured_shared_phone(tool_input: dict[str, Any]) -> str:
    _ = tool_input
    claim_rows = rq("MATCH (c:Entity {node_type: 'Claim'}) RETURN c.node_id AS cid")
    matches: list[dict[str, Any]] = []
    need_ids: set[str] = set()

    pairs: list[tuple[str, str, str, str]] = []
    for cr in claim_rows:
        cid = str(cr["cid"])
        pol_rows = rq(
            """
            MATCH (c:Entity {node_id: $cid})-[r:GRAPH_EDGE]->(pol:Entity)
            WHERE r.edge_type = 'IS_CLAIM_AGAINST_POLICY' AND pol.node_type = 'Policy'
            RETURN pol.node_id AS pid
            """,
            {"cid": cid},
        )
        for pr in pol_rows:
            pid = str(pr["pid"])
            party = rq(
                """
                MATCH (per:Entity)-[r:GRAPH_EDGE]->(pol:Entity {node_id: $pid})
                WHERE per.node_type = 'Person' AND r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
                RETURN per.node_id AS per_id, r.edge_type AS et
                """,
                {"pid": pid},
            )
            agents = {str(r["per_id"]) for r in party if str(r["et"]) == "SOLD_POLICY"}
            insureds = {str(r["per_id"]) for r in party if str(r["et"]) == "IS_COVERED_BY"}
            for a in agents:
                for i in insureds:
                    if a != i:
                        pairs.append((cid, pid, a, i))
                        need_ids.update({a, i})

    attrs = _fetch_nodes_bulk(list(need_ids)) if need_ids else {}
    for cid, pid, agent_id, insured_id in pairs:
        ad = attrs.get(agent_id, {})
        idata = attrs.get(insured_id, {})
        agent_node = {**ad, "properties_json": ad.get("properties_json")}
        insured_node = {**idata, "properties_json": idata.get("properties_json")}
        ap = _extract_phones(agent_node)
        ip = _extract_phones(insured_node)
        for phone in ap & ip:
            matches.append(
                {
                    "claim_id": cid,
                    "policy_id": pid,
                    "agent_id": agent_id,
                    "insured_id": insured_id,
                    "shared_phone": phone,
                }
            )

    if not matches:
        return json.dumps(
            {
                "result": "no_matches",
                "message": "No insureds share a phone number with the writing agent of any claim policy.",
                "claims_checked": len(claim_rows),
            }
        )
    return json.dumps(
        {"match_count": len(matches), "claims_checked": len(claim_rows), "matches": matches},
        default=str,
    )


def native_policies_with_multiple_covered_persons(tool_input: dict[str, Any]) -> str:
    min_persons = max(1, int(tool_input.get("min_persons", 2)))
    rows = rq(
        """
        MATCH (person:Entity {node_type: 'Person'})-[r:GRAPH_EDGE]->(pol:Entity {node_type: 'Policy'})
        WHERE r.edge_type IN ['IS_COVERED_BY', 'SOLD_POLICY']
        WITH pol, collect(DISTINCT person.node_id) AS person_ids
        WHERE size(person_ids) >= $minp
        RETURN pol.node_id AS policy_id,
               pol.label AS policy_label,
               size(person_ids) AS covered_person_count,
               person_ids AS covered_person_ids
        ORDER BY covered_person_count DESC
        """,
        {"minp": min_persons},
    )
    results = [
        {
            "policy_id": str(r["policy_id"]),
            "policy_label": r.get("policy_label"),
            "covered_person_count": int(r["covered_person_count"]),
            "covered_person_ids": sorted(str(x) for x in (r["covered_person_ids"] or [])),
        }
        for r in rows
    ]
    if not results:
        return json.dumps(
            {
                "policies_with_multiple_covered_persons": [],
                "count": 0,
                "message": f"No policies found with {min_persons} or more covered persons.",
            }
        )
    return json.dumps(
        {
            "policies_with_multiple_covered_persons": results,
            "count": len(results),
            "min_persons_filter": min_persons,
        },
        default=str,
    )


def native_find_people_by_city_state(tool_input: dict[str, Any]) -> str:
    city = (tool_input.get("city") or "").strip().upper()
    state = (tool_input.get("state") or "").strip().upper()
    if not city:
        return json.dumps({"error": "city is required"})
    rows = rq(
        """
        MATCH (n:Entity)
        WHERE toUpper(toString(n.label)) CONTAINS $city
           OR toUpper(toString(n.properties_json)) CONTAINS $city
        WITH n
        WHERE $state = '' OR toUpper(toString(n.label)) CONTAINS $state
           OR toUpper(toString(n.properties_json)) CONTAINS $state
        RETURN n.node_id AS nid, n.node_type AS nt, n.label AS lab, n.properties_json AS pj
        """,
        {"city": city, "state": state or ""},
    )
    person_map: dict[str, dict[str, Any]] = {}

    def _add_person(pid: str, pdata: dict[str, Any], ctx: str) -> None:
        if pid not in person_map:
            person_map[pid] = {
                "person_id": pid,
                "label": pdata.get("label", pid),
                "address_context": [],
            }
        person_map[pid]["address_context"].append(ctx)

    nids_for_neighbors: list[str] = []
    for r in rows:
        nid = str(r["nid"])
        nt = str(r.get("nt") or "").lower()
        lab = r.get("lab") or nid
        if nt == "person":
            _add_person(nid, {"label": lab}, f"self:{lab}")
        else:
            nids_for_neighbors.append(nid)

    if nids_for_neighbors:
        nr = rq(
            """
            MATCH (n:Entity)-[:GRAPH_EDGE]-(per:Entity {node_type: 'Person'})
            WHERE n.node_id IN $nids AND per.node_id <> n.node_id
            RETURN DISTINCT n.node_id AS anchor, per.node_id AS pid, per.label AS plab
            """,
            {"nids": list(dict.fromkeys(nids_for_neighbors))},
        )
        for r in nr:
            anchor = str(r["anchor"])
            pdata = {"label": r.get("plab")}
            alab = next((x.get("lab") for x in rows if str(x["nid"]) == anchor), anchor)
            _add_person(str(r["pid"]), pdata, str(alab))

    all_person = rq(
        """
        MATCH (per:Entity {node_type: 'Person'})
        WHERE toUpper(toString(per.properties_json)) CONTAINS $city
          AND ($state = '' OR toUpper(toString(per.properties_json)) CONTAINS $state)
        RETURN per.node_id AS pid, per.label AS plab
        """,
        {"city": city, "state": state or ""},
    )
    for r in all_person:
        pid = str(r["pid"])
        if pid not in person_map:
            person_map[pid] = {
                "person_id": pid,
                "label": r.get("plab", pid),
                "address_context": ["direct_property_match"],
            }

    if not person_map:
        qd = city + (f", {state}" if state else "")
        return json.dumps(
            {
                "city": city,
                "state": state,
                "people_found": 0,
                "people": [],
                "note": f"No Person nodes found associated with {qd}",
            }
        )
    out = list(person_map.values())
    for x in out:
        x["address_context"] = list(dict.fromkeys(x["address_context"]))
    return json.dumps(
        {"city": city, "state": state, "people_found": len(out), "people": out},
        default=str,
    )


def _classify_neighbor(nt: str, label: str) -> tuple[bool, bool]:
    nt_norm = nt.lower().replace(" ", "").replace("_", "")
    lbl = label.lower().replace(" ", "").replace("_", "")
    combined = nt_norm + "|" + lbl
    customer_types = {"person", "customer", "insured", "policyholder"}
    provider_types = {"healthcareprovider", "provider", "medicalprovider"}
    is_customer = any(ct in combined for ct in customer_types)
    is_provider = any(pt in combined for pt in provider_types)
    return is_customer, is_provider


def native_find_bank_accounts_shared_customer_and_provider(tool_input: dict[str, Any]) -> str:
    min_accounts = max(1, int(tool_input.get("min_accounts_per_group", 2)))
    rows = rq(
        """
        MATCH (ba:Entity {node_type: 'BankAccount'})
        MATCH (n:Entity)-[r:GRAPH_EDGE]-(ba)
        WHERE n.node_id <> ba.node_id
        RETURN ba.node_id AS bid, n.node_id AS nid, n.node_type AS nt, n.label AS lab
        """
    )
    bank_account_nodes = list({str(r["bid"]) for r in rows})
    if not bank_account_nodes:
        return json.dumps({"result": "no_bank_account_nodes_found", "groups": []})

    ba_customers: dict[str, set[str]] = defaultdict(set)
    ba_providers: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        bid = str(r["bid"])
        nid = str(r["nid"])
        ic, ip = _classify_neighbor(str(r.get("nt") or ""), str(r.get("lab") or ""))
        if ic:
            ba_customers[bid].add(nid)
        if ip:
            ba_providers[bid].add(nid)

    pair_to_accounts: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ba in bank_account_nodes:
        for cust in ba_customers.get(ba, ()):
            for prov in ba_providers.get(ba, ()):
                pair_to_accounts[(cust, prov)].append(ba)

    triples: list[tuple[str, str, list[str]]] = []
    need = set()
    for (cust_id, prov_id), accounts in pair_to_accounts.items():
        uq = list(dict.fromkeys(accounts))
        if len(uq) >= min_accounts:
            need.update({cust_id, prov_id})
            triples.append((cust_id, prov_id, uq))

    attrs = _fetch_nodes_bulk(list(need)) if need else {}
    out_rows: list[dict[str, Any]] = []
    for cust_id, prov_id, uq in triples:
        cd = attrs.get(cust_id, {})
        pd = attrs.get(prov_id, {})
        out_rows.append(
            {
                "customer_id": cust_id,
                "customer_label": cd.get("label", cust_id),
                "customer_type": cd.get("node_type", ""),
                "provider_id": prov_id,
                "provider_label": pd.get("label", prov_id),
                "provider_type": pd.get("node_type", ""),
                "bank_account_ids": uq,
                "account_count": len(uq),
            }
        )
    out_rows.sort(key=lambda x: -x["account_count"])

    if not out_rows:
        has_any_link = sum(1 for ba in bank_account_nodes if ba_customers.get(ba) or ba_providers.get(ba))
        has_both = sum(1 for ba in bank_account_nodes if ba_customers.get(ba) and ba_providers.get(ba))
        return json.dumps(
            {
                "result": "no_groups_found",
                "total_bank_accounts_scanned": len(bank_account_nodes),
                "accounts_with_any_link": has_any_link,
                "accounts_with_both_customer_and_provider": has_both,
                "note": (
                    "No bank accounts share both a common customer and a common healthcare provider "
                    "at the requested minimum group size."
                ),
                "groups": [],
            }
        )

    return json.dumps(
        {
            "result": "groups_found",
            "total_groups": len(out_rows),
            "total_bank_accounts_scanned": len(bank_account_nodes),
            "min_accounts_per_group": min_accounts,
            "groups": out_rows,
        },
        default=str,
    )


_NATIVE_EXT: dict[str, Callable[[dict[str, Any]], str]] = {
    "claims_agent_insured_shared_bank": native_claims_agent_insured_shared_bank,
    "claims_agent_insured_shared_phone": native_claims_agent_insured_shared_phone,
    "policies_with_multiple_covered_persons": native_policies_with_multiple_covered_persons,
    "find_people_by_city_state": native_find_people_by_city_state,
    "find_bank_accounts_shared_customer_and_provider": native_find_bank_accounts_shared_customer_and_provider,
}


def clear_dynamic_native_cache() -> None:
    """Called after a new ``native_ext_generated`` module is written."""
    _dynamic_native_cache.clear()


def _load_dynamic_native_fn(module_name: str) -> Callable[[dict[str, Any]], str] | None:
    if module_name in _dynamic_native_cache:
        return _dynamic_native_cache[module_name]
    mod_path = f"src.graph_query.native_ext_generated.{module_name}"
    try:
        if mod_path in sys.modules:
            del sys.modules[mod_path]
        m = importlib.import_module(mod_path)
        fn = getattr(m, "run_native", None)
        if not callable(fn):
            _dynamic_native_cache[module_name] = None
            return None
        _dynamic_native_cache[module_name] = fn  # type: ignore[assignment]
        return fn  # type: ignore[return-value]
    except Exception:
        _dynamic_native_cache[module_name] = None
        return None


def run_extension_native(module_name: str, tool_input: dict[str, Any]) -> str:
    fn = _NATIVE_EXT.get(module_name)
    if fn is None:
        dyn = _load_dynamic_native_fn(module_name)
        if dyn is not None:
            fn = dyn
    if fn is None:
        return json.dumps({"error": f"No Neo4j native implementation for extension `{module_name}`."})
    try:
        return fn(tool_input)
    except Exception as exc:
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
"""Quick Neo4j connectivity + schema sanity check (run from project root).

Usage::

    PYTHONPATH=. python -m src.graph_store.neo4j_diagnose

Requires ``NEO4J_URI`` and ``NEO4J_PASSWORD`` in ``.env`` (see ``env.template``).
"""

from __future__ import annotations

import os
import sys


def _is_database_not_found(exc: BaseException) -> bool:
    code = str(getattr(exc, "code", "") or "")
    if "DatabaseNotFound" in code:
        return True
    m = str(exc).lower()
    return ("database" in m or "graph reference" in m) and ("not found" in m or "does not exist" in m)


def _try_aura_routing_entity_read(nc) -> tuple[int, str] | None:
    """
    If default (often direct Bolt on Aura) fails with a missing database, try once with a
    routing ``neo4j+s://`` driver — some Aura builds resolve the graph only via routing.
    """
    raw = nc.neo4j_uri()
    if not raw:
        return None
    if nc._neo4j_driver_mode() == "routing":
        return None
    from urllib.parse import urlparse

    host = (urlparse(raw.strip()).hostname or "").lower()
    if not host.endswith(".databases.neo4j.io"):
        return None
    default_uri = nc.effective_neo4j_uri(raw)
    routing_uri = nc.effective_neo4j_uri(raw, driver_mode="routing")
    if not routing_uri or routing_uri == default_uri:
        return None
    driver = None
    try:
        driver = nc.open_driver(driver_mode="routing")
        driver.verify_connectivity()
        kw = nc.neo4j_session_kwargs()
        with driver.session(**kw) as session:
            one = session.run("MATCH (n:Entity) RETURN count(n) AS entity_count LIMIT 1").single()
            n = int(one["entity_count"]) if one is not None else 0
        return (n, routing_uri)
    except Exception as exc2:
        print(
            f"\n  One-off read with **routing** driver ({routing_uri!r}) also FAILED: "
            f"{type(exc2).__name__}: {exc2}"
        )
        return None
    finally:
        if driver is not None:
            driver.close()


def _print_database_catalog_hint(nc) -> None:
    """After a read failure, list ``SHOW DATABASES`` (no ``database=``) and suggest a safe ``NEO4J_DATABASE``."""
    try:
        driver = nc.open_driver()
    except Exception as exc:
        print(f"  (Could not open driver to list databases: {exc})")
        return

    rows: list[dict[str, object]] = []
    try:
        with driver.session() as session:
            result = session.run("SHOW DATABASES")
            for row in result:
                rows.append(dict(row))
    except Exception as exc:
        print(f"  SHOW DATABASES (no database= in session) failed: {exc}")
        return
    finally:
        driver.close()

    if not rows:
        print("  SHOW DATABASES returned no rows.")
        return

    reserved = frozenset({"system", "neo4j-fabric"})
    # name -> True if any row marks this DB as home
    by_name: dict[str, dict[str, object]] = {}
    for d in rows:
        raw_name = d.get("name")
        if raw_name is None:
            continue
        name = str(raw_name).strip()
        if not name:
            continue
        st = str(d.get("currentStatus") or "").strip().lower()
        if st and st != "online":
            continue
        prev = by_name.get(name)
        home = d.get("home")
        is_home = bool(home) if home is not None else False
        if prev is None:
            by_name[name] = {"home": is_home, "row": d}
        else:
            prev["home"] = bool(prev["home"]) or is_home

    names_sorted = sorted(by_name.keys())
    print(f"  Catalog databases (``SHOW DATABASES``, de-duplicated, online only): {names_sorted}")

    candidates = [n for n in names_sorted if n not in reserved]

    def is_digits_only(n: str) -> bool:
        return bool(n) and n.isdigit()

    non_digit = [n for n in candidates if not is_digits_only(n)]
    suggested: str | None = None
    if "neo4j" in non_digit:
        suggested = "neo4j"
    elif non_digit:
        homes_first = [n for n in non_digit if by_name.get(n, {}).get("home")]
        suggested = homes_first[0] if homes_first else non_digit[0]

    if suggested and not is_digits_only(suggested):
        print(f"  Suggested .env line: NEO4J_DATABASE={suggested}")
        return

    if candidates and all(is_digits_only(c) for c in candidates):
        print(
            "  ** Only digits-only catalog name(s) found (often the Aura instance id). "
            "Do **not** set ``NEO4J_DATABASE`` to that value — Bolt usually rejects it even if it appears here. "
            "In the Aura / Neo4j workspace, open **Query** and confirm which graph/database runs your data; "
            "if reads still fail, diagnose will try a one-off ``neo4j+s`` routing driver; "
            "you can also set ``NEO4J_DRIVER_MODE=routing`` in .env."
        )
        return

    if not candidates:
        print("  No user databases listed besides ``system`` (check Aura console).")
        return

    print(
        "  Could not infer a safe ``NEO4J_DATABASE`` from the catalog; set it explicitly "
        "to the graph name shown in your Aura / Neo4j workspace (not the instance id)."
    )


def main() -> int:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from src.project_env import load_project_dotenv

    load_project_dotenv()

    from src.graph_store import neo4j_client as nc

    uri = nc.neo4j_uri()
    user, pw = nc.neo4j_auth()
    db = nc.neo4j_database()
    raw_db = (os.getenv("NEO4J_DATABASE") or "").strip()

    print("Neo4j diagnose")
    print(f"  NEO4J_URI set: {bool(uri)}")
    eff = nc.effective_neo4j_uri(uri) if uri else None
    if eff and eff != uri:
        from urllib.parse import urlparse as _up

        pe = _up(eff)
        print(f"  Driver URI (effective): {pe.scheme!r}  host: {pe.hostname!r}")
        print(
            "  (Rewritten from neo4j*:// — Aura defaults to direct Bolt to avoid routing-table failures.)"
        )
    if eff and eff.startswith("bolt+ssc://"):
        print(
            "  ** TLS: ``bolt+ssc`` (``NEO4J_TLS_INSECURE``) — server cert verification is relaxed; "
            "use only for local PoC.**"
        )
    if uri:
        from urllib.parse import urlparse

        p = urlparse(uri)
        host = p.hostname or ""
        print(f"  Configured URI scheme: {p.scheme!r}  host: {host!r}")
        if host and "." not in host and host.isdigit():
            print(
                "  ** Warning: host looks like an Aura instance id only. "
                "Use the full host, e.g. ``<id>.databases.neo4j.io`` (from Aura console)."
            )
        if host and not host.endswith(".databases.neo4j.io") and "neo4j" in (p.scheme or ""):
            print("  ** Hint: Aura URIs usually end with ``.databases.neo4j.io``.")
    print(f"  NEO4J_PASSWORD set: {bool(pw)}")
    print(
        f"  NEO4J_DATABASE (effective): {db!r} "
        "(None = omit ``database=``; on Aura set ``NEO4J_DATABASE`` or ``NEO4J_AURA_DEFAULT_DATABASE=neo4j`` if needed)"
    )
    if raw_db and raw_db.isdigit():
        if nc._aura_effective_host_lower().endswith(".databases.neo4j.io"):
            print(
                f"  ** Note: NEO4J_DATABASE ``{raw_db}`` is digits-only (often the Aura instance id). "
                "That is not a Neo4j database name — it is ignored. Set ``NEO4J_DATABASE`` to your "
                "catalog name (run diagnose after a read failure to list ``SHOW DATABASES``), "
                "or ``NEO4J_AURA_DEFAULT_DATABASE=neo4j`` for classic Aura."
            )
        else:
            print(
                f"  ** Note: NEO4J_DATABASE ``{raw_db}`` is digits-only and is ignored as likely an instance id. "
                "Remove it or set your real database name."
            )
    if not uri or not pw:
        print("\nFix: set NEO4J_URI and NEO4J_PASSWORD in .env (copy from env.template).")
        return 1

    ca = nc.apply_certifi_ca_bundle_if_needed()
    if ca:
        print(f"  SSL_CERT_FILE (certifi, default): {ca}")
    elif not os.environ.get("SSL_CERT_FILE"):
        print("  ** Note: SSL_CERT_FILE unset and certifi not importable — run ``pip install certifi``.")

    try:
        nc.verify_connectivity()
        print("\n  verify_connectivity: OK")
    except Exception as exc:
        print(f"\n  verify_connectivity FAILED: {type(exc).__name__}: {exc}")
        msg = str(exc).lower()
        print("  Check URI, user/password, firewall/VPN.")
        if "ssl" in msg or "certificate" in msg or "tls" in msg:
            print(
                "  ** SSL / certificate:** Prefer fixing trust store: "
                "``pip install --upgrade certifi``; on macOS (python.org builds) run "
                "``/Applications/Python 3.x/Install Certificates.command``. "
                "PoC-only workaround: ``NEO4J_TLS_INSECURE=1`` in .env (uses ``bolt+ssc`` — **MITM risk**)."
            )
        if "operation not permitted" in msg or "eperm" in msg:
            print(
                "  ** ``Operation not permitted``:** can be macOS security / VPN / proxy blocking TLS sockets; "
                "try another network or terminal outside a restricted sandbox."
            )
        if "routing" in msg or "unable to retrieve" in msg:
            print(
                "  ** If routing still fails:** set ``NEO4J_DRIVER_MODE=direct`` explicitly, or\n"
                "     ``NEO4J_DRIVER_MODE=routing`` only if you must use the cluster routing driver.\n"
                "     Non-Aura ``neo4j+s://`` URIs are unchanged unless ``direct`` is set."
            )
        return 2

    try:
        from src.graph_store.neo4j_read_session import run_read_query

        rows = run_read_query(
            "MATCH (n:Entity) RETURN count(n) AS entity_count LIMIT 1",
            {},
        )
        n = int(rows[0]["entity_count"]) if rows else 0
        print(f"\n  :Entity count: {n}")
        if n == 0:
            print(
                "  Your database has no :Entity nodes. Load data with:\n"
                "    PYTHONPATH=. python -m src.graph_store.sync_processed --clear"
            )
            return 3
    except Exception as exc:
        print(f"\n  Read query FAILED: {type(exc).__name__}: {exc}")
        msg = str(exc).lower()
        print(
            "  If ``Database … not found``: set ``NEO4J_DATABASE`` (or ``NEO4J_AURA_DEFAULT_DATABASE``) "
            "to a catalog name that exists on this instance — see ``SHOW DATABASES`` below if available.\n"
            "  Ensure ``sync_processed`` has been run against this instance."
        )
        _print_database_catalog_hint(nc)
        if _is_database_not_found(exc):
            retry = _try_aura_routing_entity_read(nc)
            if retry is not None:
                n2, ruri = retry
                print(
                    f"\n  ** Read with routing driver succeeded ** (``{ruri}``).\n"
                    "  **Action:** set ``NEO4J_DRIVER_MODE=routing`` in ``.env`` so the app uses this URI mode "
                    "(direct ``bolt+s://`` can mis-resolve the database on some Aura instances)."
                )
                print(f"\n  :Entity count: {n2}")
                if n2 == 0:
                    print(
                        "  Your database has no :Entity nodes. Load data with:\n"
                        "    PYTHONPATH=. python -m src.graph_store.sync_processed --clear"
                    )
                    return 3
                print("\nAll checks passed — native / LLM Cypher tool reads should work with ``NEO4J_DRIVER_MODE=routing``.")
                return 0
        if "routing" in msg or "unable to retrieve" in msg:
            print(
                "  ** Routing errors:** Aura URIs default to direct Bolt — pull latest code, "
                "or set ``NEO4J_DRIVER_MODE=direct``. If you forced ``NEO4J_DRIVER_MODE=routing``, remove it."
            )
        return 4

    print("\nAll checks passed — native / LLM Cypher tool reads should be able to query this DB.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

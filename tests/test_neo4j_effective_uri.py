"""Tests for Neo4j URI / driver-mode logic (no live database).

Patch ``_neo4j_driver_mode`` so results do not depend on the developer's ``.env``
(``load_dotenv`` runs on ``neo4j_client`` import and would otherwise restore flags).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_non_aura_uri_unchanged_in_auto_mode(monkeypatch) -> None:
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "auto")
    monkeypatch.delenv("NEO4J_TLS_INSECURE", raising=False)
    monkeypatch.delenv("NEO4J_SSL_INSECURE", raising=False)
    u = "neo4j+s://neo4j.mycompany.internal:7687"
    assert nc.effective_neo4j_uri(u) == u


def test_aura_host_auto_uses_direct_bolt(monkeypatch) -> None:
    """*.databases.neo4j.io + auto driver mode → bolt+s (no routing table)."""
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "auto")
    monkeypatch.delenv("NEO4J_TLS_INSECURE", raising=False)
    monkeypatch.delenv("NEO4J_SSL_INSECURE", raising=False)
    u = "neo4j+s://76944085.databases.neo4j.io"
    assert nc.effective_neo4j_uri(u) == "bolt+s://76944085.databases.neo4j.io"


def test_explicit_routing_keeps_neo4j_scheme(monkeypatch) -> None:
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "routing")
    monkeypatch.delenv("NEO4J_TLS_INSECURE", raising=False)
    monkeypatch.delenv("NEO4J_SSL_INSECURE", raising=False)
    u = "neo4j+s://76944085.databases.neo4j.io"
    assert nc.effective_neo4j_uri(u) == u


def test_explicit_direct_rewrites(monkeypatch) -> None:
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "direct")
    monkeypatch.delenv("NEO4J_TLS_INSECURE", raising=False)
    monkeypatch.delenv("NEO4J_SSL_INSECURE", raising=False)
    assert (
        nc.effective_neo4j_uri("neo4j+s://abc.databases.neo4j.io")
        == "bolt+s://abc.databases.neo4j.io"
    )
    assert (
        nc.effective_neo4j_uri("neo4j+ssc://x.example.com")
        == "bolt+ssc://x.example.com"
    )
    assert nc.effective_neo4j_uri("neo4j://localhost:7687") == "bolt://localhost:7687"
    assert nc.effective_neo4j_uri("bolt+s://already") == "bolt+s://already"


def test_neo4j_database_numeric_instance_id_non_aura_is_none(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_DATABASE", "76944085")
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() is None


def test_neo4j_database_numeric_instance_id_aura_omits_without_aura_default(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt+s://76944085.databases.neo4j.io")
    monkeypatch.setenv("NEO4J_DATABASE", "76944085")
    monkeypatch.delenv("NEO4J_AURA_DEFAULT_DATABASE", raising=False)
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() is None


def test_neo4j_database_unset_aura_omits_database(monkeypatch) -> None:
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.delenv("NEO4J_AURA_DEFAULT_DATABASE", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt+s://abc.databases.neo4j.io")
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() is None


def test_neo4j_database_aura_default_database_neo4j_explicit(monkeypatch) -> None:
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.setenv("NEO4J_AURA_DEFAULT_DATABASE", "neo4j")
    monkeypatch.setenv("NEO4J_URI", "bolt+s://abc.databases.neo4j.io")
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() == "neo4j"


def test_neo4j_database_aura_default_database_none(monkeypatch) -> None:
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.setenv("NEO4J_AURA_DEFAULT_DATABASE", "none")
    monkeypatch.setenv("NEO4J_URI", "bolt+s://abc.databases.neo4j.io")
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() is None


def test_neo4j_database_unset_non_aura_ignores_aura_default(monkeypatch) -> None:
    monkeypatch.delenv("NEO4J_DATABASE", raising=False)
    monkeypatch.delenv("NEO4J_AURA_DEFAULT_DATABASE", raising=False)
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() is None


def test_neo4j_database_keeps_valid_name(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setenv("NEO4J_DATABASE", "mydb")
    from src.graph_store import neo4j_client as nc

    assert nc.neo4j_database() == "mydb"


def test_effective_uri_driver_mode_routing_restores_neo4j_after_auto_bolt(monkeypatch) -> None:
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "auto")
    monkeypatch.delenv("NEO4J_TLS_INSECURE", raising=False)
    monkeypatch.delenv("NEO4J_SSL_INSECURE", raising=False)
    u = "neo4j+s://76944085.databases.neo4j.io"
    assert nc.effective_neo4j_uri(u) == "bolt+s://76944085.databases.neo4j.io"
    assert nc.effective_neo4j_uri(u, driver_mode="routing") == "neo4j+s://76944085.databases.neo4j.io"


def test_effective_uri_routing_converts_bolt_plus_s_aura_to_neo4j(monkeypatch) -> None:
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "auto")
    monkeypatch.delenv("NEO4J_TLS_INSECURE", raising=False)
    monkeypatch.delenv("NEO4J_SSL_INSECURE", raising=False)
    b = "bolt+s://76944085.databases.neo4j.io"
    assert nc.effective_neo4j_uri(b, driver_mode="routing") == "neo4j+s://76944085.databases.neo4j.io"


def test_tls_insecure_rewrites_s_to_ssc(monkeypatch) -> None:
    monkeypatch.setenv("NEO4J_TLS_INSECURE", "1")
    from src.graph_store import neo4j_client as nc

    monkeypatch.setattr(nc, "_neo4j_driver_mode", lambda: "auto")
    assert (
        nc.effective_neo4j_uri("neo4j+s://76944085.databases.neo4j.io")
        == "bolt+ssc://76944085.databases.neo4j.io"
    )


def test_apply_certifi_sets_ssl_cert_file(monkeypatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("NEO4J_USE_CERTIFI_CA_BUNDLE", "1")
    from src.graph_store import neo4j_client as nc

    p = nc.apply_certifi_ca_bundle_if_needed()
    assert p
    assert os.environ.get("SSL_CERT_FILE") == p


def test_apply_certifi_skipped_when_disabled(monkeypatch) -> None:
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setenv("NEO4J_USE_CERTIFI_CA_BUNDLE", "0")
    from src.graph_store import neo4j_client as nc

    assert nc.apply_certifi_ca_bundle_if_needed() is None
    assert os.environ.get("SSL_CERT_FILE") is None

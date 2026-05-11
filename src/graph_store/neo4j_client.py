"""Neo4j driver factory from environment (Aura-friendly URIs; Aura defaults to direct Bolt)."""

from __future__ import annotations

import os
import threading
from collections.abc import Generator
from contextlib import contextmanager

from neo4j import Driver, GraphDatabase, Session

from src.project_env import load_project_dotenv

load_project_dotenv()

_singleton_driver: Driver | None = None
_singleton_lock = threading.Lock()


def neo4j_uri() -> str | None:
    return os.getenv("NEO4J_URI") or os.getenv("NEO4J_URL")


def _neo4j_driver_mode() -> str:
    """
    ``direct`` — force ``bolt*://`` (no routing table).

    ``routing`` — keep ``neo4j*://`` (cluster / Aura routing driver).

    ``auto`` — **Aura** hosts (``*.databases.neo4j.io``) default to **direct** Bolt because
    ``neo4j+s://`` often hits ``Unable to retrieve routing information`` on VPNs / strict DNS;
    other hosts keep the configured scheme.
    """
    raw = (os.getenv("NEO4J_DRIVER_MODE") or "").strip().lower()
    if raw in ("direct", "bolt", "1", "true", "yes", "on"):
        return "direct"
    if raw in ("routing", "cluster", "neo4j"):
        return "routing"
    if (os.getenv("NEO4J_USE_DIRECT_BOLT") or "").strip().lower() in ("1", "true", "yes", "on"):
        return "direct"
    return "auto"


def _to_direct_bolt(uri: str) -> str:
    for prefix, repl in (
        ("neo4j+s://", "bolt+s://"),
        ("neo4j+ssc://", "bolt+ssc://"),
        ("neo4j://", "bolt://"),
    ):
        if uri.startswith(prefix):
            return repl + uri[len(prefix) :]
    return uri


def _to_routing_neo4j_scheme(uri: str) -> str:
    """Undo direct Bolt: ``bolt*://`` → ``neo4j*://`` for cluster / Aura routing drivers."""
    for prefix, repl in (
        ("bolt+s://", "neo4j+s://"),
        ("bolt+ssc://", "neo4j+ssc://"),
        ("bolt://", "neo4j://"),
    ):
        if uri.startswith(prefix):
            return repl + uri[len(prefix) :]
    return uri


def _maybe_insecure_tls_ssc(uri: str) -> str:
    """
    When ``NEO4J_TLS_INSECURE=1`` (or ``NEO4J_SSL_INSECURE``), rewrite ``+s`` → ``+ssc``.

    The Neo4j driver treats ``+ssc`` as encrypted with **TrustAll** (no system CA verification).
    **Insecure (MITM risk)** — only for local PoC when ``SSLCertVerificationError`` cannot be
    fixed (fix Python CA bundle first: ``pip install --upgrade certifi`` or macOS
    ``Install Certificates.command``).
    """
    v = (os.getenv("NEO4J_TLS_INSECURE") or os.getenv("NEO4J_SSL_INSECURE") or "").strip().lower()
    if v not in ("1", "true", "yes", "on"):
        return uri
    for secure, ssc in (
        ("bolt+s://", "bolt+ssc://"),
        ("neo4j+s://", "neo4j+ssc://"),
    ):
        if uri.startswith(secure):
            return ssc + uri[len(secure) :]
    return uri


def _driver_mode_for_effective_uri(driver_mode: str | None) -> str:
    if driver_mode is None:
        return _neo4j_driver_mode()
    m = driver_mode.strip().lower()
    if m in ("direct", "routing", "auto"):
        return m
    return _neo4j_driver_mode()


def effective_neo4j_uri(raw: str | None, *, driver_mode: str | None = None) -> str | None:
    """
    Return the URI passed to the Python driver.

    **Explicit** ``NEO4J_DRIVER_MODE=direct`` (or ``NEO4J_USE_DIRECT_BOLT=1``): rewrite
    ``neo4j+s://`` → ``bolt+s://`` so the driver does not fetch a routing table.

    **Explicit** ``NEO4J_DRIVER_MODE=routing``: use Aura / cluster routing (``neo4j*://``).
    If the configured URI is ``bolt*://`` toward **Aura**, rewrite back to ``neo4j*://``.

    **Default (auto):** if the host is ``*.databases.neo4j.io`` (Neo4j Aura) and the URI uses a
    ``neo4j*://`` scheme, rewrite to ``bolt*://`` — same credentials, avoids routing failures
    on many networks. Non-Aura URIs are left unchanged unless ``direct`` is set.

    **TLS (last step):** ``NEO4J_TLS_INSECURE=1`` rewrites ``bolt+s`` / ``neo4j+s`` → ``+ssc``
    (driver trust-all). Prefer fixing the Python SSL trust store instead.

    ``driver_mode`` — optional ``direct`` / ``routing`` / ``auto`` override for one-off drivers
    (e.g. diagnose) without changing ``NEO4J_DRIVER_MODE`` in the environment.
    """
    if not raw:
        return None
    uri = raw.strip()
    mode = _driver_mode_for_effective_uri(driver_mode)
    if mode == "direct":
        out = _to_direct_bolt(uri)
    elif mode == "routing":
        from urllib.parse import urlparse

        host = (urlparse(uri).hostname or "").lower()
        if host.endswith(".databases.neo4j.io") and uri.startswith(("bolt+s://", "bolt+ssc://", "bolt://")):
            out = _to_routing_neo4j_scheme(uri)
        else:
            out = uri
    elif uri.startswith(("neo4j+s://", "neo4j+ssc://", "neo4j://")):
        from urllib.parse import urlparse

        host = (urlparse(uri).hostname or "").lower()
        if host.endswith(".databases.neo4j.io"):
            out = _to_direct_bolt(uri)
        else:
            out = uri
    else:
        out = uri
    return _maybe_insecure_tls_ssc(out)


def neo4j_auth() -> tuple[str, str]:
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME") or "neo4j"
    password = os.getenv("NEO4J_PASSWORD") or ""
    return user, password


def _aura_effective_host_lower() -> str:
    """Hostname from configured (effective) Neo4j URI, lowercased."""
    u = effective_neo4j_uri(neo4j_uri()) or ""
    if not u:
        return ""
    from urllib.parse import urlparse

    return (urlparse(u).hostname or "").lower()


def neo4j_database() -> str | None:
    """
    Database name for ``driver.session(database=…)``.

    **Digits-only** ``NEO4J_DATABASE`` (common mistake: Aura **instance id**) is treated as
    unset so the driver does not open ``database=<id>`` (``Database … not found``).

    On **Aura** (``*.databases.neo4j.io``), if still unset, ``NEO4J_AURA_DEFAULT_DATABASE`` is
    used when **non-empty** (e.g. ``neo4j`` for classic Aura). When that env is unset or
    ``none`` / ``0`` / ``false`` / ``off``, return ``None`` — omit ``database=`` so the server
    picks the home graph (some Aura / Neo4j builds have no catalog database named ``neo4j``).

    Non-Aura: unset → ``None``.
    """
    raw = (os.getenv("NEO4J_DATABASE") or "").strip()
    if raw.isdigit():
        raw = ""
    if raw:
        return raw
    if _aura_effective_host_lower().endswith(".databases.neo4j.io"):
        v = (os.getenv("NEO4J_AURA_DEFAULT_DATABASE") or "").strip()
        if not v or v.lower() in ("0", "false", "none", "off"):
            return None
        return v
    return None


def neo4j_session_kwargs() -> dict[str, str]:
    """Keyword args for ``driver.session()`` — omit ``database`` when unset (non-Aura default)."""
    db = neo4j_database()
    return {"database": db} if db else {}


def apply_certifi_ca_bundle_if_needed() -> str | None:
    """
    If ``SSL_CERT_FILE`` is unset, set it to **certifi**'s Mozilla CA bundle (when installed).

    Default **on** (set ``NEO4J_USE_CERTIFI_CA_BUNDLE=0`` to skip). Many macOS / venv Python
    builds cannot verify Aura (Let's Encrypt) without this. Idempotent.
    """
    if (os.getenv("NEO4J_USE_CERTIFI_CA_BUNDLE") or "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return None
    if os.environ.get("SSL_CERT_FILE"):
        return None
    try:
        import certifi

        path = certifi.where()
        if path:
            os.environ["SSL_CERT_FILE"] = path
            return path
    except ImportError:
        pass
    return None


def open_driver(*, driver_mode: str | None = None) -> Driver:
    """Open a fresh driver (closes connection when you call driver.close()). Prefer get_driver().

    ``driver_mode`` — optional ``direct`` / ``routing`` / ``auto`` override (see ``effective_neo4j_uri``).
    """
    uri = effective_neo4j_uri(neo4j_uri(), driver_mode=driver_mode)
    if not uri:
        raise RuntimeError(
            "Set NEO4J_URI in .env (see env.template; e.g. neo4j+s://xxxx.databases.neo4j.io for Aura)."
        )
    user, password = neo4j_auth()
    if not password:
        raise RuntimeError("Set NEO4J_PASSWORD in .env (see env.template).")
    apply_certifi_ca_bundle_if_needed()
    return GraphDatabase.driver(uri, auth=(user, password))


def get_driver() -> Driver:
    """Return a persistent module-level driver whose connection pool stays open between calls.

    Eliminates the per-query TLS handshake overhead that open_driver()+driver.close() causes.
    Thread-safe (double-checked locking).
    """
    global _singleton_driver
    if _singleton_driver is None:
        with _singleton_lock:
            if _singleton_driver is None:
                _singleton_driver = open_driver()
    return _singleton_driver


@contextmanager
def driver_session() -> Generator[tuple[Driver, Session], None, None]:
    driver = open_driver()
    try:
        session = driver.session(**neo4j_session_kwargs())
        try:
            yield driver, session
        finally:
            session.close()
    finally:
        driver.close()


def verify_connectivity(*, driver_mode: str | None = None) -> None:
    driver = open_driver(driver_mode=driver_mode)
    try:
        driver.verify_connectivity()
    finally:
        driver.close()

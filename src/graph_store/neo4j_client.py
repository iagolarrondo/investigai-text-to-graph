"""Neo4j driver factory from environment (Aura-friendly ``neo4j+s://`` URIs)."""

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


def neo4j_auth() -> tuple[str, str]:
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME") or "neo4j"
    password = os.getenv("NEO4J_PASSWORD") or ""
    return user, password


def neo4j_database() -> str | None:
    """Return database name, or None for server default (Aura Free uses ``neo4j`` implicitly)."""
    db = os.getenv("NEO4J_DATABASE")
    return db if db else None


def open_driver() -> Driver:
    """Open a fresh driver (closes connection when you call driver.close()). Prefer get_driver()."""
    uri = neo4j_uri()
    if not uri:
        raise RuntimeError(
            "Set NEO4J_URI in .env.example (e.g. neo4j+s://xxxx.databases.neo4j.io for Aura)."
        )
    user, password = neo4j_auth()
    if not password:
        raise RuntimeError("Set NEO4J_PASSWORD in .env.example.")
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
    db = neo4j_database()
    try:
        session = driver.session(database=db) if db else driver.session()
        try:
            yield driver, session
        finally:
            session.close()
    finally:
        driver.close()


def verify_connectivity() -> None:
    driver = open_driver()
    try:
        driver.verify_connectivity()
    finally:
        driver.close()

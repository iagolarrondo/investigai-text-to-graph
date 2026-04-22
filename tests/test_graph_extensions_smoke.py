"""Smoke: **active** registry extensions must import and register ``run``."""

from __future__ import annotations

import importlib

from src.graph_query.extension_loader import (
    active_extension_specs,
    load_extension_handlers,
    read_registry_entries,
)


def test_registry_is_list_on_disk():
    entries = read_registry_entries()
    assert isinstance(entries, list)


def test_active_extensions_have_handlers():
    specs = active_extension_specs()
    handlers = load_extension_handlers()
    missing = [s["name"] for s in specs if s["name"] not in handlers]
    assert not missing, f"registry tools without importable run(): {missing}"
    for fn in handlers.values():
        assert callable(fn)


def test_generated_modules_are_importable():
    for e in read_registry_entries():
        if not e.get("active", True):
            continue
        mod = str(e.get("module") or e.get("name", "")).strip()
        if not mod:
            continue
        importlib.import_module(f"src.graph_query.generated.{mod}")

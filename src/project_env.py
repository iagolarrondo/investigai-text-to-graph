"""Project root and dotenv file. Prefer ``.env``; fall back to legacy ``.env.example``."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"
LEGACY_DOTENV_PATH = PROJECT_ROOT / ".env.example"


def load_project_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if DOTENV_PATH.exists():
        load_dotenv(DOTENV_PATH)
    elif LEGACY_DOTENV_PATH.exists():
        load_dotenv(LEGACY_DOTENV_PATH)

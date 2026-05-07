"""Project root and local ``.env`` loading.

Copy ``env.template`` to ``.env`` in the project root and set your keys there.
Only ``.env`` is loaded automatically (not ``env.template``).
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOTENV_PATH = PROJECT_ROOT / ".env"


def load_project_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if DOTENV_PATH.exists():
        load_dotenv(DOTENV_PATH)

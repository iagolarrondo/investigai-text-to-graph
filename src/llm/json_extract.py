"""Shared helpers to parse JSON objects from LLM text (fences, extra prose)."""

from __future__ import annotations

import json
import re
from typing import Any


def strip_json_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def extract_json_object(raw: str) -> dict[str, Any] | None:
    text = strip_json_fence(raw)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
            return data[0]
        return None
    except json.JSONDecodeError:
        pass
    i = text.find("{")
    j = text.rfind("}")
    if i >= 0 and j > i:
        try:
            data = json.loads(text[i : j + 1])
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
                return data[0]
            return None
        except json.JSONDecodeError:
            return None
    return None

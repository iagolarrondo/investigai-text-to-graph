"""Eval dataset loading, bucketing, and scoring helpers for the Streamlit Evals page."""
from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_EVAL_CSV = _PROJECT_ROOT / "eval" / "generated_qa.csv"

# Investigator-question buckets from eval/investigator_question_set.md.
# Tuple is (bucket_idx, bucket_title, qid_range_inclusive).
_BUCKETS: list[tuple[int, str, range]] = [
    (1, "Policy & Claim Information", range(1, 6)),
    (2, "People & Relationships", range(6, 11)),
    (3, "Providers", range(11, 16)),
    (4, "Caregiver App Sessions & Geolocation", range(16, 23)),
    (5, "Clinical & Medical Information", range(23, 28)),
    (6, "Billing, Payments & Financial", range(28, 33)),
    (7, "Review Cycles & Remediations", range(33, 37)),
    (8, "Graph-Native & Inference Questions", range(37, 51)),
]


def bucket_for_qid(qid: str) -> tuple[int, str] | None:
    """Map a qid like 'Q28' to its bucket (idx, title), or None if unknown."""
    try:
        n = int(qid[1:])
    except (ValueError, IndexError):
        return None
    for idx, title, rng in _BUCKETS:
        if n in rng:
            return idx, title
    return None


def all_buckets() -> list[tuple[int, str]]:
    return [(idx, title) for idx, title, _ in _BUCKETS]


@dataclass
class EvalRow:
    qid: str
    claim_node_id: str
    claim_number: str
    question_template: str
    question_text: str
    expected_answer_type: str
    expected_answer: str
    evidence_node_ids: str
    notes: str
    bucket_idx: int
    bucket_title: str


def load_eval_rows(csv_path: Path | None = None) -> list[EvalRow]:
    path = csv_path or _EVAL_CSV
    rows: list[EvalRow] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            qid = r.get("qid", "").strip()
            b = bucket_for_qid(qid)
            if b is None:
                continue
            rows.append(
                EvalRow(
                    qid=qid,
                    claim_node_id=r.get("claim_node_id", ""),
                    claim_number=r.get("claim_number", ""),
                    question_template=r.get("question_template", ""),
                    question_text=r.get("question_text", ""),
                    expected_answer_type=r.get("expected_answer_type", ""),
                    expected_answer=r.get("expected_answer", ""),
                    evidence_node_ids=r.get("evidence_node_ids", ""),
                    notes=r.get("notes", ""),
                    bucket_idx=b[0],
                    bucket_title=b[1],
                )
            )
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Scoring
# ─────────────────────────────────────────────────────────────────────────────

_NEG_RE = re.compile(
    r"\b("
    r"unknown|n/a|"
    r"not\s+(?:found|listed|recorded|available|on\s+file|present|known|associated)|"
    r"no\s+(?:record|records|data|result|results|match|matches|info|information|"
    r"policyholder|claim|claims|agent|agents|provider|providers|account|accounts|"
    r"entity|entities|such|holder|one|payment|payments|address)|"
    r"no\s+\w+(?:\s+\w+){0,4}\s+(?:found|record|recorded|listed|known|on\s+file|exists?|associated|filed)|"
    r"none\s+(?:found|known|listed|on\s+file|exist|associated)|"
    r"(?:could|did|do|does|was|were|is|are)\s*n[o’']t\s+(?:find|locate|see|know|exist|have|appear)|"
    r"unable\s+to\s+(?:find|locate|determine)|"
    r"absent|missing"
    r")\b"
)
_BOOL_YES = ("yes", "true", "is ", "does ", "has ", "there is", "there are")
_BOOL_NO = ("no", "false", "isn't", "is not", "does not", "doesn't",
            "has not", "hasn't", "there is no", "there are no")


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def _try_parse_json(s: str) -> Any:
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _flatten_strings(value: Any) -> list[str]:
    """Return all string-ish leaves of a JSON-like value, lowercased."""
    out: list[str] = []
    if value is None:
        return out
    if isinstance(value, (str, int, float, bool)):
        out.append(_normalize(str(value)))
    elif isinstance(value, list):
        for v in value:
            out.extend(_flatten_strings(v))
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten_strings(v))
    return [s for s in out if s]


@dataclass
class ScoreResult:
    passed: bool
    score: float  # 0.0 – 1.0
    detail: str  # short human-readable explanation
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def score_answer(expected: str, expected_type: str, actual: str) -> ScoreResult:
    """Best-effort grader. Substring-based for strings; element coverage for lists/objects."""
    actual_n = _normalize(actual)
    expected_s = (expected or "").strip()
    expected_n = _normalize(expected_s)

    if not actual_n:
        return ScoreResult(False, 0.0, "No answer text produced.")

    is_blank_expected = expected_s in ("", "[]", "{}")
    is_unknown_expected = expected_n == "unknown"

    # "no data" / "unknown" expected: pass if the answer indicates absence.
    if is_blank_expected or is_unknown_expected:
        if _NEG_RE.search(actual_n):
            return ScoreResult(True, 1.0, "Correctly reported no data / unknown.")
        return ScoreResult(False, 0.0, "Expected no-data/unknown but the answer asserted a value.")

    t = (expected_type or "").lower()

    if t == "bool":
        truthy = expected_n in ("true", "yes", "1")
        falsy = expected_n in ("false", "no", "0")
        if truthy:
            if any(tok in actual_n for tok in _BOOL_YES) and not any(
                tok in actual_n for tok in ("no ", "not ", "isn't", "doesn't", "hasn't")
            ):
                return ScoreResult(True, 1.0, "Correctly affirmed.")
            return ScoreResult(False, 0.0, "Expected yes/true but answer was negative or unclear.")
        if falsy:
            if any(tok in actual_n for tok in _BOOL_NO):
                return ScoreResult(True, 1.0, "Correctly denied.")
            return ScoreResult(False, 0.0, "Expected no/false but answer was affirmative or unclear.")
        # Fall through to substring if expected isn't a clean bool.

    if t == "number":
        nums = re.findall(r"-?\d+(?:\.\d+)?", expected_s)
        if nums:
            target = nums[0]
            if target in actual:
                return ScoreResult(True, 1.0, f"Number {target} present in answer.")
            return ScoreResult(False, 0.0, f"Number {target} not present in answer.")

    if t in ("list", "object"):
        parsed = _try_parse_json(expected_s)
        elements = _flatten_strings(parsed) if parsed is not None else []
        if not elements:
            # Fallback to substring of the raw expected.
            if expected_n and expected_n in actual_n:
                return ScoreResult(True, 1.0, "Expected JSON appears as substring.")
            return ScoreResult(False, 0.0, "Could not parse expected JSON; no substring match.")
        matched = [e for e in elements if e and e in actual_n]
        missing = [e for e in elements if e and e not in actual_n]
        coverage = len(matched) / len(elements)
        passed = coverage >= 0.7  # at least 70% of leaf strings appear
        return ScoreResult(
            passed,
            coverage,
            f"{len(matched)}/{len(elements)} expected elements found in answer.",
            matched=matched,
            missing=missing,
        )

    # Default: string substring.
    if expected_n and expected_n in actual_n:
        return ScoreResult(True, 1.0, "Expected string present in answer.")
    return ScoreResult(False, 0.0, "Expected string not present in answer.")


# ─────────────────────────────────────────────────────────────────────────────
# LLM judge — semantic grading via the same backend as the investigation
# ─────────────────────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """You are an evaluator grading an investigator-assistant answer against a ground-truth answer.

You will be given:
- QUESTION: what the user asked.
- EXPECTED_TYPE: one of string | bool | number | list | object.
- EXPECTED: the ground-truth answer (may be a literal value, JSON list/object, the string "Unknown", or empty / [] / {}).
- ACTUAL: the answer produced by the system under test.

Decide whether ACTUAL is semantically consistent with EXPECTED for that QUESTION. Apply these rules:
1. EXPECTED is "Unknown", empty, "[]", or "{}" → pass if ACTUAL correctly conveys absence ("no data", "not found",
   "no policyholder on record", a clear negative answer, etc.). Fail if ACTUAL fabricates a specific value.
2. EXPECTED is a scalar (string / bool / number) → pass if ACTUAL asserts the same fact, regardless of wording,
   verbosity, or formatting (synonyms, full sentences, currency formatting all OK).
3. EXPECTED is a list / object → pass if ACTUAL covers the key elements / fields. Order, formatting, casing, and
   minor name variants do not matter; missing or fabricated entries do.
4. Fail if ACTUAL is unrelated, contradicts EXPECTED, or hallucinates entities not in EXPECTED.
5. ACTUAL may include explanation, citations, or extra context — do not penalize verbosity.

Reply with STRICT JSON only — no preamble, no code fences:
{"passed": true|false, "score": 0.0-1.0, "reasoning": "one or two short sentences"}
"""


def _judge_user_text(question: str, expected_type: str, expected: str, actual: str) -> str:
    return (
        f"QUESTION:\n{question}\n\n"
        f"EXPECTED_TYPE: {expected_type or 'string'}\n"
        f"EXPECTED:\n{expected if expected else '(empty)'}\n\n"
        f"ACTUAL:\n{actual if actual else '(empty)'}\n"
    )


def _strip_json_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        # Drop the opening fence (``` or ```json) and its newline.
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        if s.endswith("```"):
            s = s[: -3]
    return s.strip()


def _parse_judge_json(raw: str) -> dict[str, Any] | None:
    txt = _strip_json_fence(raw)
    try:
        obj = json.loads(txt)
    except (ValueError, TypeError):
        # Try to extract the first {...} block.
        m = re.search(r"\{.*\}", txt, flags=re.DOTALL)
        if not m:
            return None
        try:
            obj = json.loads(m.group(0))
        except (ValueError, TypeError):
            return None
    return obj if isinstance(obj, dict) else None


def _judge_via_anthropic(question: str, expected_type: str, expected: str, actual: str) -> str:
    from anthropic import Anthropic
    from src.llm.anthropic_llm import anthropic_generate_text

    api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    model = (os.environ.get("EVAL_JUDGE_MODEL") or "").strip()
    if not model:
        model = (os.environ.get("ANTHROPIC_MODEL") or "claude-sonnet-4-6").strip()
    client = Anthropic(api_key=api_key)
    return anthropic_generate_text(
        client,
        model=model,
        system_instruction=_JUDGE_SYSTEM,
        user_text=_judge_user_text(question, expected_type, expected, actual),
        max_tokens=512,
    )


def _judge_via_gemini(question: str, expected_type: str, expected: str, actual: str) -> str:
    from google import genai
    from src.llm.gemini_llm import generate_text

    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set.")
    model = (os.environ.get("EVAL_JUDGE_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    client = genai.Client(api_key=api_key)
    return generate_text(
        client,
        model=model,
        system_instruction=_JUDGE_SYSTEM,
        user_text=_judge_user_text(question, expected_type, expected, actual),
        max_output_tokens=512,
    )


def _select_judge_backend() -> str:
    v = (os.environ.get("INVESTIGATION_LLM") or "anthropic").strip().lower()
    if v in ("ollama", "local"):
        # Ollama isn't reliable enough as a strict-JSON grader — prefer Anthropic if a key is set.
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        return "gemini" if (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")) else "anthropic"
    if v in ("anthropic", "claude"):
        return "anthropic"
    return "gemini"


def score_answer_llm(
    question: str,
    expected_type: str,
    expected: str,
    actual: str,
    *,
    fallback_to_heuristic: bool = True,
) -> ScoreResult:
    """LLM-based semantic grader. Falls back to ``score_answer`` if the LLM call fails."""
    if not (actual or "").strip():
        return ScoreResult(False, 0.0, "No answer text produced.")
    backend = _select_judge_backend()
    try:
        if backend == "anthropic":
            raw = _judge_via_anthropic(question, expected_type, expected, actual)
        else:
            raw = _judge_via_gemini(question, expected_type, expected, actual)
    except Exception as exc:  # noqa: BLE001
        if fallback_to_heuristic:
            heur = score_answer(expected, expected_type, actual)
            heur.detail = f"[LLM judge failed: {type(exc).__name__}] {heur.detail}"
            return heur
        return ScoreResult(False, 0.0, f"LLM judge failed: {type(exc).__name__}: {exc}")

    obj = _parse_judge_json(raw)
    if not obj:
        if fallback_to_heuristic:
            heur = score_answer(expected, expected_type, actual)
            heur.detail = f"[LLM judge returned non-JSON; using heuristic] {heur.detail}"
            return heur
        return ScoreResult(False, 0.0, "LLM judge returned non-JSON.")

    passed = bool(obj.get("passed", False))
    try:
        score = float(obj.get("score", 1.0 if passed else 0.0))
    except (ValueError, TypeError):
        score = 1.0 if passed else 0.0
    score = max(0.0, min(1.0, score))
    reasoning = str(obj.get("reasoning") or "").strip()
    if not reasoning:
        reasoning = "LLM judge: pass" if passed else "LLM judge: fail"
    return ScoreResult(passed=passed, score=score, detail=reasoning)

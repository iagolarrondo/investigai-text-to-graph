from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from src.llm.json_extract import extract_json_object
from src.llm.tool_agent import investigation_llm_backend
from src.session.memory import MemoryDigest, build_memory_digest

_HAS_NODE_ID_RE = re.compile(r"\b([A-Za-z]+\|[A-Za-z0-9_.-]+|[A-Za-z0-9_]+_[A-Za-z0-9_.-]+)\b")
_CONTEXT_CUE_RE = re.compile(
    r"\b(it|its|they|them|their|that|those|this|these|same|again|also|previous|earlier)\b",
    re.IGNORECASE,
)
_CLAIM_REF_RE = re.compile(r"\b(that|this|same)\s+claim\b", re.IGNORECASE)
_POLICY_REF_RE = re.compile(r"\b(that|this|same)\s+policy\b", re.IGNORECASE)
_PERSON_REF_RE = re.compile(r"\b(that|this|same)\s+(person|insured|agent|customer|member)\b", re.IGNORECASE)
_FOLLOWUP_START_RE = re.compile(r"^\s*(and|also|what about|how about|then|now)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ResolverDecision:
    action: str  # pass_through | rewrite | clarify
    resolved_question: str
    clarification_prompt: str = ""
    rationale: str = ""
    used_llm_fallback: bool = False


def _pick_recent_id(digest: MemoryDigest, prefix: str) -> str | None:
    p = prefix.lower()
    for node_id in reversed(digest.recent_focus_node_ids):
        if node_id.lower().startswith(p):
            return node_id
    for node_id in reversed(digest.recent_anchor_ids):
        if node_id.lower().startswith(p):
            return node_id
    return None


def _maybe_rewrite_deterministic(question: str, digest: MemoryDigest) -> ResolverDecision | None:
    q = (question or "").strip()
    if not q:
        return ResolverDecision(action="pass_through", resolved_question="", rationale="empty question")
    if digest.turn_count <= 0:
        return ResolverDecision(
            action="pass_through",
            resolved_question=q,
            rationale="no prior session turns",
        )
    if _HAS_NODE_ID_RE.search(q):
        return ResolverDecision(
            action="pass_through",
            resolved_question=q,
            rationale="question already has explicit node ids",
        )

    rewritten = q
    changed = False

    if _CLAIM_REF_RE.search(q):
        claim_id = _pick_recent_id(digest, "claim|") or _pick_recent_id(digest, "claim_")
        if claim_id:
            rewritten = _CLAIM_REF_RE.sub(claim_id, rewritten)
            changed = True
    if _POLICY_REF_RE.search(rewritten):
        policy_id = _pick_recent_id(digest, "policy|") or _pick_recent_id(digest, "policy_")
        if policy_id:
            rewritten = _POLICY_REF_RE.sub(policy_id, rewritten)
            changed = True
    if _PERSON_REF_RE.search(rewritten):
        person_id = _pick_recent_id(digest, "person|") or _pick_recent_id(digest, "person_")
        if person_id:
            rewritten = _PERSON_REF_RE.sub(person_id, rewritten)
            changed = True

    if changed:
        return ResolverDecision(
            action="rewrite",
            resolved_question=rewritten,
            rationale="deterministic reference rewrite from session entities",
        )

    looks_contextual = bool(_FOLLOWUP_START_RE.search(q) or _CONTEXT_CUE_RE.search(q))
    if not looks_contextual:
        return ResolverDecision(
            action="pass_through",
            resolved_question=q,
            rationale="no contextual cues; preserve standalone question",
        )
    return None


def _llm_rewrite_enabled() -> bool:
    raw = (os.environ.get("SESSION_MEMORY_LLM_REWRITE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _rewrite_with_llm(question: str, digest: MemoryDigest) -> ResolverDecision | None:
    if not _llm_rewrite_enabled():
        return None
    backend = investigation_llm_backend()
    compact_mem = {
        "recent_questions": digest.recent_questions[-3:],
        "recent_focus_node_ids": digest.recent_focus_node_ids[-4:],
        "recent_anchor_ids": digest.recent_anchor_ids[-10:],
        "latest_answer_excerpt": digest.latest_answer_excerpt,
    }
    system = (
        "You rewrite follow-up investigation questions into standalone questions when clearly needed.\n"
        "Be conservative:\n"
        "- pass_through by default\n"
        "- rewrite only when contextual dependency is clear\n"
        "- clarify only when necessary due to ambiguity\n"
        "Return JSON keys: action, resolved_question, clarification_prompt, rationale.\n"
        "action must be one of: pass_through, rewrite, clarify."
    )
    user_text = (
        "Session memory digest:\n"
        f"{json.dumps(compact_mem, ensure_ascii=True)}\n\n"
        f"New question:\n{question}\n\n"
        "Return only JSON."
    )
    try:
        raw = _generate_small_json(backend=backend, system=system, user_text=user_text)
        parsed = extract_json_object(raw) if raw else None
        if not isinstance(parsed, dict):
            return None
        action = str(parsed.get("action", "pass_through")).strip().lower()
        resolved = str(parsed.get("resolved_question", "")).strip() or question
        clarify = str(parsed.get("clarification_prompt", "")).strip()
        rationale = str(parsed.get("rationale", "")).strip()
        if action not in ("pass_through", "rewrite", "clarify"):
            action = "pass_through"
        if action == "clarify" and not clarify:
            clarify = "Could you clarify which prior entity you mean?"
        return ResolverDecision(
            action=action,
            resolved_question=resolved if action != "pass_through" else question,
            clarification_prompt=clarify,
            rationale=rationale or "LLM fallback resolver decision",
            used_llm_fallback=True,
        )
    except Exception:
        return None


def _generate_small_json(*, backend: str, system: str, user_text: str) -> str:
    if backend == "ollama":
        from ollama import Client

        from src.llm.local_ollama import ollama_generate_text

        host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip()
        client = Client(host=host, timeout=120.0)
        model_name = os.environ.get("OLLAMA_MODEL", "llama3.1:8b")
        return ollama_generate_text(
            client,
            model=model_name,
            system_instruction=system,
            user_text=user_text,
            num_predict=512,
            json_mode=True,
        )
    if backend == "anthropic":
        from src.llm.anthropic_llm import anthropic_generate_text

        api_key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
        if not api_key:
            return ""
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
        return anthropic_generate_text(
            client,
            model=model,
            system_instruction=system,
            user_text=user_text,
            max_tokens=512,
        )
    from google import genai

    from src.llm.gemini_llm import generate_text

    api_key_g = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key_g:
        return ""
    client_g = genai.Client(api_key=api_key_g)
    model_g = os.environ.get("INVESTIGATION_GEMINI_MODEL") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-pro"
    return generate_text(
        client_g,
        model=model_g,
        system_instruction=system,
        user_text=user_text,
        max_output_tokens=512,
    )


def resolve_question_with_session_memory(
    question: str,
    turns: list[dict[str, Any]],
) -> ResolverDecision:
    q = (question or "").strip()
    digest = build_memory_digest(turns, last_n=3)
    deterministic = _maybe_rewrite_deterministic(q, digest)
    if deterministic is not None:
        return deterministic
    llm_decision = _rewrite_with_llm(q, digest)
    if llm_decision is not None:
        return llm_decision
    return ResolverDecision(
        action="pass_through",
        resolved_question=q,
        rationale="fallback pass-through for safety",
    )


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
_CLAIM_REF_RE = re.compile(r"\b(that|this|same)\s+claim\b", re.IGNORECASE)
_POLICY_REF_RE = re.compile(r"\b(that|this|same)\s+policy\b", re.IGNORECASE)
_PERSON_REF_RE = re.compile(
    r"\b(that|this|same)\s+(person|insured|agent|customer|member)\b",
    re.IGNORECASE,
)
_SAME_ONE_RE = re.compile(
    r"\b(the\s+)?same\s+(one|person|claim|policy|insured|policyholder)\b",
    re.IGNORECASE,
)
_FOLLOWUP_START_RE = re.compile(r"^\s*(and|also|what about|how about|then|now)\b", re.IGNORECASE)

# Pronouns and anaphora — must not reach the planner unresolved when session has no referent.
_PRONOUN_RE = re.compile(
    r"\b(he|him|his|she|her|hers|they|them|their)\b",
    re.IGNORECASE,
)
_WEAK_ANAPHORA_RE = re.compile(
    r"\b(it|its|this|these|those|above|previous|earlier)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResolverDecision:
    action: str  # pass_through | rewrite | clarify
    resolved_question: str
    clarification_prompt: str = ""
    rationale: str = ""
    used_llm_fallback: bool = False


def _effective_referents(
    digest: MemoryDigest,
    session_overlay: dict[str, str | None] | None,
) -> dict[str, str | None]:
    o = session_overlay or {}
    merged = {
        "primary_person": o.get("primary_person") or digest.active_primary_person,
        "primary_claim": o.get("primary_claim") or digest.active_primary_claim,
        "primary_policy": o.get("primary_policy") or digest.active_primary_policy,
        "graph_focus": o.get("graph_focus") or digest.last_graph_focus,
    }
    try:
        from src.graph_query.query_graph import get_graph
        from src.session.node_id_canonical import canonicalize_referents_dict

        return canonicalize_referents_dict(merged, get_graph())
    except RuntimeError:
        return {k: v for k, v in merged.items() if v}


def _pick_recent_id(digest: MemoryDigest, prefix: str) -> str | None:
    p = prefix.lower()
    for node_id in reversed(digest.recent_focus_node_ids):
        if node_id.lower().startswith(p):
            return node_id
    for node_id in reversed(digest.recent_anchor_ids):
        if node_id.lower().startswith(p):
            return node_id
    return None


def _replace_pronouns_with_person(text: str, person_id: str) -> str:
    """Replace common pronouns with the graph person id (standalone question for the planner)."""
    if not person_id:
        return text
    out = text
    for pat, repl in (
        (r"\bhe\b", person_id),
        (r"\bhim\b", person_id),
        (r"\bhis\b", person_id + "'s"),
        (r"\bshe\b", person_id),
        (r"\bher\b", person_id),
        (r"\bhers\b", person_id),
        (r"\bthey\b", person_id),
        (r"\bthem\b", person_id),
        (r"\btheir\b", person_id + "'s"),
    ):
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out


def _same_one_rewrite(question: str, refs: dict[str, str | None]) -> tuple[str, bool]:
    if not _SAME_ONE_RE.search(question):
        return question, False
    m = _SAME_ONE_RE.search(question)
    if not m:
        return question, False
    span = m.group(0).lower()
    chosen: str | None = None
    if "claim" in span:
        chosen = refs.get("primary_claim")
    elif "policy" in span:
        chosen = refs.get("primary_policy")
    elif "person" in span or "insured" in span or "policyholder" in span or "one" in span:
        chosen = refs.get("primary_person") or refs.get("graph_focus")
    if chosen:
        return _SAME_ONE_RE.sub(chosen, question, count=1), True
    return question, False


def _maybe_rewrite_deterministic(
    question: str,
    digest: MemoryDigest,
    refs: dict[str, str | None],
) -> ResolverDecision | None:
    q = (question or "").strip()
    if not q:
        return ResolverDecision(action="pass_through", resolved_question="", rationale="empty question")
    if digest.turn_count <= 0:
        return ResolverDecision(
            action="pass_through",
            resolved_question=q,
            rationale="no prior session turns",
        )

    rewritten = q
    changed = False

    if _CLAIM_REF_RE.search(rewritten):
        claim_id = refs.get("primary_claim") or _pick_recent_id(digest, "claim|") or _pick_recent_id(digest, "claim_")
        if claim_id:
            rewritten = _CLAIM_REF_RE.sub(claim_id, rewritten)
            changed = True
    if _POLICY_REF_RE.search(rewritten):
        policy_id = (
            refs.get("primary_policy") or _pick_recent_id(digest, "policy|") or _pick_recent_id(digest, "policy_")
        )
        if policy_id:
            rewritten = _POLICY_REF_RE.sub(policy_id, rewritten)
            changed = True
    if _PERSON_REF_RE.search(rewritten):
        person_id = (
            refs.get("primary_person") or _pick_recent_id(digest, "person|") or _pick_recent_id(digest, "person_")
        )
        if person_id:
            rewritten = _PERSON_REF_RE.sub(person_id, rewritten)
            changed = True

    sr, sc = _same_one_rewrite(rewritten, refs)
    if sc:
        rewritten = sr
        changed = True

    if _PRONOUN_RE.search(rewritten):
        person_id = (
            refs.get("primary_person") or _pick_recent_id(digest, "person|") or _pick_recent_id(digest, "person_")
        )
        if person_id:
            new_q = _replace_pronouns_with_person(rewritten, person_id)
            if new_q != rewritten:
                rewritten = new_q
                changed = True

    if changed:
        return ResolverDecision(
            action="rewrite",
            resolved_question=rewritten,
            rationale="deterministic reference rewrite from session referents",
        )

    return None


def _has_hard_contextual_markers(question: str) -> bool:
    q = question or ""
    if _PRONOUN_RE.search(q):
        return True
    if _SAME_ONE_RE.search(q):
        return True
    if _CLAIM_REF_RE.search(q) or _POLICY_REF_RE.search(q) or _PERSON_REF_RE.search(q):
        return True
    if _FOLLOWUP_START_RE.search(q.strip()) and (
        _PRONOUN_RE.search(q) or _WEAK_ANAPHORA_RE.search(q) or _SAME_ONE_RE.search(q)
    ):
        return True
    return False


def _has_weak_contextual_markers(question: str) -> bool:
    return bool(_WEAK_ANAPHORA_RE.search(question or ""))


def _needs_clarification_after_rewrite(question: str, original: str) -> bool:
    """True if contextual anaphora likely still unresolved (guardrail)."""
    if _PRONOUN_RE.search(question):
        return True
    if _SAME_ONE_RE.search(question):
        return True
    if _CLAIM_REF_RE.search(question) or _POLICY_REF_RE.search(question) or _PERSON_REF_RE.search(question):
        return True
    if _has_weak_contextual_markers(question) and _has_weak_contextual_markers(original):
        return True
    return False


def _clarify_unresolved(original: str, *, hint: str) -> ResolverDecision:
    return ResolverDecision(
        action="clarify",
        resolved_question=original,
        clarification_prompt=(
            f"{hint} Please name the graph entity (for example Person|…, Claim|…, Policy|…) "
            "or rephrase with an explicit id so the investigation does not pick the wrong subject."
        ),
        rationale="contextual reference unresolved — blocking planner until clarified",
    )


def _llm_rewrite_enabled() -> bool:
    raw = (os.environ.get("SESSION_MEMORY_LLM_REWRITE") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _rewrite_with_llm(question: str, digest: MemoryDigest, refs: dict[str, str | None]) -> ResolverDecision | None:
    if not _llm_rewrite_enabled():
        return None
    backend = investigation_llm_backend()
    compact_mem = {
        "recent_questions": digest.recent_questions[-3:],
        "recent_focus_node_ids": digest.recent_focus_node_ids[-4:],
        "recent_anchor_ids": digest.recent_anchor_ids[-10:],
        "latest_answer_excerpt": digest.latest_answer_excerpt,
        "active_referents": {k: v for k, v in refs.items() if v},
    }
    system = (
        "You help rewrite short follow-up investigation questions into standalone questions.\n"
        "Session referents are authoritative when provided.\n"
        "Rules:\n"
        "- If pronouns or 'that claim/policy/person' refer to the active referents, rewrite with explicit node ids.\n"
        "- If multiple subjects are plausible, return action clarify (never pass_through with unresolved pronouns).\n"
        "- For brand-new standalone questions with no anaphora, return action pass_through.\n"
        "Return JSON only: action, resolved_question, clarification_prompt, rationale.\n"
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
            clarify = "Which entity from the prior turns should this question apply to?"
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
    *,
    session_referents: dict[str, str | None] | None = None,
) -> ResolverDecision:
    q = (question or "").strip()
    digest = build_memory_digest(turns, last_n=5)
    refs = _effective_referents(digest, session_referents)

    if not q:
        return ResolverDecision(action="pass_through", resolved_question="", rationale="empty question")
    if _HAS_NODE_ID_RE.search(q):
        return ResolverDecision(
            action="pass_through",
            resolved_question=q,
            rationale="question already has explicit node ids",
        )
    if digest.turn_count <= 0:
        return ResolverDecision(
            action="pass_through",
            resolved_question=q,
            rationale="no prior session turns",
        )

    det = _maybe_rewrite_deterministic(q, digest, refs)
    if det is not None:
        if det.action == "rewrite" and _needs_clarification_after_rewrite(det.resolved_question, q):
            return _clarify_unresolved(
                q,
                hint="The question still looks like it depends on an unresolved reference.",
            )
        return det

    hard = _has_hard_contextual_markers(q)
    weak_only = _has_weak_contextual_markers(q) and not hard

    if hard:
        llm_decision = _rewrite_with_llm(q, digest, refs)
        if llm_decision is not None:
            if llm_decision.action == "rewrite" and _needs_clarification_after_rewrite(
                llm_decision.resolved_question, q
            ):
                return _clarify_unresolved(
                    q,
                    hint="Could not confidently map this follow-up to a single prior entity.",
                )
            if llm_decision.action == "pass_through":
                return _clarify_unresolved(
                    q,
                    hint="This follow-up appears contextual but could not be rewritten safely.",
                )
            return llm_decision
        return _clarify_unresolved(
            q,
            hint="This follow-up appears to refer to earlier context, but no safe automatic rewrite is available.",
        )

    if weak_only:
        focus = refs.get("graph_focus")
        if focus and _node_id_shape(focus):
            rewritten = re.sub(
                r"\b(it|this|that)\b",
                focus,
                q,
                count=1,
                flags=re.IGNORECASE,
            )
            if rewritten != q:
                return ResolverDecision(
                    action="rewrite",
                    resolved_question=rewritten,
                    rationale="weak anaphora resolved via last graph focus",
                )
        llm_decision = _rewrite_with_llm(q, digest, refs)
        if llm_decision is not None and llm_decision.action != "pass_through":
            return llm_decision
        if weak_only:
            return _clarify_unresolved(
                q,
                hint="This question may depend on prior context (for example 'it' / 'this').",
            )

    return ResolverDecision(
        action="pass_through",
        resolved_question=q,
        rationale="standalone question; no unresolved contextual markers",
    )


def _node_id_shape(node_id: str) -> bool:
    return bool(_HAS_NODE_ID_RE.search(node_id))

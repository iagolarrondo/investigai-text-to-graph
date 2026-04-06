"""LLM-oriented helpers: prompts (future) and intent router (rules + dispatch)."""

from src.llm.prompts import (
    FEW_SHOT_EXAMPLES,
    SYSTEM_INTENT_ROUTER,
)
from src.llm.router import (
    RouterDecision,
    dispatch_routed_query,
    route_question,
    route_question_llm,
    route_question_rules,
    summary_for_display,
)

__all__ = [
    "FEW_SHOT_EXAMPLES",
    "SYSTEM_INTENT_ROUTER",
    "RouterDecision",
    "dispatch_routed_query",
    "route_question",
    "route_question_llm",
    "route_question_rules",
    "summary_for_display",
]

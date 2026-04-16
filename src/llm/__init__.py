"""LLM helpers: copilot prompts, intent classification, multi-step agent, and dispatch."""

from src.llm.investigation_agent import AgentRunResult, run_investigation_agent
from src.llm.prompts import (
    DOMAIN_DOCS,
    FEW_SHOT_ANSWER_EXAMPLES,
    FEW_SHOT_INTENT_EXAMPLES,
    QUERY_TEMPLATE_CONTEXT,
    SYSTEM_AGENTIC_SYNTHESIS,
    SYSTEM_COPILOT_ANSWER,
    SYSTEM_COVERAGE_JUDGE,
    SYSTEM_INTENT_ROUTER,
    SYSTEM_TOOL_AGENT,
)
from src.llm.result_serialize import payload_to_text
from src.llm.tool_agent import ToolAgentResult, run_tool_planner_agent
from src.llm.router import (
    DEFAULT_CLAIM_NODE_ID,
    RouterDecision,
    claim_anchor_is_valid,
    dispatch_routed_query,
    extract_claim_node_id,
    route_question,
    route_question_auto,
    route_question_llm,
    route_question_rules,
    summary_for_display,
)

__all__ = [
    "AgentRunResult",
    "DEFAULT_CLAIM_NODE_ID",
    "DOMAIN_DOCS",
    "FEW_SHOT_ANSWER_EXAMPLES",
    "FEW_SHOT_INTENT_EXAMPLES",
    "QUERY_TEMPLATE_CONTEXT",
    "SYSTEM_AGENTIC_SYNTHESIS",
    "SYSTEM_COPILOT_ANSWER",
    "SYSTEM_COVERAGE_JUDGE",
    "SYSTEM_INTENT_ROUTER",
    "SYSTEM_TOOL_AGENT",
    "ToolAgentResult",
    "RouterDecision",
    "claim_anchor_is_valid",
    "dispatch_routed_query",
    "extract_claim_node_id",
    "payload_to_text",
    "route_question",
    "route_question_auto",
    "route_question_llm",
    "route_question_rules",
    "run_investigation_agent",
    "run_tool_planner_agent",
    "summary_for_display",
]

import os

from src.llm import orchestration as orch


def test_merge_judge_synthesis_env_default_on():
    os.environ.pop("INVESTIGATION_MERGE_JUDGE_SYNTHESIS", None)
    try:
        assert orch._merge_judge_synthesis_enabled() is True
    finally:
        os.environ.pop("INVESTIGATION_MERGE_JUDGE_SYNTHESIS", None)


def test_merge_judge_synthesis_env_off():
    os.environ["INVESTIGATION_MERGE_JUDGE_SYNTHESIS"] = "0"
    try:
        assert orch._merge_judge_synthesis_enabled() is False
    finally:
        os.environ.pop("INVESTIGATION_MERGE_JUDGE_SYNTHESIS", None)


def test_synth_payload_from_merged_requires_nonempty_answer():
    assert orch._synth_payload_from_merged_judgment({"answer": ""}) is None
    assert orch._synth_payload_from_merged_judgment({"answer": "   "}) is None
    p = orch._synth_payload_from_merged_judgment(
        {
            "answer": "### Key findings\n- x\n\n### Conclusion\ny.",
            "graph_focus_node_id": "Person|1",
            "graph_focus_rationale": "anchor",
        }
    )
    assert p is not None
    assert "### Key findings" in p["answer"]
    assert p["graph_focus_node_id"] == "Person|1"
    assert p["rationale"] == "anchor"


def test_coverage_rationale_prefers_explicit_key():
    j = {"coverage_rationale": "cov", "rationale": "legacy"}
    assert orch._coverage_rationale_from_judgment(j) == "cov"
    assert orch._coverage_rationale_from_judgment({"rationale": "legacy"}) == "legacy"


def test_max_total_tool_steps_default():
    os.environ.pop("INVESTIGATION_MAX_TOOL_STEPS", None)
    try:
        assert orch._max_total_tool_steps() == 30
    finally:
        os.environ.pop("INVESTIGATION_MAX_TOOL_STEPS", None)

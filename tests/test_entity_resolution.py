from src.app.entity_resolution import (
    Candidate,
    fallback_mentions,
    format_candidate_option,
    locate_mention_span,
    question_already_has_node_ids,
    rewrite_question,
)


def test_format_candidate_option_includes_node_id():
    c = Candidate(
        node_id="Address|9005",
        node_type="Address",
        label="Quincy, MA",
        match_reason="label",
    )
    s = format_candidate_option(c)
    assert "Address" in s
    assert "Quincy, MA" in s
    assert "Address|9005" in s


def test_rewrite_question_replaces_mentions_longest_first():
    q = "Check Quincy, MA vs Quincy."
    out = rewrite_question(q, {"Quincy, MA": "Address|9005", "Quincy": "Address|9999"})
    assert out == "Check Address|9005 vs Address|9999."


def test_question_already_has_node_ids_pipe_or_slug():
    assert question_already_has_node_ids("Look up Person|1004") is True
    assert question_already_has_node_ids("2 hops around claim_C9000000122") is True
    assert question_already_has_node_ids("Quincy, MA") is False


def test_locate_mention_span_case_and_punct_insensitive():
    q = "Check Quincy, MA for shared accounts."
    assert locate_mention_span(q, "quincy, ma") == (6, 16)
    # loose punctuation match
    assert locate_mention_span(q, "Quincy MA") == (6, 16)


def test_fallback_mentions_detects_city_state_and_person_name():
    q = "Who is related to Emma Webb in Quincy, MA?"
    ms = fallback_mentions(q)
    mentions = {m["mention"]: m["node_type_hint"] for m in ms}
    assert mentions.get("Emma Webb") == "Person"
    assert mentions.get("Quincy, MA") == "Address"


def test_mention_extractor_json_array_parsing():
    # Ensure the parsing approach used by the mention extractor works for JSON arrays.
    import json
    from src.llm.json_extract import strip_json_fence

    raw = '[{"mention":"Quincy, MA","node_type_hint":"Address"},{"mention":"Ava Park","node_type_hint":"Person"}]'
    data = json.loads(strip_json_fence(raw))
    assert isinstance(data, list)
    assert data[0]["mention"] == "Quincy, MA"


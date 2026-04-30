"""Generate the InvestigAI architecture PDF.

Run:  .venv/bin/python docs/build_architecture_pdf.py
Output: docs/investigai_architecture.pdf
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_JUSTIFY
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    KeepTogether,
)


OUTPUT = Path(__file__).resolve().parent / "investigai_architecture.pdf"


# ---- Styles --------------------------------------------------------------

base = getSampleStyleSheet()

TITLE = ParagraphStyle(
    "Title",
    parent=base["Title"],
    fontName="Helvetica-Bold",
    fontSize=22,
    leading=26,
    spaceAfter=6,
    textColor=colors.HexColor("#0F172A"),
)
SUBTITLE = ParagraphStyle(
    "Subtitle",
    parent=base["Normal"],
    fontName="Helvetica",
    fontSize=11,
    leading=14,
    spaceAfter=18,
    textColor=colors.HexColor("#475569"),
)
H1 = ParagraphStyle(
    "H1",
    parent=base["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=15,
    leading=19,
    spaceBefore=14,
    spaceAfter=6,
    textColor=colors.HexColor("#0F172A"),
)
H2 = ParagraphStyle(
    "H2",
    parent=base["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=12,
    leading=16,
    spaceBefore=10,
    spaceAfter=4,
    textColor=colors.HexColor("#1E293B"),
)
BODY = ParagraphStyle(
    "Body",
    parent=base["BodyText"],
    fontName="Helvetica",
    fontSize=10,
    leading=14,
    spaceAfter=6,
    alignment=TA_JUSTIFY,
    textColor=colors.HexColor("#0F172A"),
)
BULLET = ParagraphStyle(
    "Bullet",
    parent=BODY,
    leftIndent=14,
    bulletIndent=2,
    spaceAfter=2,
    alignment=TA_LEFT,
)
CODE = ParagraphStyle(
    "Code",
    parent=base["Code"],
    fontName="Courier",
    fontSize=8.5,
    leading=11,
    leftIndent=8,
    rightIndent=8,
    spaceBefore=4,
    spaceAfter=8,
    textColor=colors.HexColor("#0F172A"),
    backColor=colors.HexColor("#F1F5F9"),
    borderPadding=6,
)
CAPTION = ParagraphStyle(
    "Caption",
    parent=BODY,
    fontSize=9,
    textColor=colors.HexColor("#64748B"),
    alignment=TA_LEFT,
    spaceAfter=10,
)


# ---- Page template -------------------------------------------------------

def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#94A3B8"))
    canvas.drawString(0.75 * inch, 0.5 * inch, "InvestigAI — Architecture")
    canvas.drawRightString(
        LETTER[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}"
    )
    canvas.restoreState()


def _build_doc():
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="InvestigAI Architecture",
        author="InvestigAI Project",
    )
    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="frame",
    )
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_on_page)])
    return doc


# ---- Helpers -------------------------------------------------------------

def p(text: str, style=BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str]) -> list:
    return [Paragraph(f"&bull;&nbsp; {item}", BULLET) for item in items]


def code(text: str) -> Preformatted:
    return Preformatted(text, CODE)


def section_table(rows: list[list[str]], col_widths) -> Table:
    body_font = ("FONT", (0, 1), (-1, -1), "Helvetica", 9)
    head_font = ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9)
    style = TableStyle([
        head_font,
        body_font,
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E2E8F0")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
    ])
    wrapped = [[Paragraph(c, BODY) for c in row] for row in rows]
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    t.setStyle(style)
    return t


# ---- Story ---------------------------------------------------------------

def build_story() -> list:
    s: list = []

    # Title
    s.append(p("InvestigAI Architecture", TITLE))
    s.append(p(
        "An LTC fraud-investigation copilot built on a deterministic graph layer with "
        "an LLM tool-planner, a coverage judge, and a runtime Python tool authoring pipeline.",
        SUBTITLE,
    ))

    # Section 1
    s.append(p("1. System overview", H1))
    s.append(p(
        "InvestigAI answers free-form investigator questions over a property graph of people, "
        "policies, claims, banks, addresses, and businesses. The graph lives in memory as a "
        "NetworkX <font face='Courier'>DiGraph</font> loaded from two CSV files in "
        "<font face='Courier'>data/processed/</font>. All graph traversal is deterministic Python "
        "code; the LLM only chooses which functions to call and writes the final prose.",
    ))
    s.append(p(
        "The Streamlit UI in <font face='Courier'>src/app/app.py</font> kicks off an orchestrator "
        "(<font face='Courier'>src/llm/orchestration.py</font>) that walks the question through five "
        "stages: <b>preflight</b>, <b>optional extension authoring</b>, <b>tool-calling planner</b>, "
        "<b>coverage judge</b>, and <b>synthesis</b>. The judge can loop the planner; the synthesis step "
        "produces the only user-visible answer plus a focus node for the summary graph view.",
    ))

    s.append(p("End-to-end flow", H2))
    s.append(code(
        "User question (Streamlit)\n"
        "      |\n"
        "      v\n"
        "[1] Preflight LLM\n"
        "      classifies catalog: sufficient | insufficient | sufficient_but_inefficient\n"
        "      |\n"
        "      v\n"
        "[2] Extension authoring  (only if not 'sufficient' AND env flag enabled)\n"
        "      LLM writes a new Python tool, validated + smoke-tested, registered\n"
        "      |\n"
        "      v\n"
        "[3] Planner phase           --- repeats N tool rounds ---\n"
        "      LLM picks tools from GRAPH_TOOLS; deterministic graph code runs them\n"
        "      |\n"
        "      v\n"
        "[4] Coverage judge\n"
        "      reads the FULL trace, decides satisfied/not\n"
        "      not satisfied -> appends feedback, loops back to [3]\n"
        "      |\n"
        "      v\n"
        "[5] Synthesis\n"
        "      writes markdown answer + picks graph_focus_node_id\n"
        "      |\n"
        "      v\n"
        "Streamlit renders: tool trace + reviewer rounds + answer + investigation graph"
    ))

    s.append(p("Key files", H2))
    s.append(section_table(
        [
            ["Stage", "File", "Entry function"],
            ["UI",            "src/app/app.py",                          "main() ~L162"],
            ["Orchestrator",  "src/llm/orchestration.py",                "run_investigation_orchestrator() ~L233"],
            ["Preflight",     "src/llm/tool_preflight.py",               "run_tool_preflight() ~L29"],
            ["Extension author", "src/llm/extension_author.py",          "try_author_extension() ~L170"],
            ["Tool planner",  "src/llm/tool_agent.py",                   "run_tool_planner_agent() ~L657"],
            ["Tool dispatch", "src/llm/tool_agent.py",                   "execute_graph_tool() ~L507"],
            ["Graph queries", "src/graph_query/query_graph.py",          "load_graph(), get_*() helpers"],
            ["Extension loader", "src/graph_query/extension_loader.py",  "active_extension_specs(), load_extension_handlers()"],
        ],
        col_widths=[1.1 * inch, 2.7 * inch, 2.95 * inch],
    ))

    s.append(PageBreak())

    # Section 2
    s.append(p("2. The deterministic graph layer", H1))
    s.append(p(
        "Every answer is grounded in a NetworkX directed graph built from "
        "<font face='Courier'>nodes.csv</font> and <font face='Courier'>edges.csv</font>. Two CSV "
        "schemas are supported (a builder format and a Neo4j export format). Once loaded, nodes carry "
        "<font face='Courier'>node_type</font>, <font face='Courier'>label</font>, and a "
        "<font face='Courier'>properties_json</font> blob; edges carry "
        "<font face='Courier'>edge_type</font> and similar metadata.",
    ))
    s.append(p(
        "The query layer in <font face='Courier'>src/graph_query/query_graph.py</font> exposes a "
        "library of read-only functions: counts and summaries, fuzzy node search, neighbor lookup, "
        "policy/claim/person centric slices, N-hop subgraphs, and global pattern detectors "
        "(shared bank accounts, person clusters, business co-location). Crucially, "
        "<font face='Courier'>get_graph_relationship_catalog()</font> introspects the loaded data and "
        "lists every "
        "<font face='Courier'>(from_type, edge_type, to_type)</font> triple with counts &mdash; this is "
        "what lets the planner discover the schema at runtime without code changes.",
    ))

    s.append(p("3. The tool catalog", H1))
    s.append(p(
        "Tools are JSON Schema dicts registered in <font face='Courier'>_CORE_GRAPH_TOOLS</font> "
        "(<font face='Courier'>src/llm/tool_agent.py</font>). Each entry has a name, a description, "
        "and an input schema &mdash; the same shape Anthropic, Gemini, and Ollama all accept for "
        "function-calling.",
    ))
    s.append(code(
        '{\n'
        '    "name": "get_graph_relationship_catalog",\n'
        '    "description": "Future-proof schema introspection: lists every directed triple ...",\n'
        '    "input_schema": {\n'
        '        "type": "object",\n'
        '        "properties": {},\n'
        '        "required": []\n'
        '    }\n'
        '}'
    ))
    s.append(p(
        "At dispatch time, <font face='Courier'>execute_graph_tool(name, tool_input)</font> routes the "
        "call. Core tools go through an <font face='Courier'>if/elif</font> chain into "
        "<font face='Courier'>query_graph.*</font>. Extension tools are looked up in a runtime "
        "<font face='Courier'>_EXTENSION_HANDLERS</font> dict that maps "
        "<font face='Courier'>tool_name &rarr; run(dict) -&gt; str</font>.",
    ))

    s.append(PageBreak())

    # Section 3 -- THE BIG ONE
    s.append(p("4. Dynamic Python tool authoring (the core innovation)", H1))
    s.append(p(
        "When a question doesn&rsquo;t fit any existing tool, the system can <b>write a new Python "
        "function on the fly</b>, validate it, persist it, smoke-test it, and immediately make it "
        "available to the planner. This is the &ldquo;dynamic Python function written against the "
        "query&rdquo; behaviour. It lives in "
        "<font face='Courier'>src/llm/extension_author.py</font> and "
        "<font face='Courier'>src/graph_query/extension_loader.py</font>, and is gated by the "
        "environment flag <font face='Courier'>INVESTIGATION_EXTENSION_AUTHORING=1</font>.",
    ))

    s.append(p("4.1 When does the system decide to author?", H2))
    s.append(p(
        "Before the planner runs, a <b>preflight LLM</b> is given the user question and the current "
        "tool catalog (just names + descriptions). It returns a small JSON:",
    ))
    s.append(code(
        '{\n'
        '  "decision": "sufficient" | "insufficient" | "sufficient_but_inefficient",\n'
        '  "rationale": "...",\n'
        '  "gap_summary": "...",\n'
        '  "efficiency_note": "...",\n'
        '  "recommended_plan": "..."\n'
        '}'
    ))
    s.append(p(
        "If <font face='Courier'>decision</font> is <font face='Courier'>insufficient</font> or "
        "<font face='Courier'>sufficient_but_inefficient</font>, and the env flag is on, the "
        "orchestrator calls <font face='Courier'>try_author_extension(...)</font>. Otherwise it skips "
        "straight to the planner.",
    ))

    s.append(p("4.2 The authoring pipeline, step by step", H2))
    s.append(code(
        "try_author_extension()\n"
        "  1. Author LLM call\n"
        "       system: SYSTEM_TOOL_EXTENSION_AUTHOR\n"
        "       user:   question + preflight JSON + current tool catalog\n"
        "       output: { tool_name, description, input_schema, function_body }\n"
        "\n"
        "  2. Static validation\n"
        "       - tool_name: alphanumeric+underscore, not a reserved core name\n"
        "       - description and input_schema present\n"
        "       - function_body non-empty\n"
        "\n"
        "  3. Code generation\n"
        "       wrap body in _MODULE_TEMPLATE -> full module source\n"
        "\n"
        "  4. AST safety check  (_validate_extension_source)\n"
        "       - allowed imports only:\n"
        "           json, typing, collections, itertools, math, re,\n"
        "           functools, operator, datetime, decimal,\n"
        "           src.graph_query.query_graph\n"
        "       - forbidden calls:\n"
        "           eval, exec, open, compile, __import__, breakpoint, input\n"
        "       - blocks both bare names and attribute access (e.g. __builtins__.eval)\n"
        "\n"
        "  5. Write file\n"
        "       src/graph_query/generated/<tool_name>.py\n"
        "       compile(source) catches syntax errors before persistence\n"
        "\n"
        "  6. Update registry\n"
        "       append entry to src/graph_query/extension_registry.json\n"
        "       { name, module, description, input_schema, active: true, created_at }\n"
        "\n"
        "  7. Smoke gate  (subprocess, 120s timeout)\n"
        "       pytest tests/test_graph_extensions_smoke.py -q --tb=no\n"
        "       failure -> revert registry, delete file, return error\n"
        "\n"
        "  8. Hot-reload catalog\n"
        "       refresh_graph_tools_with_extensions() reloads handlers\n"
        "       -> tool is callable for the rest of THIS run and all future runs"
    ))

    s.append(p("4.3 The module template", H2))
    s.append(p(
        "The LLM does not get free rein over the file. It only writes the indented "
        "<font face='Courier'>{body}</font>; the module skeleton is fixed:",
    ))
    s.append(code(
        '"""Auto-generated graph tool extension (registry)."""\n'
        'from __future__ import annotations\n'
        '\n'
        'import json\n'
        'from typing import Any\n'
        '\n'
        'from src.graph_query.query_graph import get_graph\n'
        '\n'
        '\n'
        'def run(tool_input: dict[str, Any]) -> str:\n'
        '    """Registry entrypoint; return JSON or plain text for the planner."""\n'
        '{body}'
    ))
    s.append(p(
        "Every generated tool exposes a single <font face='Courier'>run(tool_input)</font> entrypoint "
        "that takes a dict (matching the LLM&rsquo;s declared "
        "<font face='Courier'>input_schema</font>) and returns a string the planner can read. The "
        "module can call <font face='Courier'>get_graph()</font> to get the live NetworkX object but "
        "cannot mutate it &mdash; the graph layer is read-only.",
    ))

    s.append(PageBreak())

    s.append(p("4.4 What the registry looks like", H2))
    s.append(code(
        '[\n'
        '  {\n'
        '    "name": "claims_agent_insured_shared_bank",\n'
        '    "module": "claims_agent_insured_shared_bank",\n'
        '    "description": "For every Claim in the graph, finds whether the writing\n'
        '                    agent and any insured share a bank account.",\n'
        '    "input_schema": { "type": "object", "properties": {}, "required": [] },\n'
        '    "active": true,\n'
        '    "created_at": "2026-04-22T01:39:05.088873+00:00"\n'
        '  }\n'
        ']'
    ))
    s.append(p(
        "<font face='Courier'>extension_loader.active_extension_specs()</font> returns the "
        "planner-facing dicts (name, description, input_schema). "
        "<font face='Courier'>load_extension_handlers()</font> imports each "
        "<font face='Courier'>src.graph_query.generated.&lt;module&gt;</font> dynamically and grabs "
        "its <font face='Courier'>run</font> attribute. Both are called by "
        "<font face='Courier'>refresh_graph_tools_with_extensions()</font> in "
        "<font face='Courier'>tool_agent.py</font>.",
    ))

    s.append(p("4.5 Why this design works", H2))
    s.extend(bullets([
        "<b>Bounded surface area.</b> The LLM writes only the body of one function with a fixed "
        "signature; everything else &mdash; imports, entrypoint, registry shape &mdash; is locked.",
        "<b>Static + runtime gates.</b> AST parsing blocks unsafe imports and dangerous builtins; "
        "<font face='Courier'>compile()</font> rejects syntactic garbage; pytest verifies the module "
        "actually imports and runs before it goes live.",
        "<b>Atomic activation.</b> If any gate fails the registry entry is removed and the file is "
        "deleted, leaving the catalog exactly as it was.",
        "<b>Determinism preserved.</b> Generated tools can read the graph but never invent edges or "
        "mutate state, so the answer is still reproducible from the CSVs.",
        "<b>Persistence with version control.</b> Activated tools live as real files on disk that "
        "can be code-reviewed and committed &mdash; not buried in an opaque vector store.",
    ]))

    s.append(p("4.6 Safety boundary &mdash; what this is and isn&rsquo;t", H2))
    s.append(p(
        "AST-based validation is a strong filter for accidental misuse and obvious malicious patterns "
        "but it is <b>not</b> a sandbox in the strict sense; a sufficiently determined adversary with "
        "control of the LLM output could probably craft something that slips past. Production "
        "deployments would want process isolation (subprocess with seccomp / a container) on top of "
        "the existing checks. For the PoC, the smoke gate plus the read-only graph layer is the line "
        "of defence.",
    ))

    s.append(PageBreak())

    # Section 5
    s.append(p("5. The coverage judge loop", H1))
    s.append(p(
        "After each planner phase the judge LLM gets the user question and the <b>full, untruncated</b> "
        "tool trace. It returns a JSON verdict:",
    ))
    s.append(code(
        '{\n'
        '  "satisfied": true | false,\n'
        '  "missing_aspects": ["..."],\n'
        '  "rationale": "short sentence",\n'
        '  "feedback_for_planner": "what to query next, or null"\n'
        '}'
    ))
    s.append(p(
        "If <font face='Courier'>satisfied</font> is true, the loop exits to synthesis. Otherwise "
        "<font face='Courier'>feedback_for_planner</font> is appended to the planner&rsquo;s state and "
        "another planner phase runs. Two safeguards bound the loop: "
        "<font face='Courier'>INVESTIGATION_MAX_PLANNER_PHASES</font> (default unlimited; set to 2&ndash;4 "
        "to control hosted-LLM cost) and <font face='Courier'>INVESTIGATION_MAX_TOOL_STEPS</font> (default 20).",
    ))
    s.append(p(
        "An important rule in the prompt: if a tool authoritatively says &ldquo;not found&rdquo; "
        "(missing node id, empty cluster because the anchor doesn&rsquo;t exist, etc.), the judge "
        "treats that as fully covering the lookup so synthesis can state the negative result instead "
        "of looping forever.",
    ))
    s.append(p(
        "When <font face='Courier'>INVESTIGATION_MERGE_JUDGE_SYNTHESIS=1</font> (the default) and the "
        "judge is satisfied, it can return the final answer in the same JSON, skipping the separate "
        "synthesis call &mdash; one fewer paid LLM round-trip per investigation.",
    ))

    s.append(p("6. Synthesis &mdash; the only user-visible prose", H1))
    s.append(p(
        "Synthesis runs once at the end (or is folded into the judge step in merged mode). It is the "
        "<b>only</b> place that produces narrative for the investigator. The prompt enforces a strict "
        "shape:",
    ))
    s.append(code(
        "[Optional opening paragraph: 0-3 sentences]\n"
        "\n"
        "### Key findings\n"
        "- bullet 1\n"
        "- bullet 2\n"
        "- ...\n"
        "\n"
        "### Conclusion\n"
        "1-2 synthesis sentences on review priority or what remains unknown."
    ))
    s.append(p(
        "It also picks a <font face='Courier'>graph_focus_node_id</font> (preferring typed ids like "
        "<font face='Courier'>Person|1004</font> or <font face='Courier'>Claim|C001</font> seen in the "
        "trace). The Streamlit UI uses that id to centre an N-hop pyvis visualization beneath the "
        "answer. If synthesis omits it, a regex heuristic over the trace picks the first plausible id.",
    ))

    s.append(p("7. Backends and cost knobs", H1))
    s.append(p(
        "The same orchestrator runs against three LLM backends, selected by "
        "<font face='Courier'>INVESTIGATION_LLM</font>: <b>Gemini</b> (default, "
        "<font face='Courier'>gemini-2.5-flash</font>), <b>Anthropic Claude</b> "
        "(<font face='Courier'>claude-sonnet-4-6</font>), and local <b>Ollama</b> (any tool-capable model "
        "such as <font face='Courier'>llama3.1</font>). Hosted backends use the full prompts in "
        "<font face='Courier'>src/llm/prompts.py</font>; Ollama uses compact variants and "
        "<font face='Courier'>format=json</font> with a plain-text fallback if the model emits an "
        "empty answer.",
    ))
    s.append(section_table(
        [
            ["Variable", "Default", "Effect"],
            ["INVESTIGATION_LLM",                  "gemini",      "Backend: gemini | anthropic | ollama"],
            ["INVESTIGATION_PLANNER_MAX_ROUNDS",   "14 / 12",     "Tool rounds per planner phase"],
            ["INVESTIGATION_MAX_PLANNER_PHASES",   "unlimited",   "Outer planner-judge cycles"],
            ["INVESTIGATION_MAX_TOOL_STEPS",       "20",          "Hard cap on recorded tool calls"],
            ["INVESTIGATION_MERGE_JUDGE_SYNTHESIS","1",           "Judge returns answer when satisfied"],
            ["INVESTIGATION_EXTENSION_AUTHORING",  "0",           "Allow LLM to write new tools"],
            ["OLLAMA_TIMEOUT",                     "600",         "Per-request HTTP timeout (seconds)"],
            ["OLLAMA_MAX_TRACE_CHARS",             "28000",       "Trace truncation for judge/synth"],
        ],
        col_widths=[2.4 * inch, 1.0 * inch, 3.35 * inch],
    ))

    s.append(p("8. What this design buys you", H1))
    s.extend(bullets([
        "<b>Auditability.</b> Every numeric claim in the answer maps back to a deterministic graph "
        "function call; the LLM cannot fabricate edges.",
        "<b>Adaptability.</b> The catalog grows itself when questions outrun the static tools, with "
        "validation gates instead of human deploys.",
        "<b>Cost control.</b> Phase caps, tool-call caps, and the merged judge/synthesis path each "
        "trim hosted LLM spend independently.",
        "<b>Portability.</b> Same orchestration runs against three backends; same tool schema works "
        "for Anthropic, Gemini, and Ollama.",
        "<b>Schema agnosticism.</b> The relationship-catalog tool means new node/edge types appear "
        "in the LLM&rsquo;s view as soon as they appear in the CSVs &mdash; no Python change required.",
    ]))

    return s


def main() -> None:
    doc = _build_doc()
    doc.build(build_story())
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()

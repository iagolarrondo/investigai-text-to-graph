"""Generate the InvestigAI extended-schema architecture PDF.

Run:    .venv/bin/python docs/build_extended_schema_pdf.py
Output: docs/extended_graph_schema.pdf

Companion file:  docs/extended_graph_schema.yaml  (machine-readable schema)
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


OUTPUT = Path(__file__).resolve().parent / "extended_graph_schema.pdf"


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


# ---- Page template -------------------------------------------------------

def _on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#94A3B8"))
    canvas.drawString(0.75 * inch, 0.5 * inch, "InvestigAI - Extended Graph Schema")
    canvas.drawRightString(LETTER[0] - 0.75 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()


def _build_doc():
    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title="InvestigAI Extended Graph Schema",
        author="InvestigAI Project",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="frame")
    doc.addPageTemplates([PageTemplate(id="main", frames=frame, onPage=_on_page)])
    return doc


# ---- Helpers -------------------------------------------------------------

def p(text: str, style=BODY) -> Paragraph:
    return Paragraph(text, style)


def bullets(items: list[str]) -> list:
    return [Paragraph(f"&bull;&nbsp; {item}", BULLET) for item in items]


def code(text: str) -> Preformatted:
    return Preformatted(text, CODE)


def table(rows, col_widths, body_size=8.5, header_bg="#E2E8F0"):
    body_style = ParagraphStyle(
        "tblBody",
        parent=BODY,
        fontSize=body_size,
        leading=body_size + 2.5,
        spaceAfter=0,
        alignment=TA_LEFT,
    )
    head_style = ParagraphStyle(
        "tblHead",
        parent=body_style,
        fontName="Helvetica-Bold",
    )
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
    ])
    wrapped = []
    for i, row in enumerate(rows):
        s = head_style if i == 0 else body_style
        wrapped.append([Paragraph(str(c), s) for c in row])
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    t.setStyle(style)
    return t


# ---- Story ---------------------------------------------------------------

def build_story() -> list:
    s: list = []

    # ------- Title --------------------------------------------------------
    s.append(p("InvestigAI: Extended Graph Schema", TITLE))
    s.append(p(
        "A layered schema proposal that extends the current policy-administration core with "
        "care-operations, clinical, financial, and workflow data so the graph can answer all 50 "
        "questions in <font face='Courier'>eval/investigator_question_set.md</font>. Companion "
        "machine-readable spec at <font face='Courier'>docs/extended_graph_schema.yaml</font>.",
        SUBTITLE,
    ))

    # ------- 1. Why ------------------------------------------------------
    s.append(p("1. Why extend the schema", H1))
    s.append(p(
        "The current graph (1,016 nodes, 1,770 edges across Person, Policy, Claim, BankAccount, "
        "Address, Business) is a strong policy-administration core but only covers ~6 of the 50 "
        "investigator questions. Sections 3 (Providers), 4 (Caregiver sessions), 5 (Clinical), "
        "6 (Billing), 7 (Review cycles), and most of 8 (Graph-native) are blocked by missing "
        "entity types &mdash; not by tooling or query logic. The extension below adds 13 new node "
        "types and 20 new / refined edges, organized in four optional layers that can be rolled "
        "out independently.",
    ))

    # ------- 2. Comprehensive end-state ---------------------------------
    s.append(p("2. The comprehensive graph (end-state)", H1))
    s.append(p(
        "If every layer in this proposal is implemented, the graph grows from 6 node types and "
        "8 edge types to <b>19 node types, 27 edge types, and 30 distinct relationship triples</b>. "
        "The diagram below is the full topology &mdash; existing types in the bottom box, new types "
        "stacked above. Every arrow is a real edge type the planner can traverse.",
    ))
    s.append(code(
        "+----------------+     TRIGGERED       +-------------+   HAS_REMEDIATION   +-------------+\n"
        "| TriggerMetric  +-------------------->+ ReviewCycle +-------------------->+ Remediation |\n"
        "+----------------+                     +------+------+                     +-------------+\n"
        "                                              ^ HAS_REVIEW_CYCLE\n"
        "                                              |\n"
        "+---------+  HAS_CHARGE  +---------+   BILLED_ON     +-------+\n"
        "| Invoice +------------->| Charge  |    +----------> | Claim |<-------------+\n"
        "+----+----+              +---------+    |            +---+---+              | HAS_DIAGNOSIS\n"
        "     ^ SETTLES_INVOICE                  |                |                  | RECEIVES_ADL\n"
        "     |                                  |                | IS_CLAIM_AGAINST_POLICY\n"
        "+----+----+    PAID_TO    +-----------+ |                v                  v\n"
        "| Payment +-------------> | Person /  | |          +---------+        +-----------+\n"
        "+----+----+    PAID_VIA   | Business  | |  HAS_RIDER|         |        |Diagnosis  |\n"
        "     |        +---------> +-----------+ |  HAS_BENE | Policy  |        |Assessment |\n"
        "     |        |                         |     +----->         |        |ADL        |\n"
        "     v        |                         |     |    +----+----+        +-----------+\n"
        "+-----------+ |  PROVIDES_CARE_ON       |     |         ^ IS_COVERED_BY\n"
        "|BankAccount| |  +----------------------+     |         | SOLD_POLICY\n"
        "+-----+-----+ |  |                            |    +----+----+    IS_SPOUSE_OF\n"
        "      ^ HOLD_BY  v                            |    |         |    IS_POA_FOR\n"
        "      |     +----+----+   LOGGED_SESSION  +---+    | Person  +-+ IS_HIPAA_AUTH_FOR\n"
        "      +-----+ Person  +------------------>+ Care   +---------+ | IS_FAMILY_MEMBER_OF\n"
        "            |  (ICP)  | <--SESSION_FOR_CLAIM Session              |\n"
        "            +----+----+                   +---+---+                v\n"
        "                 | EMPLOYED_BY                | USED_DEVICE       LOCATED_IN\n"
        "                 v                            v                       |\n"
        "            +---------+   IS_AGENCY_FOR   +--------+               +--+----+\n"
        "            |Business +------------------>| Device |               |Address|\n"
        "            +---------+                   +--------+               +-------+\n"
        "                 ^ LOCATED_IN\n"
        "                 (existing edges shown without source-line decoration)"
    ))
    s.append(p(
        "The diagram is dense by design &mdash; every fraud-investigation question in the eval set "
        "lives somewhere on this map. <i>get_graph_relationship_catalog()</i> would list all 30 "
        "(from, edge, to) triples shown in section 3 below.",
        ParagraphStyle("Caption", parent=BODY, fontSize=9, textColor=colors.HexColor("#64748B")),
    ))

    s.append(PageBreak())

    # ------- 2b. Complete node and edge inventory -----------------------
    s.append(p("3. Complete node-type inventory", H1))
    s.append(p(
        "All 19 node types after rollout, flattened across layers. Status column tags whether "
        "the type exists today, exists today with new properties, or is brand-new.",
    ))
    s.append(table(
        [
            ["Node type",    "Layer",            "Status",          "Role"],
            ["Person",       "policy-admin core","existing+",       "Insureds, family, agents, ICPs, POAs, HIPAA authorizees"],
            ["Policy",       "policy-admin core","existing+",       "LTC policy contracts"],
            ["Claim",        "policy-admin core","existing+",       "Open / closed claim instances"],
            ["Address",      "policy-admin core","existing+",       "Geo-coded residential / business locations"],
            ["BankAccount",  "policy-admin core","existing",        "Bank accounts referenced for premium and payment"],
            ["Business",     "policy-admin core","existing+",       "HHCAs, facilities, ICP LLCs, other providers"],
            ["Rider",        "policy-admin core","new",             "Optional benefits attached to a policy"],
            ["Benefit",      "policy-admin core","new",             "DMB / MMB by care setting on a policy"],
            ["Diagnosis",    "clinical",         "new",             "ICD-10 diagnoses on a claim"],
            ["Assessment",   "clinical",         "new",             "MMSE / Barthel / cognitive scores on a person"],
            ["ADL",          "clinical",         "new",             "Activities of Daily Living provided on a claim"],
            ["CareSession",  "care-operations",  "new",             "Per-session caregiver app records (geo, device, mode)"],
            ["Device",       "care-operations",  "new",             "Mobile devices used for session check-in / check-out"],
            ["Invoice",      "financial",        "new",             "Provider invoices billed against a claim"],
            ["Charge",       "financial",        "new",             "Line items inside an invoice"],
            ["Payment",      "financial",        "new",             "Disbursements settling invoices"],
            ["ReviewCycle",  "workflow",         "new",             "Fraud-investigation workflow instances"],
            ["TriggerMetric","workflow",         "new",             "Signals that opened a review cycle"],
            ["Remediation",  "workflow",         "new",             "Post-cycle outcomes and recoveries"],
        ],
        col_widths=[1.05*inch, 1.1*inch, 0.85*inch, 3.75*inch],
        body_size=8.0,
    ))

    s.append(PageBreak())

    s.append(p("4. Complete relationship catalog (every from -> edge -> to triple)", H1))
    s.append(p(
        "This is what <font face='Courier'>get_graph_relationship_catalog()</font> returns at "
        "runtime once the full schema is loaded. The planner can chain any of these triples to "
        "answer multi-hop questions.",
    ))
    s.append(table(
        [
            ["From",            "Edge",                          "To",            "Status"],
            ["Person",          "IS_COVERED_BY",                 "Policy",        "existing"],
            ["Person",          "SOLD_POLICY",                   "Policy",        "existing"],
            ["Claim",           "IS_CLAIM_AGAINST_POLICY",       "Policy",        "existing"],
            ["Person",          "HOLD_BY",                       "BankAccount",   "existing"],
            ["Person",          "LOCATED_IN",                    "Address",       "existing"],
            ["Business",        "LOCATED_IN",                    "Address",       "existing"],
            ["Person",          "IS_SPOUSE_OF",                  "Person",        "existing"],
            ["Person",          "IS_POA_FOR",                    "Person",        "new"],
            ["Person",          "IS_HIPAA_AUTHORIZED_FOR",       "Person",        "new"],
            ["Person",          "IS_FAMILY_MEMBER_OF",           "Person",        "new"],
            ["Person",          "PROVIDES_CARE_ON",              "Claim",         "new"],
            ["Person",          "EMPLOYED_BY",                   "Business",      "new"],
            ["Business",        "IS_AGENCY_FOR",                 "Claim",         "new"],
            ["Person",          "LOGGED_SESSION",                "CareSession",   "new"],
            ["CareSession",     "SESSION_FOR_CLAIM",             "Claim",         "new"],
            ["CareSession",     "USED_DEVICE",                   "Device",        "new"],
            ["Claim",           "HAS_DIAGNOSIS",                 "Diagnosis",     "new"],
            ["Person",          "HAS_ASSESSMENT",                "Assessment",    "new"],
            ["Claim",           "RECEIVES_ADL",                  "ADL",           "new"],
            ["Policy",          "HAS_RIDER",                     "Rider",         "new"],
            ["Policy",          "HAS_BENEFIT",                   "Benefit",       "new"],
            ["Invoice",         "BILLED_ON",                     "Claim",         "new"],
            ["Invoice",         "INVOICED_BY",                   "Person",        "new"],
            ["Invoice",         "INVOICED_BY",                   "Business",      "new"],
            ["Invoice",         "HAS_CHARGE",                    "Charge",        "new"],
            ["Payment",         "SETTLES_INVOICE",               "Invoice",       "new"],
            ["Payment",         "PAID_TO",                       "Person",        "new"],
            ["Payment",         "PAID_TO",                       "Business",      "new"],
            ["Payment",         "PAID_VIA",                      "BankAccount",   "new"],
            ["Claim",           "HAS_REVIEW_CYCLE",              "ReviewCycle",   "new"],
            ["TriggerMetric",   "TRIGGERED",                     "ReviewCycle",   "new"],
            ["ReviewCycle",     "HAS_REMEDIATION",               "Remediation",   "new"],
        ],
        col_widths=[1.4*inch, 2.05*inch, 1.4*inch, 0.85*inch],
        body_size=8.0,
    ))

    s.append(PageBreak())

    # ------- 2c. Scale estimates ---------------------------------------
    s.append(p("5. Scale estimates", H1))
    s.append(p(
        "Anchored on today&rsquo;s &ldquo;large&rdquo; config (~220 claims) plus six months of "
        "operational activity. CareSessions and their device edges dominate; everything else is a "
        "rounding error against them. Visualization tools should switch to a ball-and-summary view "
        "for any anchor with &gt;1k touched edges.",
    ))
    s.append(table(
        [
            ["Snapshot",                                           "Total nodes",   "Total edges"],
            ["Today (large config)",                               "~1,016",        "~1,770"],
            ["After full extension &mdash; small demo (30 claims)","~6,000",        "~18,000"],
            ["After full extension &mdash; large (220 claims, 6mo)","~96,000",      "~283,000"],
        ],
        col_widths=[3.3*inch, 1.7*inch, 1.7*inch],
    ))
    s.append(p("Largest contributors at full scale (large):", H2))
    s.append(table(
        [
            ["Node / edge",                  "Count",   "Driver"],
            ["CareSession (node)",           "~59,000", "220 claims * 3 ICPs * 6 mo * ~15 sessions/mo"],
            ["USED_DEVICE (edge)",           "~118,000","2 events per session (check-in + check-out)"],
            ["LOGGED_SESSION (edge)",        "~59,000", "1 per session"],
            ["SESSION_FOR_CLAIM (edge)",     "~59,000", "1 per session"],
            ["Charge (node)",                "~26,400", "~10 line items per invoice"],
            ["Invoice (node)",               "~2,640",  "~12 monthly invoices per claim"],
            ["Payment (node)",               "~2,640",  "1 settling payment per invoice"],
            ["Diagnosis / Assessment / ADL", "~660 + 440 + 880", "1-5 per claim (each)"],
        ],
        col_widths=[2.3*inch, 1.3*inch, 3.1*inch],
    ))

    s.append(p("6. Sample multi-hop traversals the comprehensive graph enables", H1))
    s.append(p(
        "These are the kinds of paths that today&rsquo;s graph cannot express but that the full "
        "extension makes natural. Each one maps directly to a question or two from the eval set.",
    ))
    s.append(table(
        [
            ["Pattern",                                  "Path",                                                                                                            "Detects"],
            ["Provider paid into family bank (Q47)",     "Claim &mdash; Person(ICP) &mdash; Payment &mdash; BankAccount &mdash; Person &mdash; Person(insured)",            "Provider paid into a bank held by claimant&rsquo;s family member"],
            ["Manual high-charge cluster (Q45)",         "CareSession[Manual] &mdash; Claim &mdash; Invoice &mdash; Charge",                                                "Manual sessions correlated with high hourly_rate / hours_billed"],
            ["Cross-claim ICP saturation (Q39, Q49)",    "Person(ICP) &mdash; Claim_A; Person(ICP) &mdash; Claim_B (and N more)",                                           "Same ICP saturating an unusual share of claims"],
            ["ICP-claimant address collision (Q37)",     "Person(ICP) &mdash; Address &mdash; Person(insured) &mdash; Policy &mdash; Claim",                                "Care provider lives at the policyholder&rsquo;s address"],
            ["Trigger-to-remediation audit (Q34, Q36)",  "TriggerMetric &mdash; ReviewCycle &mdash; Claim; ReviewCycle &mdash; Remediation",                                "Full chain from anomaly to recovery"],
        ],
        col_widths=[2.0*inch, 2.7*inch, 2.0*inch],
        body_size=8.0,
    ))

    s.append(PageBreak())

    # ------- (renumbered) Layered architecture diagram -----------------
    s.append(p("7. Layered architecture (deltas view)", H1))
    s.append(p(
        "The current graph is the bottom layer. Each layer above is a slice of the LTC investigation "
        "world that adds independent value &mdash; Care-operations alone unlocks ~20 questions, "
        "Clinical adds ~5, Financial ~7, Workflow ~4.",
    ))
    s.append(code(
        "                       +-----------------------------------+\n"
        "                       |   Workflow                         |\n"
        "                       |   ReviewCycle  -- TriggerMetric    |\n"
        "                       |       |                            |\n"
        "                       |       +-- Remediation              |\n"
        "                       +----------------+-------------------+\n"
        "                                        | HAS_REVIEW_CYCLE\n"
        "                       +----------------v-------------------+\n"
        "                       |   Financial                        |\n"
        "                       |   Invoice -- Charge                |\n"
        "                       |     |                              |\n"
        "                       |     +- Payment -- BankAccount      |\n"
        "                       +----------------+-------------------+\n"
        "                                        | BILLED_ON / SETTLES_INVOICE\n"
        "                       +----------------v-------------------+\n"
        "                       |   Care-operations                  |\n"
        "                       |   CareSession -- Device            |\n"
        "                       |     |                              |\n"
        "                       |     +- Person(ICP) -- Business     |\n"
        "                       +----------------+-------------------+\n"
        "                                        | SESSION_FOR_CLAIM /\n"
        "                                        | PROVIDES_CARE_ON\n"
        "                       +----------------v-------------------+\n"
        "                       |   Clinical                         |\n"
        "                       |   Diagnosis  Assessment  ADL       |\n"
        "                       +----------------+-------------------+\n"
        "                                        | HAS_DIAGNOSIS / HAS_ASSESSMENT\n"
        "                       +----------------v-------------------+\n"
        "                       |   POLICY-ADMIN CORE  (today)       |\n"
        "                       |   Person -- Policy -- Claim        |\n"
        "                       |   Address  BankAccount  Business   |\n"
        "                       |   + Rider, Benefit (new on Policy) |\n"
        "                       +------------------------------------+"
    ))

    s.append(PageBreak())

    # ------- 3. New node types -------------------------------------------
    s.append(p("8. New node types (per layer)", H1))
    s.append(p(
        "Thirteen new node types organized by layer. Properties are JSON-stringified into "
        "<font face='Courier'>properties_json</font> on each row of "
        "<font face='Courier'>nodes.csv</font>, so no column-level schema migration is needed in "
        "the loader.",
    ))

    s.append(p("Clinical layer", H2))
    s.append(table(
        [
            ["Node",       "Key properties",                                                  "Unlocks"],
            ["Diagnosis",  "icd10_code, description, diagnosis_date, diagnosing_provider_id", "Q25"],
            ["Assessment", "type (MMSE/Barthel), score, max_score, cognitive_impairment_flag","Q23, Q24"],
            ["ADL",        "name (Bathing/Dressing/...), is_provided, frequency_per_day",     "Q26"],
        ],
        col_widths=[1.1*inch, 4.0*inch, 1.65*inch],
    ))

    s.append(p("Care-operations layer", H2))
    s.append(table(
        [
            ["Node",        "Key properties",                                                                    "Unlocks"],
            ["CareSession", "session_date, check_in/out_ts + lat/lon, check_in/out_device_id, submission_mode", "Q16-22, Q41-45, Q49"],
            ["Device",      "device_id, os, model, first_seen_ts, last_seen_ts",                                 "Q19, Q20, Q21, Q43"],
        ],
        col_widths=[1.1*inch, 4.0*inch, 1.65*inch],
    ))

    s.append(p("Policy-benefit additions", H2))
    s.append(table(
        [
            ["Node",    "Key properties",                                              "Unlocks"],
            ["Rider",   "rider_code, rider_name, effective_date, termination_date",   "Q3"],
            ["Benefit", "care_setting (Home/AssistedLiving/Nursing), DMB, MMB, lifetime_max", "Q4"],
        ],
        col_widths=[1.1*inch, 4.0*inch, 1.65*inch],
    ))

    s.append(p("Financial layer", H2))
    s.append(table(
        [
            ["Node",    "Key properties",                                                       "Unlocks"],
            ["Invoice", "claim_id, billing_period_start/end, total_amount, submission_date, status", "Q29, Q30"],
            ["Charge",  "line_item_date, hours_billed, hourly_rate, line_amount, service_code", "Q28, Q29, Q45"],
            ["Payment", "payment_date, amount, payment_method, status",                         "Q30-32, Q47"],
        ],
        col_widths=[1.1*inch, 4.0*inch, 1.65*inch],
    ))

    s.append(p("Workflow layer", H2))
    s.append(table(
        [
            ["Node",          "Key properties",                                                "Unlocks"],
            ["ReviewCycle",   "claim_id, opened_date, closed_date, status, outcome",           "Q33, Q35"],
            ["TriggerMetric", "name (DistanceAnomaly/ManualSessionShare/...), value, threshold","Q34"],
            ["Remediation",   "action_type, recovery_amount, completion_date",                 "Q36"],
        ],
        col_widths=[1.1*inch, 4.0*inch, 1.65*inch],
    ))

    s.append(PageBreak())

    # ------- 4. New / refined edges --------------------------------------
    s.append(p("9. New and refined edge types", H1))
    s.append(p(
        "Today's <font face='Courier'>ACT_ON_BEHALF_OF</font> and "
        "<font face='Courier'>IS_RELATED_TO</font> are too coarse to answer Q6, Q9, Q10, Q38, Q46. "
        "They split into role-specific edges below.",
    ))

    s.append(p("Refined relationship edges", H2))
    s.append(table(
        [
            ["Edge",                       "From -> To",        "Replaces / Refines",        "Unlocks"],
            ["IS_POA_FOR",                 "Person -> Person",  "subset of ACT_ON_BEHALF_OF","Q6, Q10, Q38, Q46"],
            ["IS_HIPAA_AUTHORIZED_FOR",    "Person -> Person",  "(new)",                     "Q9, Q10, Q46"],
            ["IS_FAMILY_MEMBER_OF",        "Person -> Person",  "refines IS_RELATED_TO",     "Q7, Q37, Q38, Q46"],
        ],
        col_widths=[2.1*inch, 1.6*inch, 1.7*inch, 1.35*inch],
    ))

    s.append(p("Care-operations edges", H2))
    s.append(table(
        [
            ["Edge",               "From -> To",                "Properties",                                             "Unlocks"],
            ["PROVIDES_CARE_ON",   "Person -> Claim",           "role (ICP/Informal/Family), service_start, service_end", "Q11-13, Q15, Q39, Q49"],
            ["EMPLOYED_BY",        "Person -> Business",        "role, hire_date, termination_date",                      "Q11, Q50"],
            ["IS_AGENCY_FOR",      "Business -> Claim",         "agency_type (HHCA/Facility), contract dates",            "Q11, Q50"],
            ["LOGGED_SESSION",     "Person -> CareSession",     "(none)",                                                 "Q16-22"],
            ["SESSION_FOR_CLAIM",  "CareSession -> Claim",      "(none)",                                                 "Q16, Q41-45"],
            ["USED_DEVICE",        "CareSession -> Device",     "event (CheckIn / CheckOut)",                             "Q19-21, Q43"],
        ],
        col_widths=[1.7*inch, 1.7*inch, 2.4*inch, 0.95*inch],
    ))

    s.append(p("Clinical, benefit, financial, and workflow edges", H2))
    s.append(table(
        [
            ["Edge",               "From -> To",                  "Unlocks"],
            ["HAS_DIAGNOSIS",      "Claim -> Diagnosis",          "Q25"],
            ["HAS_ASSESSMENT",     "Person -> Assessment",        "Q23, Q24"],
            ["RECEIVES_ADL",       "Claim -> ADL",                "Q26"],
            ["HAS_RIDER",          "Policy -> Rider",             "Q3"],
            ["HAS_BENEFIT",        "Policy -> Benefit",           "Q4"],
            ["BILLED_ON",          "Invoice -> Claim",            "Q29, Q30"],
            ["INVOICED_BY",        "Invoice -> Person | Business","Q28, Q29, Q32"],
            ["HAS_CHARGE",         "Invoice -> Charge",           "Q28, Q29"],
            ["SETTLES_INVOICE",    "Payment -> Invoice",          "Q30, Q32"],
            ["PAID_TO",            "Payment -> Person | Business","Q31, Q32, Q47"],
            ["PAID_VIA",           "Payment -> BankAccount",      "Q31, Q47"],
            ["HAS_REVIEW_CYCLE",   "Claim -> ReviewCycle",        "Q33, Q35"],
            ["TRIGGERED",          "TriggerMetric -> ReviewCycle","Q34"],
            ["HAS_REMEDIATION",    "ReviewCycle -> Remediation",  "Q36"],
        ],
        col_widths=[1.85*inch, 2.65*inch, 2.25*inch],
    ))

    s.append(PageBreak())

    # ------- 5. Property additions to existing nodes ---------------------
    s.append(p("10. Property additions to existing nodes", H1))
    s.append(table(
        [
            ["Existing node", "New properties",                                                            "Unlocks"],
            ["Policy",        "termination_reason, termination_date, sub_status_detail",                   "Q2"],
            ["Claim",         "claim_status_reason, claim_close_reason, no_touch_flag, cognitive_impairment_flag", "Q2, Q24, Q27"],
            ["Person",        "PRIMARY_ROLE (Insured/Family/ICP/Agent/POA), license_number, specialty",    "Q11-13"],
            ["Business",      "BUSINESS_TYPE_EXT (HHCA, Facility, ICP_LLC, ...)",                          "Q11, Q48, Q50"],
            ["Address",       "residence_type (Home / Business / CareSite)",                               "Q8, Q37, Q48"],
        ],
        col_widths=[1.4*inch, 4.0*inch, 1.35*inch],
    ))

    # ------- 6. Loader compatibility -------------------------------------
    s.append(p("11. Loader compatibility (CSV emission contract)", H1))
    s.append(p(
        "Existing builder format: each <font face='Courier'>nodes.csv</font> row is "
        "<i>node_id, node_type, label, source_table, properties_json</i>; each "
        "<font face='Courier'>edges.csv</font> row is "
        "<i>edge_id, source_node_id, target_node_id, edge_type, source_table, properties_json</i>. "
        "All new properties are JSON-stringified into <font face='Courier'>properties_json</font>, "
        "so the loader in <font face='Courier'>src/graph_query/query_graph.py</font> needs zero "
        "changes for new node or edge types.",
    ))
    s.append(p("Example CareSession row in nodes.csv:", H2))
    s.append(code(
        'session_S202604220001,CareSession,'
        '"Session 2026-04-22 ICP=person_5421",care_sessions,'
        '"{""SESSION_ID"":""S202604220001"",""CLAIM_ID"":""C9000000001"",'
        '""ICP_PERSON_ID"":""5421"",""SESSION_DATE"":""2026-04-22"",'
        '""CHECK_IN_TS"":""2026-04-22T08:02:14"",""CHECK_OUT_TS"":""2026-04-22T11:48:55"",'
        '""CHECK_IN_LAT"":42.4583,""CHECK_IN_LON"":-71.0024,'
        '""CHECK_OUT_LAT"":42.4585,""CHECK_OUT_LON"":-71.0021,'
        '""CHECK_IN_DEVICE_ID"":""D-AAB12"",""CHECK_OUT_DEVICE_ID"":""D-AAB12"",'
        '""SUBMISSION_MODE"":""Live"",""DURATION_MINUTES"":226}"'
    ))
    s.append(p("Corresponding edge row in edges.csv:", H2))
    s.append(code(
        'e_session_S202604220001_session_for_claim,'
        'session_S202604220001,claim_C9000000001,SESSION_FOR_CLAIM,'
        'care_sessions,{}'
    ))

    s.append(PageBreak())

    # ------- 7. Implied tools --------------------------------------------
    s.append(p("12. Implied tool catalog additions", H1))
    s.append(p(
        "These tools can be added either as core entries in "
        "<font face='Courier'>src/llm/tool_agent.py</font> or &mdash; appropriately &mdash; "
        "authored at runtime by the existing extension authoring pipeline once the underlying "
        "graph layers exist.",
    ))
    s.append(table(
        [
            ["Tool",                                "Inputs",                                       "Purpose"],
            ["get_care_sessions_for_claim",         "claim_node_id, date_range",                    "Sessions on a claim within a window"],
            ["compute_session_distance_from_address","session_id",                                  "Haversine distance for check-in/out vs policyholder address"],
            ["find_shared_devices_across_icps",     "claim_node_id",                                "Devices on sessions of more than one ICP"],
            ["get_clinical_profile",                "claim_node_id",                                "Diagnoses + MMSE + ADLs"],
            ["get_billing_summary",                 "claim_node_id, period",                        "Charges and payments grouped by ICP and month"],
            ["get_review_cycle_history",            "claim_node_id",                                "Review cycles, triggers, remediations"],
            ["find_provider_overlap_across_claims", "provider_person_id",                           "Other claims this ICP appears on"],
            ["find_address_collisions_for_claim",   "claim_node_id",                                "Anchor + ICP + business address collisions"],
        ],
        col_widths=[2.1*inch, 1.7*inch, 2.95*inch],
    ))

    # ------- 8. Question coverage matrix ---------------------------------
    s.append(p("13. Question coverage", H1))
    s.append(table(
        [
            ["Section",                                    "Today", "After extension"],
            ["1. Policy & claim info (Q1-5)",              "2/5",   "5/5"],
            ["2. People & relationships (Q6-10)",          "2/5",   "5/5"],
            ["3. Providers (Q11-15)",                      "0/5",   "5/5"],
            ["4. Caregiver sessions / geo (Q16-22)",       "0/7",   "7/7"],
            ["5. Clinical (Q23-27)",                       "0/5",   "5/5"],
            ["6. Billing & payments (Q28-32)",             "0.5/5", "5/5"],
            ["7. Review cycles (Q33-36)",                  "0/4",   "4/4"],
            ["8. Graph-native & inference (Q37-50)",       "1/14",  "14/14"],
            ["<b>Total</b>",                                "<b>~6/50</b>", "<b>50/50</b>"],
        ],
        col_widths=[3.7*inch, 1.4*inch, 1.65*inch],
    ))

    s.append(PageBreak())

    # ------- 9. Migration plan -------------------------------------------
    s.append(p("14. Migration plan", H1))
    s.append(p(
        "The five layers are ordered by question yield per unit of effort. Each phase ships "
        "self-consistent CSV updates, tool additions, and synthetic-generator config; the app "
        "loads the new graph without code changes to <font face='Courier'>query_graph.py</font>.",
    ))
    s.append(table(
        [
            ["Phase",                                       "Adds",                                                                       "Unlocks (cumulative)"],
            ["1. Refined relationships + Rider + Benefit",  "IS_POA_FOR, IS_HIPAA_AUTHORIZED_FOR, IS_FAMILY_MEMBER_OF, Rider, Benefit",  "~6 / 50"],
            ["2. Care-operations layer",                    "Person.PRIMARY_ROLE, CareSession, Device, PROVIDES_CARE_ON, USED_DEVICE",   "~26 / 50"],
            ["3. Clinical layer",                           "Diagnosis, Assessment, ADL + edges + Claim flags",                          "~31 / 50"],
            ["4. Financial layer",                          "Invoice, Charge, Payment + INVOICED_BY / PAID_TO / PAID_VIA",                "~38 / 50"],
            ["5. Workflow layer",                           "ReviewCycle, TriggerMetric, Remediation",                                   "50 / 50"],
        ],
        col_widths=[1.95*inch, 3.55*inch, 1.25*inch],
    ))

    s.append(p("15. Synthetic generator changes", H1))
    s.append(p(
        "<font face='Courier'>src/synthetic/configs/large.yaml</font> gains four new sections "
        "(care-operations, clinical, financial, workflow) and the suspicious-motif library "
        "extends with six new patterns:",
    ))
    s.extend(bullets([
        "<b>icp_claimant_address_collision</b> &mdash; ICP and claimant share home address.",
        "<b>device_reuse_across_icps</b> &mdash; same device id submits sessions for &gt;1 ICP.",
        "<b>distance_anomaly_with_manual_sessions</b> &mdash; long-distance pings + Manual mode.",
        "<b>high_charge_low_session_quality</b> &mdash; charges scale with manual / short sessions.",
        "<b>agency_icp_bank_sharing</b> &mdash; HHCA and its ICPs settle into one bank account.",
        "<b>provider_cross_claim_concentration</b> &mdash; one ICP saturates an unusual share of claims.",
    ]))

    s.append(p("16. What this design buys", H1))
    s.extend(bullets([
        "<b>Determinism preserved.</b> Every new property and edge is read-only from the LLM&rsquo;s "
        "perspective; the planner picks tools but cannot fabricate clinical scores or session pings.",
        "<b>Layered rollout.</b> Each phase is independently useful and shippable; the full set is "
        "not a prerequisite to demo value.",
        "<b>No loader migration.</b> Properties live inside <font face='Courier'>properties_json</font>, "
        "so the existing CSV columns and the NetworkX loader are unchanged.",
        "<b>Plays well with extension authoring.</b> Once the underlying nodes exist, the LLM can "
        "author and smoke-test new tools (haversine, overlap detection, motif scans) on demand.",
        "<b>Maps directly to fraud signals.</b> The TriggerMetric vocabulary mirrors the suspicious "
        "motifs the synthetic generator injects, so investigators see the same words in the data "
        "and in the UI.",
    ]))

    return s


def main() -> None:
    doc = _build_doc()
    doc.build(build_story())
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()

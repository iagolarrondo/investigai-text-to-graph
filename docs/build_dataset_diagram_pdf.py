"""Render a 3-page architecture diagram of the full extended synthetic dataset.

Page 1 — Operations flow (Workflow + Financial + Care-ops layers, anchored on Claim).
Page 2 — Schema reference (Clinical + Policy-admin core layers, anchored on Claim/Person).
Page 3 — Edge inventory + node counts + layer color legend.

Splitting the topology across two focused diagrams keeps every arrow short and
unambiguous; the full edge list lives on the legend page.

Run:    .venv/bin/python docs/build_dataset_diagram_pdf.py
Output: docs/synthetic_dataset_diagram.pdf
"""
from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER, landscape
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Live counts
# ---------------------------------------------------------------------------
NODE_COUNTS = {
    "ADL": 799, "Address": 528, "Assessment": 173, "BankAccount": 503,
    "Benefit": 660, "Business": 44, "CareSession": 7127, "Charge": 7127,
    "Claim": 220, "Device": 439, "Diagnosis": 548, "Invoice": 1980,
    "Payment": 1980, "Person": 793, "Policy": 240, "Remediation": 13,
    "ReviewCycle": 54, "Rider": 331, "TriggerMetric": 58,
}
PERSON_ICP = 433
PERSON_OTHER = NODE_COUNTS["Person"] - PERSON_ICP  # 360

EDGE_COUNTS = {
    "ACT_ON_BEHALF_OF": 3, "BILLED_ON": 1980, "EMPLOYED_BY": 433,
    "HAS_ASSESSMENT": 173, "HAS_BENEFIT": 660, "HAS_CHARGE": 7127,
    "HAS_DIAGNOSIS": 548, "HAS_REMEDIATION": 13, "HAS_REVIEW_CYCLE": 54,
    "HAS_RIDER": 331, "HOLD_BY": 888, "INVOICED_BY": 1980,
    "IS_AGENCY_FOR": 173, "IS_CLAIM_AGAINST_POLICY": 220,
    "IS_COVERED_BY": 431, "IS_RELATED_TO": 84, "IS_SPOUSE_OF": 96,
    "LOCATED_IN": 873, "LOGGED_SESSION": 7127, "PAID_TO": 1980,
    "PAID_VIA": 1980, "PROVIDES_CARE_ON": 433, "RECEIVES_ADL": 799,
    "SESSION_FOR_CLAIM": 7127, "SETTLES_INVOICE": 1980, "SOLD_POLICY": 49,
    "TRIGGERED": 58, "USED_DEVICE": 7127,
}
TOTAL_NODES = sum(NODE_COUNTS.values())
TOTAL_EDGES = sum(EDGE_COUNTS.values())

LAYERS = {
    "workflow":  {"fill": colors.HexColor("#FECACA"), "stroke": colors.HexColor("#991B1B"), "label": "Workflow"},
    "financial": {"fill": colors.HexColor("#BFDBFE"), "stroke": colors.HexColor("#1E40AF"), "label": "Financial"},
    "careops":   {"fill": colors.HexColor("#FDE68A"), "stroke": colors.HexColor("#92400E"), "label": "Care-operations"},
    "clinical":  {"fill": colors.HexColor("#BBF7D0"), "stroke": colors.HexColor("#166534"), "label": "Clinical"},
    "core":      {"fill": colors.HexColor("#C7D2FE"), "stroke": colors.HexColor("#3730A3"), "label": "Policy-admin core"},
}

PAGE_W, PAGE_H = (1224, 792)  # tabloid landscape
BOX_W, BOX_H = 170, 64

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def fmt(n):
    return f"{n:,}" if n >= 1000 else str(n)


def _wrap(text, max_chars):
    if len(text) <= max_chars:
        return [text]
    words = text.split()
    line1 = ""
    rest = []
    for w in words:
        if len(line1) + len(w) + 1 <= max_chars:
            line1 = (line1 + " " + w).strip()
        else:
            rest.append(w)
    return [line1, " ".join(rest)] if rest else [line1]


def draw_box(c, name, count, layer, x, y, dimmed=False):
    style = LAYERS[layer]
    fill = style["fill"]
    stroke = style["stroke"]
    if dimmed:
        # mute the fill color
        fill = colors.HexColor("#E5E7EB")
        stroke = colors.HexColor("#9CA3AF")
    # drop shadow
    c.setFillColor(colors.HexColor("#CBD5E1"))
    c.setStrokeColor(colors.HexColor("#CBD5E1"))
    c.roundRect(x + 2, y - 2, BOX_W, BOX_H, 7, fill=1, stroke=0)
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(1.5)
    c.roundRect(x, y, BOX_W, BOX_H, 7, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 10.5)
    lines = _wrap(name, max_chars=22)
    line_y = y + BOX_H - 16
    for line in lines[:2]:
        c.drawCentredString(x + BOX_W / 2, line_y, line)
        line_y -= 12
    c.setFont("Helvetica-Bold", 18)
    c.setFillColor(stroke)
    c.drawCentredString(x + BOX_W / 2, y + 9, fmt(count))


_ANCHORS = {
    "left":      lambda x, y: (x,                 y + BOX_H / 2),
    "right":     lambda x, y: (x + BOX_W,         y + BOX_H / 2),
    "top":       lambda x, y: (x + BOX_W / 2,     y + BOX_H),
    "bottom":    lambda x, y: (x + BOX_W / 2,     y),
    "top-l":     lambda x, y: (x + BOX_W * 0.30,  y + BOX_H),
    "top-r":     lambda x, y: (x + BOX_W * 0.70,  y + BOX_H),
    "bottom-l":  lambda x, y: (x + BOX_W * 0.30,  y),
    "bottom-r":  lambda x, y: (x + BOX_W * 0.70,  y),
    "left-t":    lambda x, y: (x,                 y + BOX_H * 0.70),
    "left-b":    lambda x, y: (x,                 y + BOX_H * 0.30),
    "right-t":   lambda x, y: (x + BOX_W,         y + BOX_H * 0.70),
    "right-b":   lambda x, y: (x + BOX_W,         y + BOX_H * 0.30),
}


def _arrowhead(c, x_from, y_from, x_to, y_to, size=7):
    angle = math.atan2(y_to - y_from, x_to - x_from)
    a1 = angle + math.radians(150)
    a2 = angle - math.radians(150)
    p1 = (x_to + size * math.cos(a1), y_to + size * math.sin(a1))
    p2 = (x_to + size * math.cos(a2), y_to + size * math.sin(a2))
    p = c.beginPath()
    p.moveTo(x_to, y_to)
    p.lineTo(*p1)
    p.lineTo(*p2)
    p.close()
    c.drawPath(p, stroke=0, fill=1)


def draw_edge(c, x1, y1, x2, y2, color, label=None, count=None,
              waypoint=None, label_dx=0, label_dy=0, label_pos=None):
    """Straight or single-elbow arrow with optional label.

    waypoint: optional (wx, wy) -> draws line1 (x1,y1)->(wx,wy) then (wx,wy)->(x2,y2).
    label_pos: absolute (lx, ly) override — bypasses midpoint calculation entirely.
    """
    c.setStrokeColor(color)
    c.setFillColor(color)
    c.setLineWidth(1.2)

    if waypoint:
        wx, wy = waypoint
        c.line(x1, y1, wx, wy)
        c.line(wx, wy, x2, y2)
        _arrowhead(c, wx, wy, x2, y2, size=7)
        seg1_len = math.hypot(wx - x1, wy - y1)
        seg2_len = math.hypot(x2 - wx, y2 - wy)
        if seg1_len >= seg2_len:
            mx, my = (x1 + wx) / 2, (y1 + wy) / 2
        else:
            mx, my = (wx + x2) / 2, (wy + y2) / 2
    else:
        c.line(x1, y1, x2, y2)
        _arrowhead(c, x1, y1, x2, y2, size=7)
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2

    if label is not None:
        text = f"{label}  {fmt(count)}" if count is not None else label
        c.setFont("Helvetica-Bold", 8.4)
        text_w = c.stringWidth(text, "Helvetica-Bold", 8.4)
        pad = 3
        if label_pos is not None:
            lx, ly = label_pos
        else:
            lx, ly = mx + label_dx, my + label_dy
        # white pill background
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.HexColor("#E2E8F0"))
        c.setLineWidth(0.4)
        c.roundRect(lx - text_w / 2 - pad, ly - 5, text_w + pad * 2, 12, 2,
                    fill=1, stroke=1)
        c.setFillColor(color)
        c.drawCentredString(lx, ly - 1, text)


def anchor(layout, side):
    _, _, _, x, y = layout
    return _ANCHORS[side](x, y)


def draw_layer_label(c, x, y, w, h, layer_key):
    info = LAYERS[layer_key]
    c.setFillColor(info["fill"])
    c.setStrokeColor(info["stroke"])
    c.setLineWidth(0.6)
    c.roundRect(x, y, w, h, 4, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 9.5)
    c.saveState()
    c.translate(x + w / 2, y + h / 2)
    c.rotate(90)
    c.drawCentredString(0, -3, info["label"])
    c.restoreState()


# ---------------------------------------------------------------------------
# PAGE 1: Operations flow
# Layers: Workflow / Financial / Care-ops, anchored on Claim.
# ---------------------------------------------------------------------------

def render_page_operations(c):
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    # Title
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 22)
    c.drawString(40, PAGE_H - 40, "Page 1 / 3 - Operational data flow")
    c.setFont("Helvetica", 11)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(40, PAGE_H - 58,
                 "Workflow + Financial + Care-operations layers anchored on Claim. "
                 "Static schema (Clinical + Policy core) on page 2.")

    # Layout per layer
    BAND_Y = {"workflow": 660, "financial": 500, "careops": 340, "anchor": 110}
    nodes = {
        # workflow
        "TriggerMetric": ("TriggerMetric",   NODE_COUNTS["TriggerMetric"], "workflow",  450, BAND_Y["workflow"]),
        "ReviewCycle":   ("ReviewCycle",     NODE_COUNTS["ReviewCycle"],   "workflow",  650, BAND_Y["workflow"]),
        "Remediation":   ("Remediation",     NODE_COUNTS["Remediation"],   "workflow",  850, BAND_Y["workflow"]),

        # financial
        "Invoice":       ("Invoice",         NODE_COUNTS["Invoice"],       "financial",  90, BAND_Y["financial"]),
        "Charge":        ("Charge",          NODE_COUNTS["Charge"],        "financial", 290, BAND_Y["financial"]),
        "Payment":       ("Payment",         NODE_COUNTS["Payment"],       "financial", 740, BAND_Y["financial"]),
        "BankAccount":   ("BankAccount",     NODE_COUNTS["BankAccount"],   "financial", 940, BAND_Y["financial"]),

        # care-ops
        "Person_ICP":    ("Person (ICP role)", PERSON_ICP,                 "careops",    90, BAND_Y["careops"]),
        "Business":      ("Business (HHCA)",   NODE_COUNTS["Business"],    "careops",   290, BAND_Y["careops"]),
        "CareSession":   ("CareSession",      NODE_COUNTS["CareSession"],  "careops",   540, BAND_Y["careops"]),
        "Device":        ("Device",           NODE_COUNTS["Device"],       "careops",   740, BAND_Y["careops"]),

        # anchor (dimmed: shown for context only)
        "Claim":         ("Claim",            NODE_COUNTS["Claim"],        "core",      540, BAND_Y["anchor"]),
        "Person_Other":  ("Person (insured)", PERSON_OTHER,                "core",       90, BAND_Y["anchor"]),
    }

    # layer label strips
    draw_layer_label(c, 30, BAND_Y["workflow"]  - 14, 22, BOX_H + 30, "workflow")
    draw_layer_label(c, 30, BAND_Y["financial"] - 14, 22, BOX_H + 30, "financial")
    draw_layer_label(c, 30, BAND_Y["careops"]   - 14, 22, BOX_H + 30, "careops")
    draw_layer_label(c, 30, BAND_Y["anchor"]    - 14, 22, BOX_H + 30, "core")

    # boxes
    for k, (name, count, layer, x, y) in nodes.items():
        dimmed = (k in ("Claim", "Person_Other"))  # drawn but de-emphasized
        draw_box(c, name, count, layer, x, y, dimmed=False)

    # ----- arrows -----
    workflow_color = LAYERS["workflow"]["stroke"]
    financial_color = LAYERS["financial"]["stroke"]
    careops_color = LAYERS["careops"]["stroke"]
    core_color = LAYERS["core"]["stroke"]

    # Workflow horizontal chain
    s = nodes["TriggerMetric"]; d = nodes["ReviewCycle"]
    draw_edge(c, *anchor(s, "right"), *anchor(d, "left"), workflow_color,
              "TRIGGERED", 58, label_dy=11)
    s = nodes["ReviewCycle"]; d = nodes["Remediation"]
    draw_edge(c, *anchor(s, "right"), *anchor(d, "left"), workflow_color,
              "HAS_REMEDIATION", 13, label_dy=11)

    # Claim -> ReviewCycle: long elbow up
    s = nodes["Claim"]; d = nodes["ReviewCycle"]
    sx, sy = anchor(s, "right")
    dx, dy = anchor(d, "bottom")
    waypoint = (dx, sy)  # elbow at right of Claim, then up to ReviewCycle bottom
    draw_edge(c, sx, sy, dx, dy, core_color, "HAS_REVIEW_CYCLE", 54,
              waypoint=waypoint, label_dx=10, label_dy=0)

    # Financial internal
    s = nodes["Invoice"]; d = nodes["Charge"]
    draw_edge(c, *anchor(s, "right"), *anchor(d, "left"), financial_color,
              "HAS_CHARGE", 7127, label_dy=11)
    s = nodes["Payment"]; d = nodes["Invoice"]
    # payment to invoice: long horizontal across the band
    sx, sy = anchor(s, "left")
    dx, dy = anchor(d, "right")
    draw_edge(c, sx, sy, dx, dy, financial_color, "SETTLES_INVOICE", 1980,
              label_dy=11)
    s = nodes["Payment"]; d = nodes["BankAccount"]
    draw_edge(c, *anchor(s, "right"), *anchor(d, "left"), financial_color,
              "PAID_VIA", 1980, label_dy=11)

    # ---- Financial -> Care-ops / Claim (down arrows, labels placed in clean side channels) ----
    # Invoice -> Claim: vertical down on left side, horizontal across to Claim top
    s = nodes["Invoice"]; d = nodes["Claim"]
    sx, sy = anchor(s, "bottom")
    dx, dy = anchor(d, "top-l")
    waypoint = (sx, dy + 60)  # break at a horizontal channel between care-ops and core
    draw_edge(c, sx, sy, dx, dy, financial_color, "BILLED_ON", 1980,
              waypoint=waypoint, label_pos=(sx + 80, dy + 65))

    # Invoice -> Person_ICP: short straight diagonal down (no waypoint, simpler)
    s = nodes["Invoice"]; d = nodes["Person_ICP"]
    sx, sy = anchor(s, "bottom-r")
    dx, dy = anchor(d, "top-l")
    draw_edge(c, sx, sy, dx, dy, financial_color, "INVOICED_BY", 1980,
              label_pos=(sx + 25, (sy + dy) / 2 + 4))

    # Payment -> Person_ICP: elbow that runs above the care-ops boxes
    s = nodes["Payment"]; d = nodes["Person_ICP"]
    sx, sy = anchor(s, "left")
    dx, dy = anchor(d, "top")
    # waypoint: horizontal channel just above care-ops band
    channel_y = nodes["Person_ICP"][4] + BOX_H + 30  # 30pt above Person_ICP top
    draw_edge(c, sx, sy, dx, dy, financial_color, "PAID_TO", 1980,
              waypoint=(dx, sy),
              label_pos=((sx + dx) / 2, sy - 8))

    # ---- Care-ops internal ----
    s = nodes["Person_ICP"]; d = nodes["Business"]
    draw_edge(c, *anchor(s, "right"), *anchor(d, "left"), careops_color,
              "EMPLOYED_BY", 433, label_dy=12)

    s = nodes["Person_ICP"]; d = nodes["CareSession"]
    # Route over Business box: up from Person_ICP top, right past Business, down to CareSession top
    sx, sy = anchor(s, "top-r")
    dx, dy = anchor(d, "top")
    above_y = sy + 18
    # double-elbow path - implement as two segments
    c.setStrokeColor(careops_color); c.setFillColor(careops_color)
    c.setLineWidth(1.2)
    c.line(sx, sy, sx, above_y)
    c.line(sx, above_y, dx, above_y)
    c.line(dx, above_y, dx, dy)
    _arrowhead(c, dx, above_y, dx, dy)
    # label
    label_text = "LOGGED_SESSION  7,127"
    c.setFont("Helvetica-Bold", 8.4)
    tw = c.stringWidth(label_text, "Helvetica-Bold", 8.4)
    pad = 3
    lx, ly = (sx + dx) / 2, above_y + 5
    c.setFillColor(colors.white); c.setStrokeColor(colors.HexColor("#E2E8F0"))
    c.setLineWidth(0.4)
    c.roundRect(lx - tw / 2 - pad, ly - 5, tw + pad * 2, 12, 2, fill=1, stroke=1)
    c.setFillColor(careops_color)
    c.drawCentredString(lx, ly - 1, label_text)

    s = nodes["CareSession"]; d = nodes["Device"]
    draw_edge(c, *anchor(s, "right"), *anchor(d, "left"), careops_color,
              "USED_DEVICE", 7127, label_dy=12)

    # ---- Care-ops -> Claim (three converging arrows; spread them across Claim's top) ----
    # SESSION_FOR_CLAIM: vertical down to Claim top-center
    s = nodes["CareSession"]; d = nodes["Claim"]
    sx, sy = anchor(s, "bottom")
    dx, dy = anchor(d, "top")
    draw_edge(c, sx, sy, dx, dy, careops_color, "SESSION_FOR_CLAIM", 7127,
              label_pos=(sx + 70, (sy + dy) / 2))

    # PROVIDES_CARE_ON: from Person_ICP bottom, route along bottom channel, into Claim left
    s = nodes["Person_ICP"]; d = nodes["Claim"]
    sx, sy = anchor(s, "bottom-r")
    dx, dy = anchor(d, "left-b")
    waypoint = (sx, dy)
    draw_edge(c, sx, sy, dx, dy, careops_color, "PROVIDES_CARE_ON", 433,
              waypoint=waypoint,
              label_pos=((sx + dx) / 2, dy - 10))

    # IS_AGENCY_FOR: from Business bottom-r down, then right to Claim left-t
    s = nodes["Business"]; d = nodes["Claim"]
    sx, sy = anchor(s, "bottom-r")
    dx, dy = anchor(d, "left-t")
    waypoint = (sx, dy)
    draw_edge(c, sx, sy, dx, dy, careops_color, "IS_AGENCY_FOR", 173,
              waypoint=waypoint,
              label_pos=((sx + dx) / 2, dy + 10))

    # Footer
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawCentredString(PAGE_W / 2, 25,
        "Total: 13 edges shown on this page; remaining 14 edges (clinical + policy core + Person<->Person) on page 2.")


# ---------------------------------------------------------------------------
# PAGE 2: Static schema reference
# Layers: Clinical + Policy-admin core, anchored on Claim/Person.
# ---------------------------------------------------------------------------

def render_page_schema(c):
    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 22)
    c.drawString(40, PAGE_H - 40, "Page 2 / 3 - Static schema reference")
    c.setFont("Helvetica", 11)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(40, PAGE_H - 58,
                 "Clinical layer + Policy-admin core. Operational flow on page 1.")

    BAND_Y = {"clinical": 580, "core_top": 380, "core_bot": 120}
    # Layout: Person (left) -> Policy -> Claim (right) so Person->Policy
    # doesn't pass behind Claim. Clinical row mirrors the order so each
    # arrow is short and doesn't cross siblings.
    nodes = {
        # clinical
        "Diagnosis":  ("Diagnosis",  NODE_COUNTS["Diagnosis"],  "clinical", 540, BAND_Y["clinical"]),
        "Assessment": ("Assessment", NODE_COUNTS["Assessment"], "clinical", 100, BAND_Y["clinical"]),
        "ADL":        ("ADL",        NODE_COUNTS["ADL"],        "clinical", 800, BAND_Y["clinical"]),

        # core top row (Person -> Policy -> Claim, left to right)
        "Person_Other":  ("Person (insured / family / agent)", PERSON_OTHER, "core",  80, BAND_Y["core_top"]),
        "Policy":        ("Policy",        NODE_COUNTS["Policy"],         "core",  370, BAND_Y["core_top"]),
        "Claim":         ("Claim",         NODE_COUNTS["Claim"],          "core",  640, BAND_Y["core_top"]),

        # core bottom row
        "Rider":         ("Rider",         NODE_COUNTS["Rider"],          "core",  280, BAND_Y["core_bot"]),
        "Benefit":       ("Benefit",       NODE_COUNTS["Benefit"],        "core",  470, BAND_Y["core_bot"]),
        "Address":       ("Address",       NODE_COUNTS["Address"],        "core",  900, BAND_Y["core_bot"]),
        "BankAccount":   ("BankAccount",   NODE_COUNTS["BankAccount"],    "core",  690, BAND_Y["core_bot"]),
    }

    draw_layer_label(c, 30, BAND_Y["clinical"] - 14, 22, BOX_H + 30, "clinical")
    draw_layer_label(c, 30, BAND_Y["core_top"] - 14, 22, BOX_H + 30, "core")
    draw_layer_label(c, 30, BAND_Y["core_bot"] - 14, 22, BOX_H + 30, "core")

    for k, (name, count, layer, x, y) in nodes.items():
        draw_box(c, name, count, layer, x, y)

    clinical_color = LAYERS["clinical"]["stroke"]
    core_color = LAYERS["core"]["stroke"]

    # ---- Clinical edges (Person -> Assessment, Claim -> Diagnosis & ADL) ----
    # Person sits at far left; Assessment is the leftmost clinical box.
    # So Person -> Assessment is a clean short up-arrow.
    s = nodes["Person_Other"]; d = nodes["Assessment"]
    sx, sy = anchor(s, "top"); dx, dy = anchor(d, "bottom")
    draw_edge(c, sx, sy, dx, dy, core_color, "HAS_ASSESSMENT", 173,
              label_dx=20, label_dy=0)

    # Claim is rightmost in core row. Diagnosis is in middle of clinical row.
    s = nodes["Claim"]; d = nodes["Diagnosis"]
    sx, sy = anchor(s, "top-l"); dx, dy = anchor(d, "bottom")
    draw_edge(c, sx, sy, dx, dy, core_color, "HAS_DIAGNOSIS", 548,
              label_dx=-26, label_dy=0)

    # ADL on right, Claim on right => short up-arrow
    s = nodes["Claim"]; d = nodes["ADL"]
    sx, sy = anchor(s, "top-r"); dx, dy = anchor(d, "bottom")
    draw_edge(c, sx, sy, dx, dy, core_color, "RECEIVES_ADL", 799,
              label_dx=22, label_dy=0)

    # ---- Core row: Person -> Policy -> Claim ----
    # Person on far left, Policy in middle, Claim on right => clean horizontals.
    s = nodes["Claim"]; d = nodes["Policy"]
    draw_edge(c, *anchor(s, "left"), *anchor(d, "right"), core_color,
              "IS_CLAIM_AGAINST_POLICY  220", count=None, label_dy=12)

    # Person -> Policy: TWO edges, offset top/bottom of the boxes' right/left edges
    s = nodes["Person_Other"]; d = nodes["Policy"]
    sx, sy = anchor(s, "right-t"); dx, dy = anchor(d, "left-t")
    draw_edge(c, sx, sy, dx, dy, core_color, "IS_COVERED_BY", 431, label_dy=11)
    sx, sy = anchor(s, "right-b"); dx, dy = anchor(d, "left-b")
    draw_edge(c, sx, sy, dx, dy, core_color, "SOLD_POLICY", 49, label_dy=-11)

    # ---- Policy -> Rider / Benefit (downward to bottom row) ----
    s = nodes["Policy"]; d = nodes["Rider"]
    sx, sy = anchor(s, "bottom-l"); dx, dy = anchor(d, "top")
    draw_edge(c, sx, sy, dx, dy, core_color, "HAS_RIDER", 331,
              label_dx=-22, label_dy=0)

    s = nodes["Policy"]; d = nodes["Benefit"]
    sx, sy = anchor(s, "bottom-r"); dx, dy = anchor(d, "top")
    draw_edge(c, sx, sy, dx, dy, core_color, "HAS_BENEFIT", 660,
              label_dx=22, label_dy=0)

    # ---- Person -> Address / BankAccount (downward to bottom row, right side) ----
    # These are long arrows; route via elbow so they don't cross Policy.
    # Drop down from Person bottom, then traverse right under the core row.
    s = nodes["Person_Other"]; d = nodes["Address"]
    sx, sy = anchor(s, "bottom-r"); dx, dy = anchor(d, "top")
    waypoint = (dx, sy - 50)
    draw_edge(c, sx, sy, dx, dy, core_color, "LOCATED_IN", 829,
              waypoint=waypoint, label_dx=0, label_dy=8)

    s = nodes["Person_Other"]; d = nodes["BankAccount"]
    sx, sy = anchor(s, "bottom"); dx, dy = anchor(d, "top")
    waypoint = (dx, sy - 80)
    draw_edge(c, sx, sy, dx, dy, core_color, "HOLD_BY", 888,
              waypoint=waypoint, label_dx=14, label_dy=0)

    # Person <-> Person self-loops (drawn as a note under the box)
    px, py, _w, _h = nodes["Person_Other"][3], nodes["Person_Other"][4], BOX_W, BOX_H
    c.setStrokeColor(core_color); c.setFillColor(core_color)
    c.setLineWidth(1.0)
    # arc from left-bottom to right-bottom of Person box
    p = c.beginPath()
    p.moveTo(px + 30, py)
    p.curveTo(px + 30, py - 30, px + BOX_W - 30, py - 30, px + BOX_W - 30, py)
    c.drawPath(p, stroke=1, fill=0)
    _arrowhead(c, px + BOX_W - 32, py - 4, px + BOX_W - 30, py)
    c.setFont("Helvetica-Bold", 7.8)
    c.setFillColor(colors.white)
    label_text = "IS_SPOUSE_OF 96  |  IS_RELATED_TO 84  |  ACT_ON_BEHALF_OF 3"
    tw = c.stringWidth(label_text, "Helvetica-Bold", 7.8)
    c.roundRect(px + BOX_W / 2 - tw / 2 - 4, py - 25, tw + 8, 11, 2,
                fill=1, stroke=0)
    c.setFillColor(core_color)
    c.drawCentredString(px + BOX_W / 2, py - 21, label_text)

    # footer
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#64748B"))
    c.drawCentredString(PAGE_W / 2, 25,
        "Combined with page 1: all 27 edge types and 19 node types are present.  "
        "Full inventory + counts on page 3.")


# ---------------------------------------------------------------------------
# PAGE 3: Edge inventory + node counts + legend
# ---------------------------------------------------------------------------

def render_page_legend(c):
    page_w, page_h = landscape(LETTER)  # 792 x 612
    c.setPageSize((page_w, page_h))

    c.setFillColor(colors.HexColor("#F8FAFC"))
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 17)
    c.drawString(36, page_h - 38, "Page 3 / 3 - Complete inventory")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#475569"))
    c.drawString(36, page_h - 54,
                 "All 27 edge types (sorted by volume), all 19 node types, and the layer color key.")

    # Edge table
    rows = sorted(EDGE_COUNTS.items(), key=lambda kv: -kv[1])
    half = (len(rows) + 1) // 2
    cols = [(36, rows[:half]), (page_w / 2 + 18, rows[half:])]
    EDGE_FROM_TO = {
        "ACT_ON_BEHALF_OF":         "Person -> Person",
        "BILLED_ON":                "Invoice -> Claim",
        "EMPLOYED_BY":              "Person -> Business",
        "HAS_ASSESSMENT":           "Person -> Assessment",
        "HAS_BENEFIT":              "Policy -> Benefit",
        "HAS_CHARGE":               "Invoice -> Charge",
        "HAS_DIAGNOSIS":            "Claim -> Diagnosis",
        "HAS_REMEDIATION":          "ReviewCycle -> Remediation",
        "HAS_REVIEW_CYCLE":         "Claim -> ReviewCycle",
        "HAS_RIDER":                "Policy -> Rider",
        "HOLD_BY":                  "Person -> BankAccount",
        "INVOICED_BY":              "Invoice -> Person/Business",
        "IS_AGENCY_FOR":            "Business -> Claim",
        "IS_CLAIM_AGAINST_POLICY":  "Claim -> Policy",
        "IS_COVERED_BY":            "Person -> Policy",
        "IS_RELATED_TO":            "Person -> Person",
        "IS_SPOUSE_OF":             "Person -> Person",
        "LOCATED_IN":               "Person/Business -> Address",
        "LOGGED_SESSION":           "Person -> CareSession",
        "PAID_TO":                  "Payment -> Person/Business",
        "PAID_VIA":                 "Payment -> BankAccount",
        "PROVIDES_CARE_ON":         "Person -> Claim",
        "RECEIVES_ADL":             "Claim -> ADL",
        "SESSION_FOR_CLAIM":        "CareSession -> Claim",
        "SETTLES_INVOICE":          "Payment -> Invoice",
        "SOLD_POLICY":              "Person -> Policy",
        "TRIGGERED":                "TriggerMetric -> ReviewCycle",
        "USED_DEVICE":              "CareSession -> Device",
    }
    header_y = page_h - 86
    c.setFont("Helvetica-Bold", 9)
    for col_x, _ in cols:
        c.setFillColor(colors.HexColor("#0F172A"))
        c.drawString(col_x,         header_y, "Edge type")
        c.drawString(col_x + 170,   header_y, "From  ->  To")
        c.drawRightString(col_x + 340, header_y, "Count")
        c.setStrokeColor(colors.HexColor("#94A3B8"))
        c.setLineWidth(0.5)
        c.line(col_x, header_y - 3, col_x + 340, header_y - 3)

    c.setFont("Helvetica", 9)
    for col_x, col_rows in cols:
        y = header_y - 16
        for i, (etype, count) in enumerate(col_rows):
            if i % 2 == 1:
                c.setFillColor(colors.HexColor("#EEF2F7"))
                c.rect(col_x - 3, y - 4, 346, 14, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#0F172A"))
            c.drawString(col_x,        y, etype)
            c.setFillColor(colors.HexColor("#475569"))
            c.drawString(col_x + 170,  y, EDGE_FROM_TO.get(etype, "?"))
            c.setFillColor(colors.HexColor("#0F172A"))
            c.drawRightString(col_x + 340, y, fmt(count))
            y -= 14

    # Node-type counts
    c.setFillColor(colors.HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(36, 230, "Node-type counts")
    nodes_sorted = sorted(NODE_COUNTS.items(), key=lambda kv: -kv[1])
    cols_n = 4
    per_col = (len(nodes_sorted) + cols_n - 1) // cols_n
    col_xs = [36, 230, 424, 600]
    c.setFont("Helvetica", 9)
    for ci in range(cols_n):
        chunk = nodes_sorted[ci * per_col:(ci + 1) * per_col]
        y = 210
        for ntype, count in chunk:
            c.setFillColor(colors.HexColor("#0F172A"))
            c.drawString(col_xs[ci], y, ntype)
            c.drawRightString(col_xs[ci] + 150, y, fmt(count))
            y -= 13

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(colors.HexColor("#0F172A"))
    c.drawString(36, 80, "Arrow color = source layer")
    legend_x = 36
    legend_y = 60
    for layer_key, info in LAYERS.items():
        c.setFillColor(info["fill"])
        c.setStrokeColor(info["stroke"])
        c.rect(legend_x, legend_y, 14, 14, fill=1, stroke=1)
        c.setFillColor(colors.HexColor("#0F172A"))
        c.setFont("Helvetica", 9)
        c.drawString(legend_x + 18, legend_y + 4, info["label"])
        legend_x += 130


# ---------------------------------------------------------------------------
def main() -> None:
    out = Path(__file__).resolve().parent / "synthetic_dataset_diagram.pdf"
    c = canvas.Canvas(str(out), pagesize=(PAGE_W, PAGE_H))
    render_page_operations(c); c.showPage()
    c.setPageSize((PAGE_W, PAGE_H))
    render_page_schema(c); c.showPage()
    render_page_legend(c)
    c.save()
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

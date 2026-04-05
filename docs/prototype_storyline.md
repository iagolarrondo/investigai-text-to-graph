# Prototype storyline — graph-assisted fraud investigation (PoC v1)

A **short narrative** you can walk through in a stakeholder or team review. Audience: **technical** readers (analysts, product, SIU leads) who are **not** day-to-day engineers.

---

## 1. Problem context

Fraud and special-investigations work rarely lives in a single table. The same situation shows up as **claims**, **policies**, **people** (insureds, agents, payees), **banks**, **addresses**, and **third parties**. Teams already query relational systems, but **connecting the dots** across those views takes time, repeated joins, and institutional memory.

The question we are exploring: *Can we make “who is connected to whom, and why that matters for this case” faster to see and explain — without replacing existing systems?*

---

## 2. Why a graph matters beyond SQL

SQL is excellent for **filtering and aggregating** well-defined questions (“all claims on this policy”). It is harder to **explore** patterns that emerge only after **several hops** — for example, the same person wearing **different roles** (agent vs claimant), or **shared resources** (bank account, address) across people who do not share a policy number.

A **graph** (nodes = entities, edges = relationships) is a natural way to:

- **Traverse** a neighborhood around a claim or person in a few steps.  
- **Reuse** the same structure for different investigation questions.  
- **Show** a small picture of the relevant slice — useful when explaining a lead to a colleague.

We are **not** claiming graphs replace SQL or core warehouses; they are a **complementary lens** for exploration and narrative.

---

## 3. What our current PoC does

We built a **small, fully synthetic** book of business and a **local pipeline** that:

1. Reads **seed tables** (like simplified extracts from resolved party and policy systems).  
2. Builds a **graph export** (nodes and edges as files).  
3. Runs a handful of **investigation templates** (claim-centric view, shared banks, family-style ties, business at same address as people).  
4. Presents results in a **simple web app**: tables, a **plain-English “why this appeared,”** the **key links**, and a **tiny subgraph** diagram.

**Important:** There is **no real customer data** in this PoC, and **natural-language** routing in v1 is **rule-based** — enough to demo intent, not a production AI product.

---

## 4. Example investigation scenarios

The synthetic data is crafted so **four stories** show up clearly in a demo (details in `docs/demo_cases.md`):

- **Busy policy + role overlap** — Multiple claims on one policy; someone appears as **writing agent** and **claimant** on linked claims — a classic **conflict-of-interest** prompt for review.  
- **Shared bank account, different homes** — Two people on the **same account** with **different mailing addresses** — a **proceeds / identity** prompt, not proof of fraud.  
- **Family network** — Spouse and family edges linking people who also appear around the same claims — useful for **undisclosed connection** conversations.  
- **Business colocated with people** — A **care agency** registered at an **address** where several **insureds or claimants** also live — a **related-party / services** prompt.

Each scenario is **illustrative**; in production, every hit would need **policy, evidence, and human judgment**.

---

## 5. What we could build next

Near-term, realistic directions (see also `docs/roadmap.md`):

- **Richer synthetic (or governed sample) data** and **more query templates** aligned with real SIU playbooks.  
- **Clearer visuals** for larger neighborhoods — without overbuilding before we validate the story.  
- **Optional** smarter question routing or summarization — **only** with explicit **guardrails**, logging, and enterprise approval.  
- Longer arc: **graph database**, **orchestrated** data refresh, and **links to case systems** — if leadership wants this to move beyond a laptop demo.

The PoC’s job today is to **make the conversation concrete**: this is what “graph-assisted investigation” could **feel** like for a user, with honest limits on what is automated vs human.

---

**Related:** [demo_cases.md](demo_cases.md) · [demo_runbook.md](demo_runbook.md) · [roadmap.md](roadmap.md) · [README.md](../README.md)

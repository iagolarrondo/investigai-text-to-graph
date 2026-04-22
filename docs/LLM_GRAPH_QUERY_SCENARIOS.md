# LLM graph query scenarios (InvestigAI / LTC)

This document catalogs **query scenarios** you can use to train or evaluate an LLM that translates natural language into graph queries (e.g. Cypher) and interprets results. It ties together `GRAPH_DATA_MODEL.md`, relational query rules in `CLAUDE.md` / `documentation/`, and common fraud-investigation intents.

**How to use it**

- For each **scenario family**, craft **user questions** (variants below) and **exemplary assistant behavior**: intended query shape, required properties in the answer, and domain caveats.
- Mark scenarios as **graph-native** (paths exist in the knowledge graph) vs **requires relational fallback** (sessions, charges, ping detail not fully modeled on Care nodes).

---

## 1. Query intent taxonomy

| Intent | Description | Example user phrasing |
|--------|-------------|------------------------|
| **Entity lookup** | Single node by id or attribute | “Who is the policyholder for policy POL001?” |
| **Neighbor listing** | All nodes one hop out | “What addresses are linked to this person?” |
| **Path discovery** | Shortest or all paths between A and B | “How does this claim connect to the policy?” |
| **Pattern match** | Subgraph matching a template | “Find all Person–Person spouse pairs at the same address.” |
| **Aggregation** | Count, min/max/avg, distinct | “How many providers are tied to this claim?” |
| **Filter + traverse** | Predicate on properties then expand | “Claims in Remediate status and their policies.” |
| **Existence / boolean** | Yes/no or set empty | “Does this ICP share a bank account with another provider?” |
| **Ranking / top-N** | Order by metric or date | “Most recent review cycle per claim.” |
| **Comparison** | Across two entities or time windows | “Compare diagnosis categories between two claims.” |
| **Explanation** | Why / summarize chain | “Explain the path from alert to remediation.” |
| **Data quality** | Missing edges, orphan nodes | “Which Care nodes have no payment account?” |

---

## 2. Identifier and naming scenarios (must get right)

These scenarios exist so the LLM does **not** confuse internal keys with business keys.

| Scenario | User might say | Correct interpretation |
|----------|----------------|-------------------------|
| **Claim by business id** | “Claim CLM-2024-00001” | Match `CLAIM_NUMBER` on Claim (or filter Claim where human-readable number matches). Do **not** treat as `CLAIM_ID` unless user explicitly gives internal id `C001`-style from your data dictionary. |
| **Claim by internal id** | “Claim id C001” | Match graph `Claim` node key / `CLAIM_ID`. |
| **Person name search** | “JOHN DOE” | Names are **uppercase** in source data; matching should be case-normalized or exact uppercase. |
| **Policy number** | “Policy POL001” | Use `POLICY_NUMBER` on Policy. |
| **Ambiguous “provider”** | “Who is the provider?” | Disambiguate: ICP (Person) vs agency (Business); may be multiple providers per claim. |

**Exemplary response elements:** State which identifier type you matched; if both exist in the graph, show `CLAIM_ID` vs `CLAIM_NUMBER` explicitly in the answer.

---

## 3. Scenarios by node type

### 3.1 Policy

| # | Scenario | Graph angles |
|---|----------|--------------|
| P1 | List all policies (or filter by status/product) | Scan Policy nodes; filter on properties if present. |
| P2 | Policyholder(s) for a policy | Traverse incoming `IS_COVERED_BY` from Person. |
| P3 | Writing agent (person or business) | Traverse incoming `SOLD_POLICY` from Person or Business. |
| P4 | Claims on a policy | Traverse incoming `IS_CLAIM_AGAINST_POLICY` from Claim. |
| P5 | Riders on a policy | Traverse `ASSOCIATED_RIDERS` to Riders nodes. |
| P6 | Rerate / rate history | Traverse `APPROVED_RERATE` to Rerate (if populated). |
| P7 | Temporal link to calendar | Traverse from Year `OF_POLICY` (if Month/Year nodes exist). |

### 3.2 Person (multi-role)

| # | Scenario | Graph angles |
|---|----------|--------------|
| R1 | Policyholder identity | Person with `IS_COVERED_BY` → Policy; return name, SSN, DOB if in properties. |
| R2 | Provider (ICP) for a claim | Person `PROVIDED_CARE` → Care → `CARE_PROVIDED_FOR_CLAIM` → Claim; or `ASSIGNED_BENEFIT_TO` from Claim. |
| R3 | Family / legal ties | `IS_SPOUSE_OF`, `IS_RELATED_TO`, `ACT_ON_BEHALF_OF` (POA), `HIPAA_AUTHORIZED_ON`, `IS_PRIMARY_CONTACT_OF`, `DIAGNOSED_BY`. |
| R4 | Person receives care from business | `RECEIVE_CARE_FROM` → Business. |
| R5 | Person receives care from another person (e.g. ICP) | Person–Person `RECEIVE_CARE_FROM` if modeled. |
| R6 | Employment / treatment | `EMPLOYED_BY`, `TREATED_BY` → Business. |
| R7 | Phone | `USE_PHONE_NUMBER` → Phone. |
| R8 | Address | `LOCATED_IN` → Address. |
| R9 | Eligibility roles | `RECEIVES_REVIEW` / `ASSESS_ELIGIBILITY` → EligibilityReview. |
| R10 | Clinical / onsite roles | `COMPLETE_CLINICAL_REVIEW` → ClinicalReview; `COMPLETE_ONSITE_ASSESSMENT` → OnsiteAssessment. |
| R11 | Bank account | Incoming `HELD_BY` from BankAccount (direction: account → person per model). |

### 3.3 Business

| # | Scenario | Graph angles |
|---|----------|--------------|
| B1 | Provider type (NH, ALF, HHCA, etc.) | Filter Business by type label or property. |
| B2 | Location | `LOCATED_IN` → Address. |
| B3 | Care on claim | Business `PROVIDED_CARE` → Care → Claim. |
| B4 | Eligibility review subject | `RECEIVES_REVIEW` → EligibilityReview. |
| B5 | Sold policy (if modeled) | `SOLD_POLICY` → Policy. |

### 3.4 Claim

| # | Scenario | Graph angles |
|---|----------|--------------|
| C1 | Policy for claim | `IS_CLAIM_AGAINST_POLICY` → Policy. |
| C2 | Diagnoses | Incoming from Diagnosis `DIAGNOSIS_FOR_CLAIM` (direction per your export). |
| C3 | Eligibility reviews | `HAS_ELIGIBILITY_REVIEW` → EligibilityReview. |
| C4 | Benefit assignees | `ASSIGNED_BENEFIT_TO` → Person or Business. |
| C5 | Clinical review | Incoming `CONDUCTED_ON` from ClinicalReview. |
| C6 | Onsite assessment | Incoming `COMPLETED_ON_CLAIM` from OnsiteAssessment. |
| C7 | Review cycles / fraud | Incoming `INVESTIGATION_ON_CLAIM` from ReviewCycle. |
| C8 | Alerts | Incoming `ALERT_ON` from Alert. |

### 3.5 Care

| # | Scenario | Graph angles |
|---|----------|--------------|
| K1 | Who provided care | Incoming `PROVIDED_CARE` from Person or Business. |
| K2 | Which claim | `CARE_PROVIDED_FOR_CLAIM` → Claim. |
| K3 | Geography vs policyholder | `IS_GEO_ADJACENT_TO` → Address (compare to policyholder address). |
| K4 | Payment routing | `PAYMENT_DEPOSITED_TO_ACCOUNT` → BankAccount → `HELD_BY` → Person/Business. |
| K5 | ICP vs business care | Property `BUSINESS_CARE_IND` or separate Care node id convention. |

### 3.6 Address, Phone, BankAccount

| # | Scenario | Notes |
|---|----------|--------|
| A1 | Same address for two persons | Two `LOCATED_IN` to same Address (e.g. spouses). |
| A2 | Shared bank account across providers | Multiple Person/Business → same BankAccount via `HELD_BY` or multiple Care → same account. |

### 3.7 Medical & assessment

| # | Scenario | Graph angles |
|---|----------|--------------|
| M1 | Diagnosis linked to claim | Diagnosis → Claim. |
| M2 | Clinical review for claim | ClinicalReview → Claim (`CONDUCTED_ON`). |
| M3 | Who completed clinical review | Person → ClinicalReview (`COMPLETE_CLINICAL_REVIEW`). |
| M4 | Eligibility review participants | Claim, provider Person/Business, assessor Person. |

### 3.8 Investigation & alerts

| # | Scenario | Graph angles |
|---|----------|--------------|
| I1 | Metrics for a review cycle | ReviewCycle `FLAGGED_ON` → ReviewCycleMetric. |
| I2 | Remediation | ReviewCycle `RESULT_IN_REMEDIATION` → Remediation. |
| I3 | Alert scope | Alert `ALERT_ON` → Claim / Person / ClinicalReview / Diagnosis. |
| I4 | End-to-end fraud story | Alert → Claim → ReviewCycle → Remediation (plus providers). |

### 3.9 Temporal & communications

| # | Scenario | Graph angles |
|---|----------|--------------|
| T1 | Calls in a month | Call `IN_MONTH` → Month `IN_YEAR` → Year. |
| T2 | Call phone number | Call `CALL_WITH_PHONE_NUMBER` → Phone. |
| T3 | Policy year analytics | Year `OF_POLICY` → Policy. |

---

## 4. Scenarios by relationship type (coverage checklist)

Use this as a **matrix** to ensure the LLM has at least one example question per relationship in `GRAPH_DATA_MODEL.md`:

- **Person–Person:** `IS_RELATED_TO`, `IS_SPOUSE_OF`, `IS_PRIMARY_CONTACT_OF`, `ACT_ON_BEHALF_OF`, `DIAGNOSED_BY`, `HIPAA_AUTHORIZED_ON`, `RECEIVE_CARE_FROM` (person–person).
- **Person–entity:** `IS_COVERED_BY`, `SOLD_POLICY`, `LOCATED_IN`, `USE_PHONE_NUMBER`, `PROVIDED_CARE`, `RECEIVE_CARE_FROM` (business), `TREATED_BY`, `EMPLOYED_BY`, `COMPLETE_CLINICAL_REVIEW`, `COMPLETE_ONSITE_ASSESSMENT`, `ASSESS_ELIGIBILITY`, `RECEIVES_REVIEW`.
- **Business:** `LOCATED_IN`, `USE_PHONE_NUMBER`, `SOLD_POLICY`, `PROVIDED_CARE`, `RECEIVES_REVIEW`.
- **Claim:** `IS_CLAIM_AGAINST_POLICY`, `DIAGNOSIS_FOR_CLAIM`, `ASSIGNED_BENEFIT_TO`, `HAS_ELIGIBILITY_REVIEW`.
- **Care:** `CARE_PROVIDED_FOR_CLAIM`, `IS_GEO_ADJACENT_TO`, `PAYMENT_DEPOSITED_TO_ACCOUNT`.
- **Clinical / onsite:** `CONDUCTED_ON`, `COMPLETED_ON_CLAIM`.
- **Investigation:** `INVESTIGATION_ON_CLAIM`, `RESULT_IN_REMEDIATION`, `FLAGGED_ON`, `ALERT_ON`.
- **Policy / financial:** `APPROVED_RERATE`, `ASSOCIATED_RIDERS`, `HELD_BY`.
- **Comms / time:** `CALL_WITH_PHONE_NUMBER`, `IN_MONTH`, `IN_YEAR`, `OF_POLICY`.

---

## 5. Domain scenarios (from InvestigAI query rules)

These often require **relational** detail or properties not on every Care node; label them in your eval set as “graph + optional SQL”.

| # | Domain scenario | Notes for exemplary answer |
|---|-----------------|------------------------------|
| D1 | Policyholder lookup for a claim | Path Claim → Policy ← Person `IS_COVERED_BY`; include demographics if available. |
| D2 | Writing agent | Person or Business `SOLD_POLICY` → Policy. |
| D3 | Current review cycle | Prefer property `LAST_REVIEW_CYCLE_IND` equivalent or latest `REVIEW_CYCLE_START_DATE` if only in relational layer. |
| D4 | Review status semantics | Explain `Remediate` vs `Clear` / `SUB_STATUS_NAM`. |
| D5 | Clinical: no-touch | `END_DATE` starting with 9999 → no-touch. |
| D6 | Clinical: cognitive impairment | `MMSE_SCORE ≤ 23` heuristic. |
| D7 | Eligibility: reviewer vs subject | `ASSESS_ELIGIBILITY` vs `RECEIVES_REVIEW`. |
| D8 | Start of care | May require Invoice table, not Care node alone. |
| D9 | ICP work overlap / consecutive days | Often `INVESTIGAI_ICP_WORK_BLOCKS` + `CLAIM_SYSTEM` (LIFEPRO = no charges). |
| D10 | Geolocation: closest policyholder address | May be on session feature table, not only `IS_GEO_ADJACENT_TO` on Care. |
| D11 | Shared device IDs across ICPs | Care session / device entities may not exist as graph nodes. |
| D12 | Hourly rate summary | User asks min/max/avg, not every session — specify aggregation in exemplary response. |

---

## 6. Multi-hop patterns (from GRAPH_DATA_MODEL traversal examples)

Train the LLM on these **template** questions:

| Pattern | Purpose |
|---------|---------|
| Policy network | Policyholder–spouse–shared provider–address |
| Care flow | Provider → Care → Claim → Policy |
| Investigation path | ReviewCycle → Claim → Policy |
| Payment trail | Care → BankAccount → holder Person/Business |
| Provider–family | Same provider → multiple claims → related policyholders |
| Geographic anomaly | Care not adjacent to policyholder address (if addresses comparable) |

---

## 7. Edge-case scenarios

| # | Scenario | Expected behavior |
|---|----------|-------------------|
| E1 | **No matching nodes** | Return empty result; explain filters; suggest relaxing criteria. |
| E2 | **Multiple valid paths** | Return shortest path or enumerate paths; state ambiguity. |
| E3 | **Overspecified id** | User gives both claim number and policy; validate consistency along graph. |
| E4 | **Sensitive PII** | Answer structure should allow redaction policy (SSN, account numbers). |
| E5 | **LIFEPRO / no charges** | Answer must say charge-based analysis unavailable (domain rule). |
| E6 | **Direction confusion** | e.g. `HELD_BY`: BankAccount → Person vs Person → account; align to `GRAPH_DATA_MODEL.md`. |

---

## 8. Natural-language variation buckets

For each scenario family, include paraphrases:

- **Wh-questions:** “Who / what / which / where” tied to node types.
- **Yes/no:** “Is X connected to Y?” → existence query.
- **How many / how much:** aggregation.
- **Explain / why / how:** path or subgraph narrative.
- **Compare:** two claims, two providers, two time periods.
- **Fuzzy:** “the Boston claim” → resolve via Address `LOCATED_IN` or Claim metadata.

---

## 9. Exemplary response structure (for rubric / few-shot examples)

A strong assistant response should often include:

1. **Interpretation** — Which identifiers and node types were used.  
2. **Query sketch** — Optional Cypher outline or traversal steps (for transparency).  
3. **Results** — Nodes/edges or tabular summary.  
4. **Caveats** — e.g. incomplete graph, need relational session data, LIFEPRO limitation.  
5. **Next step** — Suggested follow-up query if intent was ambiguous.

---

## 10. Suggested minimum example set size

| Bucket | Minimum examples |
|--------|------------------|
| Per major node type (Policy, Person, Business, Claim, Care) | 5+ each |
| Per relationship type (from section 4) | 1+ each |
| Domain rules (section 5) | 1+ each |
| Multi-hop patterns (section 6) | 1+ each |
| Edge cases (section 7) | 2+ each |
| Paraphrase variants | 2–3 per intent family |

---

## 11. Related files

| File | Role |
|------|------|
| `graph/GRAPH_DATA_MODEL.md` | Canonical node/relationship definitions |
| `graph/GRAPH_RELATIONSHIP_COVERAGE.md` | SQL vs synthetic edge provenance for CSV export |
| `CLAUDE.md` | Relational query rules and pitfalls |
| `documentation/*.txt` | Per-topic query guidance |

---

*This is a scenario catalog for LLM training and evaluation—not an exhaustive list of every English phrasing, but a structured checklist to reach high coverage of graph-backed investigator questions.*

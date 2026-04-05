# PoC v1 — initial graph design

Narrow **proof-of-concept** scope for the InvestigAI **text-to-graph** prototype: a **small, loadable graph** that investigators can traverse for “who / what / where / money endpoint” questions around **claims and policies**.

This note is **implementation-oriented**. Sources of truth in-repo: `data/raw/ddl/`, `data/raw/documentation/`, `data/raw/readme.md`, and `data/raw/graph/GRAPH_DATA_MODEL.md` (for **relationship naming**, not full breadth).

---

## 1. Purpose of PoC v1

- Prove **end-to-end**: warehouse-style tables → **nodes/edges** (e.g. CSV/JSON for Neo4j load or an in-memory graph).
- Cover the **backbone** of LTC investigation context: **parties, contract, claim, location, bank endpoints**, and **how they connect**.
- Defer clinical detail, caregiver timelines, audit workflows, and full alignment with every type in `GRAPH_DATA_MODEL.md`.

---

## 2. PoC v1 node types (six only)

| Node label | Primary DDL source | Stable id (confirm in DDL) |
|------------|-------------------|----------------------------|
| **Person** | `T_RESOLVED_PERSON` | `RES_PERSON_ID` (per `GRAPH_DATA_MODEL.md`) |
| **Business** | `T_RESOLVED_BUSINESS` | `RES_BUSINESS_ID` |
| **Policy** | `T_NORM_POLICY` | `POLICY_NUMBER` (join key used in claim docs) |
| **Claim** | `T_NORM_CLAIM` | Prefer **`CLAIM_ID`** for graph internal id; expose **`CLAIM_NUMBER`** as a property for human filters (`readme.md` warns not to confuse them). |
| **Address** | `T_RESOLVED_ADDRESS` | `RES_ADDRESS_ID` |
| **BankAccount** | `T_RESOLVED_BANK_ACCOUNT` | `RES_BANK_ACCOUNT_ID` |

**Load order (suggested):** resolve entities (`Person`, `Business`, `Address`, `BankAccount`, `Policy`) from `T_RESOLVED_*` / `T_NORM_POLICY`, then `Claim` from `T_NORM_CLAIM`, then edges.

---

## 3. PoC v1 edge types (core)

Map crosswalk rows to Neo4j-style types consistent with **`GRAPH_DATA_MODEL.md`** where they match; use **crosswalk columns** (e.g. `EDGE_NAME`, role flags) when present—**read each DDL** before locking direction.

| Relationship intent | Likely relationship type(s) | Primary warehouse sources |
|--------------------|---------------------------|---------------------------|
| **Person–Policy** | `IS_COVERED_BY`, `SOLD_POLICY`, … (per `EDGE_NAME` / docs) | `T_RESOLVED_PERSON_POLICY_CROSSWALK` |
| **Claim–Policy** | `IS_CLAIM_AGAINST_POLICY` | `T_NORM_CLAIM.POLICY_NUMBER` → `T_NORM_POLICY` (attribute join; add an edge in the graph for traversal) |
| **Person–Address** | `LOCATED_IN` | `T_RESOLVED_PERSON_ADDRESS_CROSSWALK` |
| **Business–Address** | `LOCATED_IN` | `T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK` |
| **Person–Person** | `IS_RELATED_TO`, `IS_SPOUSE_OF`, `ACT_ON_BEHALF_OF`, … | `T_RESOLVED_PERSON_PERSON_CROSSWALK` (use row metadata / `EDGE_NAME` if available to pick type) |
| **Person–BankAccount** | `HELD_BY` (or equivalent) | `T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK` |

**Payment / bank links (optional in v1, only if DDL joins are obvious):**

- `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK` links **payments** to **bank accounts**. PoC v1 does **not** add a **Payment** node.
- **If** `T_NORM_PAYMENT` cleanly keys to **Claim** (and optionally provider ids), you can add a small number of edges such as **Claim → BankAccount** with **relationship properties** holding payment identifiers/amounts, *or* skip until validated. Same for “provider → bank”: only if a direct crosswalk or join exists in DDL (this repo’s inventory does **not** list a `T_RESOLVED_BUSINESS_*BANK*` table—do not assume).

---

## 4. What to implement first (checklist)

1. **Parse keys** from the six node tables; deduplicate on business keys above.
2. **Claim–Policy** edge from `POLICY_NUMBER` (verify null handling and type widths in DDL).
3. **Person–Policy**, **Person–Address**, **Business–Address**, **Person–Person** from the listed crosswalks; normalize `EDGE_NAME` → relationship type.
4. **Person–BankAccount** from `T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK`.
5. **Optional:** payment→bank→claim path after inspecting `T_NORM_PAYMENT` + `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK` FK columns.

---

## 5. Excluded from v1 for simplicity

Deliberately **out of scope** for PoC v1 (may return in v2+):

| Area | Examples in this repo | Why skip for v1 |
|------|------------------------|-----------------|
| **Caregiver / care timeline** | `T_NORM_CARE_SESSION`, `T_NORM_CARE_SESSION_EVENT`, `INVESTIGAI_ICP_*`, geolocation crosswalks | Rich time-series and app telemetry; not needed for the six-node backbone. |
| **Alerts & fraud pattern objects** | Described in `GRAPH_DATA_MODEL.md`; no matching DDL files here for Alert nodes | Conceptual layer; add when tables exist. |
| **Review cycles & remediation** | `T_NORM_REVIEW_CYCLE*`, related docs | Audit workflow; not required to prove claim–party–policy–location–bank traversal. |
| **Temporal graph nodes** | Month / Year / call-month patterns in `GRAPH_DATA_MODEL.md` | Synthetic time nodes; omit until core graph is stable. |
| **Clinical / eligibility artifacts** | `T_NORM_DIAGNOSIS`, `T_NORM_CLINICAL_REVIEW`, `T_NORM_ELIGIBILITY_REVIEW`, related crosswalks | Expand graph after backbone loads. |
| **Geolocation as a node** | `T_RESOLVED_GEOLOCATION`, session–geo crosswalks | v1 uses **Address** only for “where.” |
| **Phone, Call, Care aggregate node** | `GRAPH_DATA_MODEL.md` types without full DDL in `data/raw/ddl/` | Not in v1 load list. |
| **Unstructured / semi-structured sources** | `documentation/docs__*.txt`, `readme.md`, LLM outputs | Use for **labeling and QA**, not as graph vertices/edges in v1 unless you explicitly add a “Document” experiment later. |
| **Policy riders as separate nodes** | `T_NORM_POLICY_RIDER` | Keep as **properties on Policy** (or ignore) for v1. |

---

## 6. Open questions (PoC v1 only)

1. **Crosswalk cardinality:** duplicate `(person, policy)` or `(person, address)` rows—merge rule (latest, primary flag, or multigraph).
2. **Person–Person semantics:** map each `EDGE_NAME` / code to exactly one relationship type; document unknowns as `RELATED_TO` with properties.
3. **Business–BankAccount:** confirm whether any join path in DDL is required for investigations; if absent, document “not in v1.”
4. **Claimant vs resolved person:** `T_NORM_CLAIM` carries claimant name fields; decide whether v1 links Claim to Person only via crosswalks or also surfaces shallow claim-level properties.

Revise this file as the first load completes and you validate joins against real (or sample) rows.

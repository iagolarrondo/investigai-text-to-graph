# PoC v1 — graph mapping (warehouse → graph)

Practical mapping for the **small PoC v1** graph described in `docs/initial_graph_design.md`.  
All **source tables** and **columns** below come from `data/raw/ddl/*.sql` in this repository.

---

## 1. Node mappings

| Graph object | Source table | Key column(s) | Important properties (from DDL) | Implementation note |
|--------------|--------------|---------------|--------------------------------|---------------------|
| **Person** | `T_RESOLVED_PERSON` | `RES_PERSON_ID` | `FIRST_NAME`, `MIDDLE_NAME`, `LAST_NAME`, `BIRTH_DATE`, `SEX`, `SSN`, `DEATH_DATE`, `DECEASED_IND` | Use `RES_PERSON_ID` as stable node id. **PII:** treat `SSN` carefully (omit or mask in exports). Name search: `CONCAT(FIRST_NAME,' ',LAST_NAME)` per table comment. |
| **Business** | `T_RESOLVED_BUSINESS` | `RES_BUSINESS_ID` | `BUSINESS_NAME`, `TAX_ID`, `BUSINESS_TYPE`, `DUNS_NUMBER` | `BUSINESS_TYPE`: e.g. HHCA / NH / ALF per comment. |
| **Policy** | `T_NORM_POLICY` | `POLICY_NUMBER` | `COMPANY_CODE`, `POLICY_STATUS`, `POLICY_SUB_STATUS`, `PRODUCT_CODE`, `ISSUE_DATE`, `ISSUE_STATE`, `PREMIUM_AMT`, `TOTAL_PREMIUM_PAID`, DMB/MMB columns, `BENEFIT_PERIOD`, `ELIMINATION_PERIOD`, … | Composite business context may include `COMPANY_CODE` + `POLICY_NUMBER` if needed for uniqueness—confirm in data. |
| **Claim** | `T_NORM_CLAIM` | `CLAIM_ID` (internal) | `CLAIM_NUMBER`, `POLICY_NUMBER`, `FIRST_NAME`, `LAST_NAME`, `BIRTH_DATE` (claimant), `CLAIM_OPEN_DATE`, `CLAIM_CLOSE_DATE`, `CLAIM_STATUS_CODE`, `CLAIM_VALID_IND`, … | **Do not** use `CLAIM_ID` as the investigator-facing id; expose `CLAIM_NUMBER` for search. Join policy on `POLICY_NUMBER` (types differ: claim DDL uses `VARCHAR(200)`, policy uses `VARCHAR(15)`—**normalize/trim** on load). |
| **Address** | `T_RESOLVED_ADDRESS` | `RES_ADDRESS_ID` | `ADDRESS_LINE_1`–`3`, `CITY`, `STATE`, `ZIP_CODE`, `LATITUDE`, `LONGITUDE` | Coords not always populated. |
| **BankAccount** | `T_RESOLVED_BANK_ACCOUNT` | `RES_BANK_ACCOUNT_ID` | `ROUTING_NUMBER`, `ACCOUNT_NUMBER` | **Sensitive:** mask or hash for PoC exports (align with org policy). |

---

## 2. Edge mappings

| Graph object (edge) | Source table | Key column(s) | Important properties | Implementation note |
|---------------------|--------------|---------------|---------------------|------------------------|
| **Person → Policy** (`IS_COVERED_BY` / `SOLD_POLICY`) | `T_RESOLVED_PERSON_POLICY_CROSSWALK` | `RES_PERSON_ID`, `POLICY_NUMBER` | `EDGE_NAME` (`IS_COVERED_BY`, `SOLD_POLICY`), `EDGE_DETAIL`, `EDGE_DETAIL_DSC` | Map `EDGE_NAME` directly to relationship type (string match). Match `POLICY_NUMBER` to **Policy** node key. |
| **Claim → Policy** (`IS_CLAIM_AGAINST_POLICY` or similar) | `T_NORM_CLAIM` → `T_NORM_POLICY` | `T_NORM_CLAIM.POLICY_NUMBER` = `T_NORM_POLICY.POLICY_NUMBER` | — | No crosswalk row: **synthesize** one edge per claim row when `POLICY_NUMBER` is non-null. |
| **Person → Address** (`LOCATED_IN`) | `T_RESOLVED_PERSON_ADDRESS_CROSSWALK` | `RES_PERSON_ID`, `RES_ADDRESS_ID` | `EDGE_NAME` (expected `LOCATED_IN`), `EFFECTIVE_DATE`, `IS_LATEST_ADDRESS_IND` | Filter to latest address for a thinner graph if desired (`IS_LATEST_ADDRESS_IND`). |
| **Business → Address** (`LOCATED_IN`) | `T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK` | `RES_BUSINESS_ID`, `RES_ADDRESS_ID` | — | No `EDGE_NAME` column in DDL; use fixed type `LOCATED_IN`. |
| **Person → Person** (family / POA / HIPAA / physician) | `T_RESOLVED_PERSON_PERSON_CROSSWALK` | `RES_PERSON_ID_SRC`, `RES_PERSON_ID_TGT` | `EDGE_NAME` (`IS_SPOUSE_OF`, `ACT_ON_BEHALF_OF`, `HIPAA_AUTHORIZED_ON`, `IS_RELATED_TO`, `DIAGNOSED_BY`), `EDGE_DETAIL`, `EDGE_DETAIL_DSC` | Direction matters: follow **SRC → TGT** as in DDL comments (e.g. POA: SRC is POA for TGT). |
| **Person → BankAccount** (`HOLD_BY` per DDL) | `T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK` | `RES_PERSON_ID`, `RES_BANK_ACCOUNT_ID` | `EDGE_NAME` (comment: always `HOLD_BY`) | DDL comment spells `HOLD_BY` (not `HELD_BY`); keep literal string from data or normalize in one place. `RES_BANK_ACCOUNT_ID` is `INT` here vs `BIGINT` on bank table—watch type coercion. |

**Optional later (not required for minimal PoC):** `T_NORM_PAYMENT` has `CLAIM_ID` → `T_NORM_CLAIM`, and its header comment describes joining `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK` on `NORM_PAYMENT_ID` then `T_RESOLVED_BANK_ACCOUNT`. You can materialize **Claim → BankAccount** edges (with payment id/amount/date as **relationship properties**) without a Payment **node**.

---

## 3. Property mappings

| Graph target | Source | Key / context | Properties to copy or derive | Implementation note |
|--------------|--------|---------------|-------------------------------|---------------------|
| **Person** node | `T_RESOLVED_PERSON` | `RES_PERSON_ID` | All non-key columns as node properties | Consider dropping or hashing `SSN` for PoC. |
| **Business** node | `T_RESOLVED_BUSINESS` | `RES_BUSINESS_ID` | All non-key columns | — |
| **Policy** node | `T_NORM_POLICY` | `POLICY_NUMBER` | Status, product, dates, premium fields, DMB/MMB, benefit fields | Wide table; PoC can take a **subset** (status, product, issue date, premium) first. |
| **Claim** node | `T_NORM_CLAIM` | `CLAIM_ID` | `CLAIM_NUMBER`, `POLICY_NUMBER`, dates, status codes, claimant name fields, `CLAIM_VALID_IND`, … | Keep both ids on the node for debugging joins. |
| **Address** node | `T_RESOLVED_ADDRESS` | `RES_ADDRESS_ID` | Lines, city, state, zip, lat/long | — |
| **BankAccount** node | `T_RESOLVED_BANK_ACCOUNT` | `RES_BANK_ACCOUNT_ID` | Masked routing/account if exported | Full values only in secure pipelines. |
| **Edges** from crosswalks | `T_RESOLVED_*_CROSSWALK` | row id optional | `EDGE_NAME`, `EDGE_DETAIL*`, `EFFECTIVE_DATE`, `IS_LATEST_ADDRESS_IND` where present | Store crosswalk fields as **relationship properties** so one graph type can carry multiple real-world subtypes (e.g. `IS_RELATED_TO` + `EDGE_DETAIL`). |

---

## 4. Tables not used yet (in repo, outside PoC v1)

These **`Create_Table__` / `Create_View__` files exist under `data/raw/ddl/`** but are **not** part of the six-node PoC v1 load:

| Group | Tables (file stem) | Why defer |
|-------|-------------------|-----------|
| **Care / ICP / geo** | `T_NORM_CARE_SESSION`, `T_NORM_CARE_SESSION_EVENT`, `T_RESOLVED_*GEO*`, `INVESTIGAI_ICP_*`, `V_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK` | Out of v1 scope per `initial_graph_design.md`. |
| **Billing lines** | `T_NORM_INVOICE`, `T_NORM_CHARGE`, `T_NORM_PAYMENT` | Optional enrichment only; no Payment node in v1. |
| **Clinical / eligibility** | `T_NORM_DIAGNOSIS`, `T_NORM_CLINICAL_REVIEW`, `T_NORM_ELIGIBILITY_REVIEW`, `T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK`, related `T_RESOLVED_*ELIGIBILITY*` crosswalks | Expand after backbone. |
| **Other crosswalks** | e.g. `T_RESOLVED_BUSINESS_*` (invoice, person, eligibility), `T_RESOLVED_PERSON_*` (care session, invoice, eligibility), `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK` | Not needed for minimal party–policy–claim–address–bank graph. |
| **Policy rider** | `T_NORM_POLICY_RIDER` | Attach as Policy properties or separate node in v2. |
| **Review / audit** | `T_NORM_REVIEW_CYCLE`, `T_NORM_REVIEW_CYCLE_METRIC`, `T_NORM_REVIEW_CYCLE_REMEDIATION` | Workflow domain; later wave. |
| **Feature / denormalized** | `INVESTIGAI_PROVIDER_CLAIMS` | Scoring / features, not core topology. |

**Non-DDL assets** (`documentation/docs__*.txt`, `readme.md`, `graph/GRAPH_DATA_MODEL.md`) are **not** source tables for v1 loads; use them for **QA, naming, and relationship vocabulary**.

---

*Update this file when you add columns to the graph or widen scope to v2.*

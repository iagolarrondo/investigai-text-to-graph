# InvestigAI – Data Catalog Overview

## Introduction

This document provides an overview of the database tables and supporting documentation that make up the InvestigAI data model. It is intended to orient collaborators to the data landscape — describing what each table contains, its key columns, and how tables relate to one another — so you can quickly navigate to the relevant DDL (under `ddl/`) or documentation (under `documentation/`) file for deeper detail.

All tables reside under a parameterized path: `{catalog_name}.{schema_name}.<TABLE_NAME>`.

---

## Table Naming Conventions

The schema follows three naming conventions that reflect the role of each table:

| Prefix | Layer | Description |
|--------|-------|-------------|
| `T_NORM_*` | Normalized | Source-system records: claims, sessions, invoices, reviews, diagnoses, policies, etc. These tables hold business event data. |
| `T_RESOLVED_*` | Resolved | De-duplicated entity records (persons, businesses, addresses, geolocations) and crosswalk tables that link resolved entities to normalized records. |
| `INVESTIGAI_*` | Feature / Denormalized | Pre-computed, flat tables optimized for common query patterns, removing the need for complex multi-table joins. |

> **Important:** `CLAIM_ID` is an internal database primary key across many `T_NORM_*` tables. It is **not** the human-readable claim number. Always use `CLAIM_NUMBER` when filtering for a specific claim.

---

## Data Domains

The tables are logically organized into six domains:

1. [Core Claims & Policy](#1-core-claims--policy)
2. [People, Businesses & Relationships](#2-people-businesses--relationships)
3. [Providers](#3-providers)
4. [Caregiver App Sessions & Geolocation](#4-caregiver-app-sessions--geolocation)
5. [Clinical Reviews & Diagnoses](#5-clinical-reviews--diagnoses)
6. [Billing & Payments](#6-billing--payments)
7. [Review Cycles & Audit Workflow](#7-review-cycles--audit-workflow)

---

## 1. Core Claims & Policy

This domain covers the foundational claim and policy tables that virtually all other domains link back to.

---

### `T_NORM_CLAIM`
**File:** `ddl/Create_Table__T_NORM_CLAIM.sql`

Central claim table. Each row represents one long-term care claim. Most other domain tables reference this table via `CLAIM_ID` (internal FK) or `CLAIM_NUMBER` (human-readable identifier used in query filters).

| Column | Type | Notes |
|--------|------|-------|
| `CLAIM_ID` | VARCHAR(15) | Internal primary key — **not** the claim number |
| `CLAIM_NUMBER` | VARCHAR(60) | Human-readable claim identifier; use in `WHERE` clauses |
| `POLICY_NUMBER` | VARCHAR(200) | FK to `T_NORM_POLICY` |
| `FIRST_NAME` / `LAST_NAME` | VARCHAR(200) | Claimant name (uppercase) |
| `BIRTH_DATE` | DATETIME | Claimant birth date |
| `CLAIM_OPEN_DATE` / `CLAIM_CLOSE_DATE` | DATETIME | Claim lifecycle dates |
| `CLAIM_STATUS_CODE` / `CLAIM_SUB_STATUS_CODE` | VARCHAR | |
| `POLICY_STATUS` / `POLICY_SUB_STATUS` | VARCHAR | Policy status at time of claim |
| `CLAIM_SYSTEM` | VARCHAR(7) | Source system (`PROMISE` or `LIFEPRO`); relevant for billing analysis |
| `CLINICAL_REVIEW_END_DATE` | DATETIME | |

**Join paths:**
- To policy: `POLICY_NUMBER` → `T_NORM_POLICY`
- To policyholder: `POLICY_NUMBER` → `T_RESOLVED_PERSON_POLICY_CROSSWALK` (where `EDGE_NAME = 'IS_COVERED_BY'`) → `T_RESOLVED_PERSON`

**Supplementary docs:** `docs__T_NORM_CLAIM.txt`

---

### `T_NORM_POLICY`
**File:** `ddl/Create_Table__T_NORM_POLICY.sql`

One row per insurance policy. Most commonly joined from `T_NORM_CLAIM` via `POLICY_NUMBER`. Contains benefit maximums (daily and monthly) for each care setting, as well as premium and policy status information.

| Column | Type | Notes |
|--------|------|-------|
| `POLICY_NUMBER` | VARCHAR(15) | Primary key |
| `POLICY_STATUS` / `POLICY_SUB_STATUS` | VARCHAR | e.g., `Active`, `Terminated`, `Inactive`, `Suspended` |
| `PRODUCT_CODE` | VARCHAR | Policy product type |
| `ISSUE_DATE` / `ISSUE_STATE` | DATE / VARCHAR(2) | |
| `ALF_DMB` / `ICP_DMB` / `NH_DMB` / `HHC_DMB` | NUMERIC | Daily maximum benefits by care setting |
| `ALF_MMB` / `ICP_MMB` / `NH_MMB` / `HHC_MMB` | NUMERIC | Monthly maximum benefits by care setting |
| `PREMIUM_AMT` / `TOTAL_PREMIUM_PAID` | NUMERIC | |
| `BENEFIT_PERIOD` | VARCHAR | |
| `ELIMINATION_PERIOD` | VARCHAR | Waiting period before insurance reimbursement begins |

**Supplementary docs:** `docs__T_NORM_POLICY.txt`, `docs__DMB.txt` *(guidance on reading daily/monthly max benefits)*

---

### `T_NORM_POLICY_RIDER`
**File:** `ddl/Create_Table__T_NORM_POLICY_RIDER.sql`

Riders attached to a policy. Each row is one rider key-value pair for a given policy. Rider keys and values are not pre-defined; filter by `POLICY_NUMBER` to retrieve all riders for a policy.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_POLICY_RIDER_ID` | BIGINT | Primary key |
| `POLICY_NUMBER` | VARCHAR(15) | FK to `T_NORM_POLICY` |
| `SOURCE_SYSTEM` | VARCHAR | `PROMISE` or `LIFEPRO` |
| `RIDER_KEY` / `RIDER_VALUE` | VARCHAR | Rider identifier and value |

---

### `T_NORM_ELIGIBILITY_REVIEW`
**File:** `ddl/Create_Table__T_NORM_ELIGIBILITY_REVIEW.sql`

Provider eligibility reviews. Each row is a review conducted for a provider (person or business) for a specific benefit type. Linked to claims via `T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK` and to providers via the person/business eligibility review crosswalk tables.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_ELIGIBILITY_REVIEW_ID` | INT | Primary key |
| `STATUS` | VARCHAR | `Pending`, `Pending - Management Review`, `Provider Approved`, `Approved - Eligible`, `Provider Denied`, `Denied - Ineligible`, etc. |
| `REVIEW_DATE` | DATETIME | Date the review was conducted |
| `BENEFIT_TYPE` | VARCHAR | Type of care/benefit reviewed |
| `DENIAL_REASON` / `REVIEW_TEXT` | VARCHAR | Additional detail |

**Supplementary docs:** `docs__T_NORM_ELIGIBILITY_REVIEW.txt`, `docs__eligibility_review_query.txt` *(how to query reviews for ICPs vs. business providers)*

---

### `T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK`
**File:** `ddl/Create_Table__T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK.sql`

Links claims to eligibility reviews. `EDGE_NAME` is always `'HAS_ELIGIBILITY_REVIEW'`.

| Column | Type |
|--------|------|
| `CLAIM_ID` | VARCHAR(15) |
| `EDGE_NAME` | VARCHAR(30) |
| `NORM_ELIGIBILITY_REVIEW_ID` | INT |

**Supplementary docs:** `docs__T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK.txt`

---

## 2. People, Businesses & Relationships

These resolved entity and crosswalk tables describe the people, businesses, and addresses involved across all domains.

---

### `T_RESOLVED_PERSON`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON.sql`

De-duplicated person entity table. Covers policyholders, claimants, ICPs (Individual Care Providers), contacts, physicians, and other related individuals. All name fields are uppercase.

| Column | Type | Notes |
|--------|------|-------|
| `RES_PERSON_ID` | BIGINT | Primary key — used as FK across all person crosswalk tables |
| `FIRST_NAME` / `MIDDLE_NAME` / `LAST_NAME` | VARCHAR | Uppercase |
| `BIRTH_DATE` | DATE | |
| `SEX` | VARCHAR | |
| `SSN` | VARCHAR(15) | Social security number |
| `DEATH_DATE` | DATE | Populated when deceased |
| `DECEASED_IND` | INT | `1` = person is deceased |

**Supplementary docs:** `docs__T_RESOLVED_PERSON.txt`, `docs__policyholder_query.txt` *(how to query policyholder details)*, `docs__deceased.txt` *(checking deceased status)*

---

### `T_RESOLVED_PERSON_PERSON_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_PERSON_CROSSWALK.sql`

Person-to-person relationships. `RES_PERSON_ID_SRC` has the described relationship with `RES_PERSON_ID_TGT`.

| `EDGE_NAME` | Meaning |
|-------------|---------|
| `IS_SPOUSE_OF` | Spousal relationship |
| `ACT_ON_BEHALF_OF` | SRC is power of attorney (POA) for TGT |
| `HIPAA_AUTHORIZED_ON` | SRC has HIPAA authorization to access TGT's medical records |
| `IS_RELATED_TO` | General family/relative relationship (`EDGE_DETAIL` may specify the relation) |
| `DIAGNOSED_BY` | SRC was diagnosed by TGT (a physician) |

**Supplementary docs:** `docs__T_RESOLVED_PERSON_PERSON_CROSSWALK.txt`, `docs__POA.txt`, `docs__HIPAA.txt`, `docs__spouses.txt`

---

### `T_RESOLVED_PERSON_POLICY_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_POLICY_CROSSWALK.sql`

Connects persons to policies.

| `EDGE_NAME` | Meaning |
|-------------|---------|
| `IS_COVERED_BY` | Person is the policyholder for this policy |
| `SOLD_POLICY` | Person is the writing agent (sold this policy) |

**Supplementary docs:** `docs__T_RESOLVED_PERSON_POLICY_CROSSWALK.txt`, `docs__writing_agent.txt` *(how to identify writing agents)*

---

### `T_RESOLVED_BUSINESS`
**File:** `ddl/Create_Table__T_RESOLVED_BUSINESS.sql`

De-duplicated business entity table. Covers care agencies, nursing homes, assisted living facilities, and other provider types. All business names are uppercase.

| Column | Type | Notes |
|--------|------|-------|
| `RES_BUSINESS_ID` | BIGINT | Primary key — FK across business crosswalk tables |
| `BUSINESS_NAME` | VARCHAR(200) | Uppercase |
| `TAX_ID` | VARCHAR(15) | |
| `BUSINESS_TYPE` | VARCHAR | `HHCA` (home health care agency), `NH` (nursing home), `ALF` (assisted living facility), `Insurance Agency`, `Medical Care Provider`, `Other Provider`, `External Vendor` |
| `DUNS_NUMBER` | VARCHAR(15) | D&B number |

**Supplementary docs:** `docs__T_RESOLVED_BUSINESS.txt`

---

### `T_RESOLVED_ADDRESS`
**File:** `ddl/Create_Table__T_RESOLVED_ADDRESS.sql`

Physical address records for persons and businesses. Latitude/longitude coordinates are available for a subset of records.

| Column | Type |
|--------|------|
| `RES_ADDRESS_ID` | BIGINT (PK) |
| `ADDRESS_LINE_1` / `ADDRESS_LINE_2` / `ADDRESS_LINE_3` | VARCHAR |
| `CITY` / `STATE` / `ZIP_CODE` | VARCHAR |
| `LATITUDE` / `LONGITUDE` | DECIMAL |

**Join paths:**
- To persons: `T_RESOLVED_PERSON_ADDRESS_CROSSWALK` on `RES_ADDRESS_ID`
- To businesses: `T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK` on `RES_ADDRESS_ID`

**Supplementary docs:** `docs__T_RESOLVED_ADDRESS.txt`

---

### `T_RESOLVED_PERSON_ADDRESS_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_ADDRESS_CROSSWALK.sql`

Links persons to their addresses. `EDGE_NAME` is always `'LOCATED_IN'`. Includes an `IS_LATEST_ADDRESS_IND` flag to identify the most current address.

| Column | Type |
|--------|------|
| `RES_PERSON_ID` | BIGINT |
| `EDGE_NAME` | VARCHAR(30) |
| `EFFECTIVE_DATE` | DATETIME |
| `IS_LATEST_ADDRESS_IND` | INT |
| `RES_ADDRESS_ID` | BIGINT |

**Supplementary docs:** `docs__T_RESOLVED_PERSON_ADDRESS_CROSSWALK.txt`

---

### `T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK.sql`

Links businesses to their addresses.

| Column | Type |
|--------|------|
| `RES_BUSINESS_ID` | BIGINT |
| `RES_ADDRESS_ID` | BIGINT |

---

### `T_RESOLVED_BUSINESS_PERSON_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_BUSINESS_PERSON_CROSSWALK.sql`

Connects a business to persons associated with it (e.g., individuals receiving care from a business). `EDGE_NAME` = `'RECEIVE_CARE_FROM'`.

**Supplementary docs:** `docs__T_RESOLVED_BUSINESS_PERSON_CROSSWALK.txt`

---

### `T_RESOLVED_PERSON_ELIGIBILITY_REVIEW_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_ELIGIBILITY_REVIEW_CROSSWALK.sql`

Links individual persons to eligibility reviews.

| `EDGE_NAME` | Meaning |
|-------------|---------|
| `RECEIVES_REVIEW` | Person is the provider who received the review |
| `ASSESS_ELIGIBILITY` | Person conducted the review |

**Supplementary docs:** `docs__T_RESOLVED_PERSON_Eligibility_Review_CROSSWALK.txt`

---

### `T_RESOLVED_BUSINESS_ELIGIBILITY_REVIEW_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_BUSINESS_ELIGIBILITY_REVIEW_CROSSWALK.sql`

Links business entities to eligibility reviews. `EDGE_NAME` = `'RECEIVES_REVIEW'`.

**Supplementary docs:** `docs__T_RESOLVED_BUSINESS_ELIGIBILITY_Review_CROSSWALK.txt`

---

## 3. Providers

These tables provide optimized, pre-computed lookups for provider-to-claim relationships and ICP work patterns.

---

### `INVESTIGAI_PROVIDER_CLAIMS`
**File:** `ddl/Create_Table__INVESTIGAI_PROVIDER_CLAIMS.sql`

Pre-computed provider-to-claim lookup table. Each row associates a single provider with a claim. Covers all provider types: ICP (individual caregiver), HHCA, NH, ALF, and other business providers. This is the preferred entry point for answering "who are the providers for claim X?" or "which claims did provider Y work on?"

| Column | Type | Notes |
|--------|------|-------|
| `PROVIDER_ID` | BIGINT | `RES_PERSON_ID` if ICP; `RES_BUSINESS_ID` if business provider |
| `PROVIDER_NAME` | VARCHAR(60) | Full name |
| `PROVIDER_TYPE` | VARCHAR | `ICP`, `HHCA`, `NH`, `ALF`, `Other Provider` |
| `CLAIM_NUMBER` | VARCHAR | Filter by claim using this field (not `CLAIM_ID`) |
| `CLAIM_STATUS_CODE` | VARCHAR | |
| `SERVICE_START_DATE` / `SERVICE_END_DATE` | DATE | Dates of first and last invoices for this provider on this claim |

**Join paths:**
- For ICP providers: `PROVIDER_ID` → `T_RESOLVED_PERSON` (via `RES_PERSON_ID`)
- For business providers: `PROVIDER_ID` → `T_RESOLVED_BUSINESS` (via `RES_BUSINESS_ID`)
- For provider addresses: see `T_RESOLVED_PERSON_ADDRESS_CROSSWALK` (ICPs) or `T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK` (businesses)

**Supplementary docs:** `docs__provider_query.txt` *(recommended join and filtering patterns for all provider types)*

---

### `INVESTIGAI_ICP_WORK_BLOCKS`
**File:** `ddl/Create_Table__INVESTIGAI_ICP_WORK_BLOCKS.sql`

Pre-computed continuous work blocks for ICP providers. Each row represents a stretch of consecutive days an ICP worked on a claim without any full-day gap. Derived from charge data in `T_NORM_CHARGE`.

| Column | Type | Notes |
|--------|------|-------|
| `WORK_BLOCK_ID` | VARCHAR(32) | Unique identifier for the work block |
| `PROVIDER_ID` | BIGINT | FK to `T_RESOLVED_PERSON` |
| `PROVIDER_NAME` | VARCHAR(60) | |
| `CLAIM_NUMBER` | VARCHAR | |
| `START_DATE` / `END_DATE` | DATE | Inclusive date range of the work block |
| `NUM_DAYS_WORKED` | INT | Number of days worked in this block |
| `CHARGE_AMT` | INT | Total charges billed during the block |

> ⚠️ **LIFEPRO claims** (`CLAIM_SYSTEM = 'LIFEPRO'`) do not have charge data in `T_NORM_CHARGE`, so work block analysis is not available for them.

**Supplementary docs:**
- `docs__icp_no_breaks.txt` *(guidance on no-break / consecutive day analysis)*
- `docs__multi_icp_overlap.txt` *(how to detect overlapping work periods between multiple ICPs)*

---

## 4. Caregiver App Sessions & Geolocation

This domain covers care sessions submitted through the caregiver mobile app by ICP providers, including geolocation check-in/check-out data and per-session ping events.

---

### `INVESTIGAI_ICP_CAREGIVER_APP_SESSIONS`
**File:** `ddl/Create_Table__INVESTIGAI_ICP_CAREGIVER_APP_SESSIONS.sql`

Primary denormalized table for ICP caregiver app activity. Each row is one care session. Consolidates session details, ICP identity, billing, geolocation, device IDs, and ping summary data into a single flat structure — making it the **preferred entry point** for most caregiver app questions.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CARE_SESSION_ID` | BIGINT | Primary key |
| `PROVIDER_ID` | BIGINT | FK to `T_RESOLVED_PERSON` |
| `PROVIDER_NAME` | VARCHAR(60) | Full ICP name — no join needed to display |
| `CLAIM_NUMBER` | VARCHAR | Filter by claim using this field (not `CLAIM_ID`) |
| `SESSION_START_TS` / `SESSION_END_TS` | TIMESTAMP | |
| `SESSION_TYPE` | VARCHAR | `Manual` or `Live` |
| `SESSION_SUBMISSION_STATUS` | VARCHAR | `Approved`, `Submitted`, `Denied`, `Denied-Deleted`, `Not Submitted` |
| `SESSION_REJECTION_COMMENTS` | VARCHAR | Free-text rejection reason |
| `NUM_HOURS` / `HOURLY_RATE` / `CHARGE_AMT` | DECIMAL | Session billing info |
| `CHECK_IN_DEVICE_ID` / `CHECK_OUT_DEVICE_ID` | VARCHAR(50) | Device identifiers at check-in and check-out |
| `CHECK_IN_LATITUDE` / `CHECK_IN_LONGITUDE` | DECIMAL | Check-in geolocation |
| `CHECK_OUT_LATITUDE` / `CHECK_OUT_LONGITUDE` | DECIMAL | Check-out geolocation |
| `CHECK_IN_CHECK_OUT_DISTANCE_IN_MILES` | DECIMAL | Straight-line distance between check-in and check-out |
| `CHECK_IN_DISTANCE_TO_CLOSEST_ADDRESS_IN_MILES` | DECIMAL | Distance from check-in to the closest policyholder address |
| `CHECK_OUT_DISTANCE_TO_CLOSEST_ADDRESS_IN_MILES` | DECIMAL | Distance from check-out to the closest policyholder address |
| `CHECK_IN_CLOSEST_ADDRESS_ID` | BIGINT | FK to `T_RESOLVED_ADDRESS` — policyholder address closest to check-in |
| `CHECK_OUT_CLOSEST_ADDRESS_ID` | BIGINT | FK to `T_RESOLVED_ADDRESS` — policyholder address closest to check-out |
| `NUM_PINGS` | INT | Count of geolocation pings recorded during session |
| `MAX_PING_DISTANCE_TO_CHECK_IN_MILES` | DECIMAL | Max distance of any ping from the check-in location |
| `MAX_PING_DISTANCE_TO_CHECK_OUT_MILES` | DECIMAL | Max distance of any ping from the check-out location |

**Supplementary docs:**
- `docs__INVESTIGAI_ICP_CAREGIVER_APP_SESSIONS.txt` *(comprehensive field-level guidance and recommended usage patterns)*
- `docs__care_session_listings.txt` *(how to list sessions for a claim or provider)*
- `docs__geolocation_enabled.txt` *(how to identify sessions with geolocation data)*
- `docs__hourly_rate.txt` *(how to query hourly rates across sessions)*
- `docs__session_address_distance.txt` *(how to use precomputed distance fields and when to fall back to haversine)*
- `docs__icp_shared_device_ids.txt` *(detecting shared device IDs across ICPs on a claim)*

---

### `T_NORM_CARE_SESSION`
**File:** `ddl/Create_Table__T_NORM_CARE_SESSION.sql`

Normalized caregiver session records from the app. Use this table (instead of `INVESTIGAI_ICP_CAREGIVER_APP_SESSIONS`) when ADL activity columns are needed.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CARE_SESSION_ID` | INT | Primary key |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` |
| `SESSION_START_LOCAL_TS` / `SESSION_END_LOCAL_TS` | DATETIME | |
| `SESSION_TYPE` | VARCHAR | `Manual` or `Live` |
| `SUBMISSION_STATUS` | VARCHAR | |
| `NUM_HOURS` / `HOURLY_RATE` / `CHARGE_AMT` | Various | |
| `CHECK_IN_DEVICE_ID` / `CHECK_OUT_DEVICE_ID` | VARCHAR(50) | |
| `ADL_BATHING`, `ADL_DRESSING`, `ADL_EATING`, `ADL_TOILETING`, `ADL_TRANSFERRING`, `ADL_CONTINENCE`, `ADL_SUPERVISION`, `ADL_OTHER` | INT | 0/1 flags per Activities of Daily Living type |
| `ADL_VALUE_FOR_OTHER` | VARCHAR | Describes the care type when `ADL_OTHER = 1` |

**Supplementary docs:** `docs__T_NORM_CARE_SESSION.txt`

---

### `T_NORM_CARE_SESSION_EVENT`
**File:** `ddl/Create_Table__T_NORM_CARE_SESSION_EVENT.sql`

Per-ping geolocation events within a care session. Each row is one automatic app ping during an active session. Not all sessions will have ping events.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CARE_SESSION_EVENT_ID` | BIGINT | Primary key |
| `NORM_CARE_SESSION_ID` | INT | FK to `T_NORM_CARE_SESSION` |
| `EVENT_LOCAL_TS` | DATETIME | Ping timestamp |
| `EVENT_TYPE` | VARCHAR | `EXIT`, `ENTER`, `BACKGROUND_GEO_LOCATION_TRACKING_INTERVAL`, `APP_FOREGROUND_LOCATION` |
| `SOURCE_SYSTEM` | VARCHAR(50) | |

**Join paths:**
- To geolocation: `NORM_CARE_SESSION_EVENT_ID` → `T_RESOLVED_CARE_SESSION_EVENT_GEOLOCATION_CROSSWALK` → `T_RESOLVED_GEOLOCATION`

**Supplementary docs:** `docs__T_NORM_CARE_SESSION_EVENT.txt`

---

### `T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK.sql`

Links care sessions to their check-in and check-out geolocations.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CARE_SESSION_ID` | INT | FK to `T_NORM_CARE_SESSION` |
| `RES_GEOLOCATION_ID` | BIGINT | FK to `T_RESOLVED_GEOLOCATION` |
| `EVENT_TYPE` | VARCHAR | `GEO_CHECK_IN` or `GEO_CHECK_OUT` |
| `EVENT_DATETIME` | DATETIME | Timestamp of the check-in or check-out |

**Supplementary docs:** `docs__T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK.txt`

---

### `T_RESOLVED_CARE_SESSION_EVENT_GEOLOCATION_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_CARE_SESSION_EVENT_GEOLOCATION_CROSSWALK.sql`

Links individual ping events (`T_NORM_CARE_SESSION_EVENT`) to their resolved geolocations.

| Column | Type |
|--------|------|
| `NORM_CARE_SESSION_EVENT_ID` | BIGINT |
| `RES_GEOLOCATION_ID` | BIGINT |

---

### `T_RESOLVED_GEOLOCATION`
**File:** `ddl/Create_Table__T_RESOLVED_GEOLOCATION.sql`

Resolved latitude/longitude coordinates referenced by both session-level check-in/out and per-ping events.

| Column | Type |
|--------|------|
| `RES_GEOLOCATION_ID` | BIGINT (PK) |
| `LATITUDE` | FLOAT |
| `LONGITUDE` | FLOAT |

**Supplementary docs:** `docs__T_RESOLVED_Geolocation.txt`

---

### `T_RESOLVED_PERSON_CARE_SESSION_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_CARE_SESSION_CROSSWALK.sql`

Links ICP providers (persons) to care sessions. `EDGE_NAME` is always `'PROVIDED_CARE_ON_SESSION'`.

| Column | Type |
|--------|------|
| `RES_PERSON_ID` | BIGINT |
| `EDGE_NAME` | VARCHAR(24) |
| `NORM_CARE_SESSION_ID` | INT |

**Supplementary docs:** `docs__T_RESOLVED_PERSON_CARE_Session_CROSSWALK.txt`

---

### `V_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK` *(View)*
**File:** `ddl/Create_View__V_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK.sql`

A pre-joined view combining care session details with check-in and check-out geolocations. Useful for geolocation-focused session queries without needing to join the underlying crosswalk and geolocation tables manually.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CARE_SESSION_ID` | INT | |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` |
| `SESSION_START_LOCAL_TS` / `SESSION_END_LOCAL_TS` | DATETIME | |
| `NUM_HOURS` / `HOURLY_RATE` / `CHARGE_AMT` | Various | |
| `SUBMISSION_STATUS` | VARCHAR | |
| `CHECK_IN_DEVICE_ID` / `CHECK_OUT_DEVICE_ID` | VARCHAR(50) | |
| `CHECK_IN_GEO_ID` / `CHECK_OUT_GEO_ID` | BIGINT | FK to `T_RESOLVED_GEOLOCATION` |
| `CHECK_IN_LATITUDE` / `CHECK_IN_LONGITUDE` | FLOAT | |
| `CHECK_OUT_LATITUDE` / `CHECK_OUT_LONGITUDE` | FLOAT | |
| `CHECK_IN_CHECK_OUT_DISTANCE` | FLOAT | Distance in miles |

---

## 5. Clinical Reviews & Diagnoses

---

### `T_NORM_CLINICAL_REVIEW`
**File:** `ddl/Create_Table__T_NORM_CLINICAL_REVIEW.sql`

Clinical assessments for claimants. Each row is one review period for a claim. A claimant can have multiple reviews over time; the most recent is identified by `MAX(START_DATE)` for that `CLAIM_ID`.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CLINICAL_REVIEW_ID` | BIGINT | Primary key |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` |
| `START_DATE` / `END_DATE` | DATE | Review period; `END_DATE` starting with `9999` indicates *no-touch* status |
| `MMSE_SCORE` | INT | 0–30 cognitive score; ≤ 23 generally indicates impairment |
| `COG_IMPAIRMENT` | INT | `0/1` flag |
| `CR_APPROVED_IND` | INT | `0/1` flag — whether this review was approved |
| `MEDICAL_NECESSITY` | VARCHAR | |
| `ILLNESS_OR_INJURY` | VARCHAR | Primary condition driving the care need |
| `EDUCATIONAL_LEVEL` | VARCHAR | |
| `BATHING_ASSIST_TYPE` / `BATHING_FREQ` | VARCHAR | ADL assistance type and frequency |
| `DRESSING_ASSIST_TYPE` / `DRESSING_FREQ` | VARCHAR | |
| `EATING_ASSIST_TYPE` / `EATING_FREQ` | VARCHAR | |
| `TOILETING_ASSIST_TYPE` / `TOILETING_FREQ` | VARCHAR | |
| `TRANSFERRING_ASSIST_TYPE` / `TRANSFERRING_FREQ` | VARCHAR | |
| `CONTINENCE_ASSIST_TYPE` / `CONTINENCE_FREQ` | VARCHAR | |
| `AMBULATION_ASSIST_TYPE` / `AMBULATION_FREQ` | VARCHAR | |

**Supplementary docs:**
- `docs__T_NORM_CLINICAL_REVIEW.txt` *(field-level descriptions)*
- `docs__COG_impairment.txt` *(how to determine current cognitive impairment status)*
- `docs__no_touch.txt` *(how to identify no-touch claimants via `END_DATE`)*
- `docs__clinical_review_listings.txt` *(recommended column selection and paging when listing reviews)*

---

### `T_NORM_DIAGNOSIS`
**File:** `ddl/Create_Table__T_NORM_DIAGNOSIS.sql`

Individual diagnosis records per claim. A claim can have multiple diagnoses.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_DIAGNOSIS_ID` | BIGINT | Primary key |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` |
| `SOURCE_SYSTEM` | VARCHAR(50) | |
| `ICD9_CODE` / `ICD9_DSC` | VARCHAR | ICD-9 code and description |
| `ICD10_CODE` | VARCHAR | ICD-10 code (preferred for recent records) |
| `DIAGNOSIS_TYPE` | VARCHAR | e.g., `Debilitating`, `Preexisting`, `Precipitating` |
| `PROGNOSIS_DSC` | VARCHAR | Prognosis description |
| `DX_CATEGORY` | VARCHAR | High-level grouping (e.g., `cancer`, `parkinson`) |

**Supplementary docs:** `docs__T_NORM_Diagnosis.txt`

---

## 6. Billing & Payments

This domain covers the invoicing, charge line items, payment transactions, and bank account associations for claims.

---

### `T_NORM_INVOICE`
**File:** `ddl/Create_Table__T_NORM_INVOICE.sql`

Invoice records per claim. Each invoice covers a care service period and is associated with one claim. Multiple charges and payments can be linked to a single invoice.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_INVOICE_ID` | BIGINT | Primary key |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` |
| `INVOICE_RECEIVED_DATE` | TIMESTAMP | Use this as "invoice date" for filtering |
| `INVOICE_STATUS` | VARCHAR | |
| `INVOICE_SERVICE_START_DATE` / `INVOICE_SERVICE_END_DATE` | DATE | Service period covered; earliest `INVOICE_SERVICE_START_DATE` per claim = start of care |
| `INVOICE_CHARGE_AMT` / `INVOICE_PAY_AMT` | DECIMAL | Total billed vs. total paid |
| `PORTAL_TOTAL_HOURS` | FLOAT | Total hours worked for charges on this invoice |
| `PORTAL_MIN_HOURLY_RATE` / `PORTAL_MAX_HOURLY_RATE` | DECIMAL | Hourly rate range for this invoice |
| `PORTAL_CARE_SETTING` | VARCHAR | Care setting, if available |

**Supplementary docs:**
- `docs__T_NORM_INVOICE.txt`
- `docs__invoice_listings.txt` *(how to list invoices with provider and status information)*
- `docs__start_of_care.txt` *(deriving start-of-care date from earliest invoice service date)*
- `docs__payments.txt` *(payment amount lookups and join paths to bank accounts)*

---

### `T_NORM_CHARGE`
**File:** `ddl/Create_Table__T_NORM_CHARGE.sql`

Individual charge line items on an invoice. One invoice can have many charge records.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_CHARGE_ID` | BIGINT | Primary key |
| `NORM_INVOICE_ID` | INT | FK to `T_NORM_INVOICE` |
| `CHARGE_DATE` | DATE | Date the care service was rendered |
| `CHARGE_AMT` | DECIMAL | Billed amount for this line item |
| `PAYMENT_AMT` | DECIMAL | Amount approved for payment (may differ if partially approved) |

---

### `T_NORM_PAYMENT`
**File:** `ddl/Create_Table__T_NORM_PAYMENT.sql`

Payment transactions per claim. Each row is a single payment issued for a claim.

| Column | Type | Notes |
|--------|------|-------|
| `NORM_PAYMENT_ID` | BIGINT | Primary key |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` |
| `PAYMENT_DATE` | DATE | |
| `PAYMENT_AMT` | DECIMAL(18,2) | Amount paid |
| `PAYMENT_STATUS` | VARCHAR | |

**Join paths:**
- To bank account: `NORM_PAYMENT_ID` → `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK` → `T_RESOLVED_BANK_ACCOUNT`

---

### `T_RESOLVED_BANK_ACCOUNT`
**File:** `ddl/Create_Table__T_RESOLVED_BANK_ACCOUNT.sql`

Resolved bank account records (routing and account numbers).

| Column | Type |
|--------|------|
| `RES_BANK_ACCOUNT_ID` | BIGINT (PK) |
| `ROUTING_NUMBER` | VARCHAR(25) |
| `ACCOUNT_NUMBER` | VARCHAR(25) |

---

### `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK.sql`

Links payment records to the bank account that received them.

| Column | Type |
|--------|------|
| `NORM_PAYMENT_ID` | INT |
| `RES_BANK_ACCOUNT_ID` | BIGINT |

---

### `T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK.sql`

Links persons to the bank accounts they hold. `EDGE_NAME` = `'HOLD_BY'`.

| Column | Type |
|--------|------|
| `RES_BANK_ACCOUNT_ID` | INT |
| `EDGE_NAME` | VARCHAR(30) |
| `RES_PERSON_ID` | BIGINT |

---

### `T_RESOLVED_PERSON_INVOICE_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_PERSON_INVOICE_CROSSWALK.sql`

Links individual persons (ICP caregivers) to invoices.

| `EDGE_NAME` | Meaning |
|-------------|---------|
| `PROVIDED_CARE_ON_INVOICE` | Person (ICP) was the care provider for this invoice |
| `ASSESS_INVOICE` | Person assessed or reviewed the invoice |

**Supplementary docs:** `docs__T_RESOLVED_PERSON_Invoice_CROSSWALK.txt`

---

### `T_RESOLVED_BUSINESS_INVOICE_CROSSWALK`
**File:** `ddl/Create_Table__T_RESOLVED_BUSINESS_INVOICE_CROSSWALK.sql`

Links business entities (agencies, facilities) to invoices. `EDGE_NAME` = `'PROVIDED_CARE_ON_INVOICE'`.

> Use `T_RESOLVED_PERSON_INVOICE_CROSSWALK` for invoices submitted by individual ICPs; use this table for invoices submitted by business providers.

**Supplementary docs:** `docs__T_RESOLVED_Business_Invoice_CROSSWALK.txt`

---

## 7. Review Cycles & Audit Workflow

This domain covers the investigation and audit workflow applied to claims, including the fraud signal metrics evaluated during each cycle and any financial recovery actions taken.

---

### `T_NORM_REVIEW_CYCLE`
**File:** `ddl/Create_Table__T_NORM_REVIEW_CYCLE.sql`

Each row represents one investigation cycle for a claim. A claim can have multiple review cycles over time. Use `LAST_REVIEW_CYCLE_IND = 1` to get the most recent cycle. Notably, `CLAIM_NUMBER` is available directly in this table — no join to `T_NORM_CLAIM` is needed for claim-number filtering.

| Column | Type | Notes |
|--------|------|-------|
| `REVIEW_CYCLE_ID` | INT | Primary key |
| `CLAIM_NUMBER` | VARCHAR(60) | Use directly in `WHERE` — no join needed |
| `CLAIM_ID` | VARCHAR(15) | FK to `T_NORM_CLAIM` (if joining for other claim data) |
| `POLICY_NUMBER` | VARCHAR | |
| `USER_NAM` / `USER_ROLE_NAM` | VARCHAR | Assigned investigator and their role |
| `REFERRAL_SOURCE_NAME` | VARCHAR | `BIU Referral`, `Data Driven Referral`, `Pilot Referral`, `Manual Referral` |
| `REFERRAL_SUB_SOURCE_NAME` | VARCHAR | More granular referral source (e.g., specific rule name) |
| `STATUS_NAM` | VARCHAR | `Assign`, `Evaluate`, `Investigate`, `Remediate` |
| `SUB_STATUS_NAM` | VARCHAR | `Clear` = case closed with no fraud found |
| `SUB_STATUS_DETAILS` | VARCHAR | Additional explanation for sub-status |
| `REVIEW_CYCLE_START_DATE` | TIMESTAMP | |
| `REVIEW_CYCLE_END_DATE` | DATE | Never `NULL` even if the cycle is still ongoing |
| `DEMAND_AMT` | DECIMAL | Dollar amount demanded for recovery when remediated |
| `REVIEW_CYCLE_COMPLETE_IND` | INT | `0/1` flag |
| `LAST_REVIEW_CYCLE_IND` | INT | `0/1` flag — filter on `1` to get current cycle |
| `SUMMARY_TXT` / `COMMENT_TXT` | VARCHAR | Investigator notes and free-text findings |

**Supplementary docs:** `docs__review_cycles.txt` *(status semantics, recommended ordering/filtering patterns)*

---

### `T_NORM_REVIEW_CYCLE_METRIC`
**File:** `ddl/Create_Table__T_NORM_REVIEW_CYCLE_METRIC.sql`

Fraud signal and compliance metric evaluations within a review cycle. One cycle can have multiple metrics, each representing a different fraud indicator or compliance dimension assessed during the investigation.

| Column | Type | Notes |
|--------|------|-------|
| `REVIEW_CYCLE_METRIC_ID` | INT | Primary key |
| `REVIEW_CYCLE_ID` | INT | FK to `T_NORM_REVIEW_CYCLE` |
| `METRIC_ID` | DECIMAL(15,3) | |
| `METRIC_NAM` / `METRIC_DSC` | VARCHAR | Name and description of the metric |
| `METRIC_TYPE_NAM` | VARCHAR | Category/type of metric |
| `SEVERITY` | VARCHAR | Severity level |
| `INITIAL_SOURCE_IND` | INT | `0/1` — `1` = this metric triggered the original referral |
| `CLEAR_REASONS` | VARCHAR | Explanation when a metric is cleared/resolved |

---

### `T_NORM_REVIEW_CYCLE_REMEDIATION`
**File:** `ddl/Create_Table__T_NORM_REVIEW_CYCLE_REMEDIATION.sql`

Remediation actions associated with a review cycle — created when the investigation identifies fraud or issues requiring financial recovery. One review cycle can have multiple remediation records.

| Column | Type | Notes |
|--------|------|-------|
| `REVIEW_CYCLE_REMEDIATION_ID` | INT | Primary key |
| `REVIEW_CYCLE_ID` | INT | FK to `T_NORM_REVIEW_CYCLE` |
| `REQUESTED_AMT` | DECIMAL | Amount formally requested for recovery |
| `ACTUAL_RECOVERED_AMT` | DECIMAL | Amount actually recovered to date |
| `ESTIMATED_RECOVERED_AMT` | DECIMAL | Projected total recovery |
| `UNRECOVERABLE_AMT` | DECIMAL | Portion deemed unrecoverable |
| `ACTUARIAL_SAVINGS` | DECIMAL | Broader cost avoidance beyond direct recovery |
| `SOCIAL_MEDIA_FLAG_IND` | INT | `0/1` — associated social media finding |
| `MANAGEMENT_SUMMARY_TXT` | VARCHAR | Summary of findings, actions, and outcomes |

---

## Key Join Paths

The table below summarizes the most common join patterns across the schema:

| From | Join Column | To | Notes |
|------|-------------|-----|-------|
| `T_NORM_CLAIM` | `POLICY_NUMBER` | `T_NORM_POLICY` | |
| `T_NORM_CLAIM` | `CLAIM_ID` | Most `T_NORM_*` tables | Core FK for the normalized layer |
| `T_NORM_CLAIM` → `T_RESOLVED_PERSON_POLICY_CROSSWALK` (POLICY_NUMBER, `IS_COVERED_BY`) | `RES_PERSON_ID` | `T_RESOLVED_PERSON` | Policyholder lookup |
| `T_NORM_INVOICE` | `NORM_INVOICE_ID` | `T_NORM_CHARGE`, `T_NORM_PAYMENT` | Billing breakdown |
| `T_NORM_INVOICE` → `T_RESOLVED_PERSON_INVOICE_CROSSWALK` | `RES_PERSON_ID` | `T_RESOLVED_PERSON` | ICP provider on invoice |
| `T_NORM_INVOICE` → `T_RESOLVED_BUSINESS_INVOICE_CROSSWALK` | `RES_BUSINESS_ID` | `T_RESOLVED_BUSINESS` | Business provider on invoice |
| `T_NORM_PAYMENT` → `T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK` | `RES_BANK_ACCOUNT_ID` | `T_RESOLVED_BANK_ACCOUNT` | Payment → bank account |
| `T_RESOLVED_PERSON` → `T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK` | `RES_BANK_ACCOUNT_ID` | `T_RESOLVED_BANK_ACCOUNT` | Person → bank account |
| `T_RESOLVED_PERSON` → `T_RESOLVED_PERSON_ADDRESS_CROSSWALK` | `RES_ADDRESS_ID` | `T_RESOLVED_ADDRESS` | Person's address(es) |
| `T_RESOLVED_BUSINESS` → `T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK` | `RES_ADDRESS_ID` | `T_RESOLVED_ADDRESS` | Business address |
| `T_NORM_CARE_SESSION` | `NORM_CARE_SESSION_ID` | `T_NORM_CARE_SESSION_EVENT`, `T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK`, `T_RESOLVED_PERSON_CARE_SESSION_CROSSWALK` | |
| `T_NORM_CARE_SESSION_EVENT` → `T_RESOLVED_CARE_SESSION_EVENT_GEOLOCATION_CROSSWALK` | `RES_GEOLOCATION_ID` | `T_RESOLVED_GEOLOCATION` | Ping coordinates |
| `T_NORM_REVIEW_CYCLE` | `REVIEW_CYCLE_ID` | `T_NORM_REVIEW_CYCLE_METRIC`, `T_NORM_REVIEW_CYCLE_REMEDIATION` | |
| `T_NORM_ELIGIBILITY_REVIEW` → `T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK` | `CLAIM_ID` | `T_NORM_CLAIM` | Review → claim |
| `T_NORM_ELIGIBILITY_REVIEW` → `T_RESOLVED_PERSON_ELIGIBILITY_REVIEW_CROSSWALK` | `RES_PERSON_ID` | `T_RESOLVED_PERSON` | ICP under review |
| `T_NORM_ELIGIBILITY_REVIEW` → `T_RESOLVED_BUSINESS_ELIGIBILITY_REVIEW_CROSSWALK` | `RES_BUSINESS_ID` | `T_RESOLVED_BUSINESS` | Business under review |

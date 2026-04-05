# PoC v1 — Named demo scenarios

These four scenarios are grounded in the **synthetic seed** under `data/interim/poc_v1_seed`. After `build_graph_files.py`, the Streamlit app and `query_graph` helpers surface the same patterns.

Use this as a **presenter cheat sheet**: what to ask, what should light up, and what a strong answer sounds like.

---

## 1. “The agent on the claim”

**Scenario**  
A long-term care policy has several open claims in a short window. One claimant is the **same person** who appears in the system as the **writing agent** for that policy.

**Entities involved**

| Role | Seed / graph touchpoints |
|------|---------------------------|
| Policy | `POL-LTC-10001` → `policy_POL-LTC-10001` |
| Claims | `CLM-2024-00091` (Jane Doe), `CLM-2024-00102` (Maria Garcia), `CLM-2024-00115` (Robert Chen) |
| People | Maria Garcia (`person_5003`) — **SOLD_POLICY** on `POL-LTC-10001` and **claimant** on `CLM-2024-00102`; Jane & John Doe as insureds on the same policy |

**Investigation question to ask**  
- *“Show me the network around claim **CLM-2024-00102** / Maria Garcia’s claim.”*  
- In the prototype: `get_claim_network("claim_C9000000002")` or the app’s **claim network** / natural-language route for that claim.

**Suspicious pattern to make visible**  
- **Claim concentration**: multiple claims filed **against the same policy**.  
- **Role overlap**: someone tied to the policy as **agent** also **matches the claimant** on a linked claim (conflict-of-interest / self-dealing angle for SIU).

**What a good demo answer should mention**  
- The claim ties to **one policy** and lists **other claims** on that policy.  
- **Insureds vs agent** on the policy (covered lives vs writing agent).  
- Plain-language **“why”**: the graph links claim → policy → people; the **claimant resolved to the same person** who **sold** the policy — worth an SIU look even in a synthetic story.

---

## 2. “Same bank account, different mailboxes”

**Scenario**  
Two unrelated-looking individuals are both **holders** of the same bank account, but their **registered addresses** differ. That combination often triggers a quick fraud or proceeds-diversion review.

**Entities involved**

| Role | Seed / graph touchpoints |
|------|---------------------------|
| Account | `****9921` / `bank_8001` |
| Holders | Jane Doe (`person_5001`) — Boston; Sam Lee (`person_5005`) — Quincy |
| Addresses | `100 MAPLE ST, BOSTON` (`address_9001`) vs `200 HARBOR RD, QUINCY` (`address_9002`) |

**Investigation question to ask**  
- *“Who shares bank accounts in this book of business? Anywhere holders aren’t at the same address?”*  
- In the prototype: `find_shared_bank_accounts()` or the **shared bank** demo / routed query.

**Suspicious pattern to make visible**  
- **Multi-holder** `HOLD_BY` edges on one **BankAccount**.  
- **Two distinct** `LOCATED_IN` addresses for those holders (non-household-style sharing in the narrative).

**What a good demo answer should mention**  
- The **account** and **both people** by name (or node id).  
- That they share an account **but** map to **different** addresses — the demo copy should call that out as the risk hook.  
- Supporting links: person → bank (`HOLD_BY`) and person → address (`LOCATED_IN`).

---

## 3. “The claims sit on a family web”

**Scenario**  
Several claims and insureds look unrelated in claim screens, but **person–person** links (spouse, family) connect claimants and insureds into **one relationship cluster**.

**Entities involved**

| Relationship | Seed |
|--------------|------|
| Spouse | Jane Doe (`5001`) ↔ John Doe (`5002`) — `IS_SPOUSE_OF` |
| Family | John Doe ↔ Robert Chen (`5004`) — `IS_RELATED_TO` / cousin; Maria Garcia (`5003`) ↔ Jane Doe — `IS_RELATED_TO` / sister |
| Claims context | Jane, Maria, and Robert each have claims on **`POL-LTC-10001`**; John is insured on both LTC policies |

**Investigation question to ask**  
- *“Map family or social ties between people in the graph — who clusters together?”*  
- In the prototype: `find_related_people_clusters()` or the **people clusters** route.

**Suspicious pattern to make visible**  
- **One large connected component** (four people in the seed) built only from spouse / related-to edges — not obvious from a single claim file.  
- Overlap with **policy / claim** story: the cluster includes **multiple names** that also appear around the concentrated LTC policy (good bridge talking point after scenario 1).

**What a good demo answer should mention**  
- There is **one main cluster** (size 4) vs isolated individuals if you add more seed later.  
- **Who links to whom** (spouse line, cousin, sister) in plain English.  
- Why it matters: **coordinated activity** or **undisclosed relationships** are easier to argue when the graph shows the **same network** touching multiple claims or insureds.

---

## 4. “Care business at the insureds’ address”

**Scenario**  
A **home-care agency** is registered at a **street address** that **matches** where multiple **insureds / claimants** live in the resolved person file — a classic PoC pattern for related-party or inflated-services storylines.

**Entities involved**

| Role | Seed / graph touchpoints |
|------|---------------------------|
| Business | **RESOLVE CARE HHCA LLC** → `business_7001` |
| Shared address | `100 MAPLE ST, BOSTON` → `address_9001` |
| People at that address | Jane Doe, John Doe, Maria Garcia, Robert Chen (`person_5001`–`5004`) — all `LOCATED_IN` `9001` |

**Investigation question to ask**  
- *“Do any businesses share an address with our people — especially care or agency types?”*  
- In the prototype: `find_business_connection_patterns()` or the **business patterns** demo.

**Suspicious pattern to make visible**  
- **Business** `LOCATED_IN` → **Address** ← `LOCATED_IN` — **Person** (same address node).  
- Multiple **people** colocated with one **HHCA**-type business in the seed.

**What a good demo answer should mention**  
- The **business name** and **address** in everyday language.  
- **How many people** share that address with the business in this extract.  
- Framing: not proof of fraud — a **lead** for SIU (related-party care, commingling, or data quality), which keeps the demo credible.

---

## 5. “Billing shop at the claimant’s mailbox”

**Scenario**  
A **medical billing company** is registered at the **same suite address** as two individuals who are **business partners**, **share a bank account**, and sit on opposite sides of a **claim** (one is the **insured**, the other is the **claimant** on the same policy). In a real review this would be a **related-party / commingling / billing integrity** lead—not proof of wrongdoing.

**Entities involved**

| Role | Seed / graph touchpoints |
|------|---------------------------|
| Policy | `POL-LTC-10003` → `policy_POL-LTC-10003` |
| Claim | `CLM-2024-00240` → `claim_C9000000005` (claimant **Pat Kim**) |
| People | **Alan Webb** (`person_5006`) — insured on `POL-LTC-10003`; **Pat Kim** (`person_5007`) — claimant; `IS_RELATED_TO` **BUSINESS_PARTNER**; joint **`HOLD_BY`** on `bank_8004` |
| Business | **APEX MEDICAL BILLING LLC** → `business_7003` |
| Shared address | `88 COMMERCE WAY, LYNN` → `address_9004` — business + both people `LOCATED_IN` |

**Investigation question to ask**  
- *“Show the network for claim **CLM-2024-00240** / **claim_C9000000005**.”*  
- *“Any businesses at the same address as multiple people?”* → should list **APEX** with Alan and Pat.  
- *“Shared bank accounts?”* → includes **8004** (same household address for both holders in this seed).

**Suspicious pattern to make visible**  
- **Colocation:** billing entity and **both** parties tied to the claim share **one address**.  
- **Shared rails:** same **bank account** between two people already linked as partners.  
- **Claim context:** insured vs claimant on one policy tightens the story for SIU narrative.

**What a good demo answer should mention**  
- Claim → policy → **insured** vs **resolved claimant**; optional mention of **partner** edge and **shared bank** from the subgraph / evidence bullets.

**Which prototype query surfaces it (primary)**  
- **`find_business_connection_patterns()`** — flags `business_7003` with **two people** at `address_9004`.  
- **`get_claim_network("claim_C9000000005")`** — shows the claim, policy, insured link, and claimant match to Pat Kim (subgraph pulls in ids from tables).  
- **`find_shared_bank_accounts()`** — shows **`bank_8004`** with two holders (same address in this extract).  
- **`find_related_people_clusters()`** — Alan and Pat appear as a **size-2** cluster (partner edge).

---

## Quick reference — prototype hooks

| # | Scenario (short) | Primary query |
|---|------------------|----------------|
| 1 | Agent / claimant overlap + busy policy | `get_claim_network("claim_C9000000002")` |
| 2 | Shared bank, different addresses | `find_shared_bank_accounts()` |
| 3 | Family cluster touching LTC claims | `find_related_people_clusters()` |
| 4 | HHCA business colocated with people | `find_business_connection_patterns()` |
| 5 | Billing company + partners + claim (Lynn / 9004) | `find_business_connection_patterns()`; also `get_claim_network("claim_C9000000005")` |

Rebuild the graph from seed after CSV changes: `python src/graph_build/build_graph_files.py`.

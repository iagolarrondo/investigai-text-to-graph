# PoC v1 — demo investigation questions

Short list of **concrete questions** the v1 graph (built from `data/interim/poc_v1_seed/`) should support. Each item maps to patterns encoded in the synthetic seed so a demo can show **real paths** in `nodes.csv` / `edges.csv`.

---

## 1. Is anyone both selling the policy and claiming on it?

**Plain English:** For a given policy, is there a person who appears as a **writing agent** and also as a **claimant** on a claim tied to that same policy?

**Why it matters for fraud investigation:** Agent involvement on business the agent placed can indicate **conflicts of interest**, **undisclosed relationships**, or **self-dealing**. It is a common SIU and compliance escalation trigger when the same individual wears both sales and claimant hats on one contract.

**Graph objects it likely uses:** `Person` nodes, `Policy` nodes, `Claim` nodes; edges `SOLD_POLICY` (person → policy), `IS_CLAIM_AGAINST_POLICY` (claim → policy). Claimant identity on the `Claim` node comes from `properties_json` (`FIRST_NAME`, `LAST_NAME`, `BIRTH_DATE`) aligned with `T_RESOLVED_PERSON` in the seed.

**Expected result (this seed):** **Maria Garcia (person_5003)** has `SOLD_POLICY` to **policy_POL-LTC-10001** and is the claimant on open claim **claim_C9000000002**, which links to the same policy via `IS_CLAIM_AGAINST_POLICY`. The demo should surface that single policy as the overlap point.

---

## 2. Which policies carry unusually concentrated open claim activity?

**Plain English:** Which **policy** nodes have **multiple open claims** attached, and who are the claimants (by person or by claim record)?

**Why it matters for fraud investigation:** Many **open, valid claims** on one policy in a short window can drive **severity and reserving** concerns, **coordination** suspicions, or **provider / billing** schemes. Graph view makes **fan-in to one policy** obvious compared to scanning claim rows alone.

**Graph objects it likely uses:** `Policy`, `Claim`; edge `IS_CLAIM_AGAINST_POLICY`. Optional: join claimant attributes on `Claim` to `Person` for naming.

**Expected result (this seed):** **policy_POL-LTC-10001** has **three** open claims (**claim_C9000000001** Jane Doe, **claim_C9000000002** Maria Garcia, **claim_C9000000003** Robert Chen). **policy_POL-LTC-10002** has one closed claim (John Doe). The PoC should highlight **POL-LTC-10001** as the concentrated hub.

---

## 3. Do any people share a bank account but live at different addresses?

**Plain English:** Find **pairs of people** who both **HOLD_BY** the same **BankAccount** while their **LOCATED_IN** (latest) addresses differ.

**Why it matters for fraud investigation:** Shared accounts across **non-household** or **geographically separated** parties can suggest **proceeds sharing**, **straw payees**, or **third-party payment diversion**. It is a classic link-analysis pattern when combined with claim or policy context.

**Graph objects it likely uses:** `Person`, `BankAccount`, `Address`; edges `HOLD_BY` (person → bank account), `LOCATED_IN` (person → address).

**Expected result (this seed):** **person_5001** (Jane Doe) and **person_5005** (Sam Lee) both connect to **bank_8001** via `HOLD_BY`. Jane is at **address_9001** (100 Maple St, Boston); Sam is at **address_9002** (200 Harbor Rd, Quincy). The demo should return this pair and the shared account id **8001**.

---

## 4. Is a care provider business located at the same address as multiple insureds or claimants?

**Plain English:** Is any **Business** (e.g. home health agency) **LOCATED_IN** the same **Address** as **multiple people** who are tied to the policy/claim story (insureds, claimants, or household)?

**Why it matters for fraud investigation:** **Colocation** of a billing or care entity with claimants or insureds can flag **related-party arrangements**, **kickback**, or **facility / address manipulation** (depending on line of business). Even when innocent, it is a standard **network proximity** question for investigators.

**Graph objects it likely uses:** `Business`, `Address`, `Person`; edges `LOCATED_IN` for business → address and person → address.

**Expected result (this seed):** **business_7001** (RESOLVE CARE HHCA LLC) is at **address_9001**. **person_5001**, **person_5002**, **person_5003**, and **person_5004** are also **LOCATED_IN** **address_9001**. Several of those people are insured on **POL-LTC-10001** and/or have claims on that policy. The demo should show **one address** linking the HHCA entity and four people.

---

*These questions are scoped to PoC v1; extend with payment, care session, or eligibility subgraphs when those tables are wired into the build.*

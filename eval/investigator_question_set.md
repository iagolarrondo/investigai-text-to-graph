# InvestigAI — Investigator Question Set

## Purpose

This document provides a curated set of representative investigator questions that reflect the types of inquiries our system handles during long-term care insurance fraud investigations. The questions are organized by domain and progress from straightforward data retrieval to more complex relationship-based and inference-driven queries.

These questions are intended to help our collaborators anchor their graph-based prototype with real-world investigator workflows and to explore the kinds of graph-native insights that a relationship-aware system could surface.

> **Note:** All claim numbers, provider names, and dates in these questions are placeholders (e.g., `XYZ`, `<ICP_NAME>`, `<DATE>`).

---

## 1. Policy & Claim Information

These are foundational questions investigators ask to orient themselves on a case.

1. Who is the policyholder for claim XYZ?
2. What is the current status and sub-status of claim XYZ, and why was it terminated (if applicable)?
3. What riders are associated with the policy for claim XYZ?
4. What are the Daily Maximum Benefit (DMB) and Monthly Maximum Benefit (MMB) amounts by care setting for claim XYZ?
5. Who is the writing agent that sold the policy associated with claim XYZ?

---

## 2. People & Relationships

These questions explore the network of people connected to a claim — the policyholder, their family, legal representatives, and care providers.

6. Is there a Power of Attorney (POA) on file for the claimant on claim XYZ?
7. Does the claimant on claim XYZ have a spouse? If so, does the spouse hold any other policies or have a separate claim?
8. Are the policyholder and their spouse living at the same address for claim XYZ?
9. Is there a HIPAA-authorized person associated with the claimant on claim XYZ?
10. Is any provider on claim XYZ also listed as a POA or HIPAA-authorized person for the claimant?

---

## 3. Providers

These questions identify who is providing care, what types of providers are involved, and where they are located.

11. Who are all the providers (ICPs, agencies, facilities) associated with claim XYZ?
12. Who are the individual care providers (ICPs) on claim XYZ?
13. Are there any informal caregivers on claim XYZ?
14. What is the address of ICP \<ICP_NAME\> on claim XYZ?
15. When did each provider begin and end their service on claim XYZ?

---

## 4. Caregiver App Sessions & Geolocation

These questions dig into the care session data submitted through the caregiver mobile app, including timing, location, and device information.

16. How far are care session check-ins and check-outs from the policyholder's address for claim XYZ?
17. What is the care session with the furthest check-out from the insured's address on claim XYZ?
18. Are there any care sessions on claim XYZ where pings occurred more than 5 miles from the policyholder's address?
19. Are there any care sessions where the check-in and check-out devices are different for claim XYZ?
20. Are any ICPs on claim XYZ using the same device ID across their sessions?
21. What devices are used by each ICP in the caregiver app for claim XYZ?
22. What are the check-in and check-out coordinates for ICP \<ICP_NAME\> on \<DATE\> for claim XYZ?

---

## 5. Clinical & Medical Information

These questions address the claimant's health status, cognitive assessments, diagnoses, and clinical review history.

23. What is the MMSE score for the claimant on claim XYZ?
24. Is the claimant on claim XYZ cognitively impaired?
25. What diagnoses are on file for claim XYZ?
26. What ADLs (Activities of Daily Living) are being provided for claim XYZ?
27. Is the claimant on claim XYZ designated as "no touch" (i.e., no further clinical reviews scheduled)?

---

## 6. Billing, Payments & Financial

These questions cover charges, payments, invoices, hourly rates, and bank account relationships.

28. What is the hourly rate of each ICP for claim XYZ?
29. What are the charges associated with ICP \<ICP_NAME\> in \<MONTH YEAR\> for claim XYZ?
30. Can you pull payments for claim XYZ during \<MONTH YEAR\>?
31. Which bank accounts are associated with payments on claim XYZ?
32. What is the total paid amount to each ICP on claim XYZ?

---

## 7. Review Cycles & Remediations

These questions explore the fraud investigation workflow — review cycles, triggering metrics, and remediation outcomes.

33. Is there an ongoing review cycle for claim XYZ?
34. What metrics triggered the most recent review cycle for claim XYZ?
35. Has claim XYZ ever been cleared (no fraud found) in a prior review cycle?
36. Was there any remediation for claim XYZ, and what was the recovery amount?

---

## 8. Graph-Native & Inference Questions

These questions go beyond direct data retrieval. They are designed to leverage the graph structure for relationship traversal, pattern detection, and fraud signal identification — areas where a GraphRAG approach can add unique value.

> **Context:** Many of the questions in this section are **not currently supported by InvestigAI**. Our system is built on a set of domain-specific agents that each query a slice of a relational schema; it is well-suited for targeted, single-entity lookups but does not naturally support multi-hop relationship traversal or cross-entity pattern detection at scale. These questions represent a genuine capability gap. They reflect the kinds of insights investigators would find valuable but that require reasoning across the full relationship graph rather than querying individual tables in isolation. Because your project encodes the data as a graph, these questions are a natural fit for your architecture and could provide useful insights that go beyond data retrieval.

### Cross-Entity Relationship Discovery

37. Does the ICP on claim XYZ share a home address with the policyholder or any of the policyholder's known family members?
38. Is the ICP on claim XYZ related to the claimant (e.g., spouse, family member, or POA)?
39. Are any providers on claim XYZ also listed as providers on other claims? If so, which claims do they have in common?
40. Do any two ICPs working on the same claim share the same residential address or the same bank account for payment deposits?

### Pattern & Anomaly Detection

41. For claim XYZ, has the ICP worked consecutive days without any breaks exceeding 30 days? How does this compare to other ICPs on the same claim?
42. Do the ICPs on claim XYZ have overlapping work periods where two or more caregivers were reportedly providing care on the same dates?
43. Are there any claims where the same device ID appears across sessions logged by different ICPs (potentially indicating a shared or spoofed device)?
44. For claim XYZ, are there care sessions where the provider checked in far from the policyholder's address but checked out close to it (or vice versa), suggesting fabricated location data?
45. Is there a pattern of care sessions on claim XYZ being submitted as "Manual" rather than "Live," and do those manual sessions correlate with higher charge amounts or unusual distances?

### Network & Multi-Hop Traversals

46. Starting from the policyholder on claim XYZ, what is the full network of related persons — spouse, POA, HIPAA-authorized individuals, providers, and the providers' other associated claims?
47. Do any providers on claim XYZ receive payments into a bank account that is also linked to the policyholder, a family member, or a POA?
48. Are there any business providers (agencies) on claim XYZ whose registered address is the same as the policyholder's residential address?
49. Across all claims associated with a given ICP, are there common patterns — such as consistently high distances from the policyholder's address, consistently identical check-in/check-out devices, or consistently manual session submissions?
50. For a given agency (HHCA), which individual ICPs have provided care under that agency across multiple claims, and do any of those ICPs share addresses or bank accounts with each other?

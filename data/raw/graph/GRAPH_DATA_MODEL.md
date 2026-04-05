# LTC Knowledge Graph Data Model

## Overview
This document describes the Neo4j graph data model for the Long-Term Care (LTC) system. The graph captures relationships between policies, policyholders, providers, claims, care services, and various entities involved in the LTC insurance domain.

## Node Types

### Core Entities

#### Policy
Represents an LTC insurance policy.
- **Key Property**: `POLICY_NUMBER`
- **Key Relationships**: IS_COVERED_BY (from Person), IS_CLAIM_AGAINST_POLICY (from Claim), APPROVED_RERATE (to Rerate), ASSOCIATED_RIDERS (to Riders)

#### Person
Represents individuals in the system with multiple specialized roles.
- **Key Property**: `RES_PERSON_ID`
- **Specialized Labels** (additional labels on Person nodes):
  - `PolicyHolder`: Individual covered by a policy
  - `Provider`: Individual providing care services
  - `WritingAgent`: Agent who sold the policy
  - `Physician`: Medical professional
  - `PowerOfAttorney`: Person acting on behalf of another
  - `BenefitsSpecialist`: Person assessing invoices
  - `CareManager`: Person completing clinical reviews
  - `ProviderEligibilitySpecialist`: Person assessing provider eligibility
  - `OnsiteAssessor`: Person conducting onsite assessments
  - `PolicyHolderContact`: Contact person for a policyholder
- **Key Relationships**: IS_COVERED_BY (to Policy), IS_RELATED_TO (to Person), IS_SPOUSE_OF (to Person), RECEIVE_CARE_FROM (to Person/Business), PROVIDED_CARE (to Care)

#### Business
Represents business entities providing services.
- **Key Property**: `RES_BUSINESS_ID`
- **Specialized Labels**:
  - `AssistedLivingFacility`: Assisted living facility
  - `ExternalProvider`: External service provider
  - `HomeHealthcareAgency`: Home healthcare provider
  - `JohnHancock`: Internal John Hancock entity
  - `NursingHome`: Nursing home facility
  - `MedicalCareProvider`: Medical care provider
  - `OtherProvider`: Other types of providers
  - `WritingAgent`: Business entity that sold policies
- **Key Relationships**: LOCATED_IN (to Address), PROVIDED_CARE (to Care), RECEIVES_REVIEW (to EligibilityReview), SOLD_POLICY (to Policy)

#### Claim
Represents an insurance claim.
- **Key Property**: `CLAIM_ID`
- **Key Relationships**: IS_CLAIM_AGAINST_POLICY (to Policy), DIAGNOSIS_FOR_CLAIM (from Diagnosis), ASSIGNED_BENEFIT_TO (to Person/Business), HAS_ELIGIBILITY_REVIEW (to EligibilityReview)

#### Care
Represents an aggregated care service instance for a specific provider-claim combination. Care nodes aggregate data from invoices and caregiver app sessions, consolidating care provided by one provider (Person or Business) for one claim over a period of time.

- **Key Property**: `CARE_ID`
- **Aggregated Properties**:
  - `CARE_START_DATE`, `CARE_END_DATE`: Service period
  - `TOTAL_CHARGE_AMT`, `TOTAL_PAY_AMT`: Aggregated financial amounts
  - `TOTAL_SERVICE_CHARGE_CNT`: Total number of service charges
  - `NUM_CAREGIVER_SESSIONS`: Count of caregiver app sessions
  - `NUM_MULTIDAY_CAREGIVER_SESSIONS`: Count of multi-day sessions
  - `SESSION_NUM_HOURS_AVG`: Average session duration in hours
  - `SESSION_HOURLY_RATE_MIN/MAX/AVG`: Hourly rate statistics from sessions
  - `RATIO_DISTANT_CHECK_INS/OUTS`: Ratios of geographically distant check-ins/outs
  - `BUSINESS_CARE_IND`: Flag indicating if care provider is a business (1) or individual (0)
- **Key Relationships**: PROVIDED_CARE (from Person/Business), CARE_PROVIDED_FOR_CLAIM (to Claim), IS_GEO_ADJACENT_TO (to Address), PAYMENT_DEPOSITED_TO_ACCOUNT (to BankAccount)

### Contact & Location

#### Address
Physical address location.
- **Key Property**: `RES_ADDRESS_ID`
- **Key Relationships**: LOCATED_IN (from Person/Business), IS_GEO_ADJACENT_TO (from Care)

#### Phone
Phone number entity.
- **Key Property**: `RES_PHONE_ID`
- **Key Relationships**: USE_PHONE_NUMBER (from Person/Business), CALL_WITH_PHONE_NUMBER (from Call)

### Medical & Assessment

#### Diagnosis
Medical diagnosis information.
- **Key Property**: `DIAGNOSIS_ID`
- **Key Relationships**: DIAGNOSIS_FOR_CLAIM (to Claim)

#### ClinicalReview
Clinical assessment/review record.
- **Key Property**: `NORM_CLINICAL_REVIEW_ID`
- **Key Relationships**: CONDUCTED_ON (to Claim), COMPLETE_CLINICAL_REVIEW (from Person)

#### OnsiteAssessment
Record of an onsite assessment.
- **Key Property**: `NORM_ONSITE_ASSESSMENT_ID`
- **Key Relationships**: COMPLETED_ON_CLAIM (to Claim), COMPLETE_ONSITE_ASSESSMENT (from Person)

#### EligibilityReview
Review of provider or person eligibility.
- **Key Property**: `NORM_ELIGIBILITY_REVIEW_ID`
- **Key Relationships**: ASSESS_ELIGIBILITY (from Person), RECEIVES_REVIEW (from Person/Business), HAS_ELIGIBILITY_REVIEW (from Claim)

### Investigation & Monitoring

#### ReviewCycle
Fraud investigation or review cycle.
- **Key Property**: `REVIEW_CYCLE_ID`
- **Key Relationships**: INVESTIGATION_ON_CLAIM (to Claim), RESULT_IN_REMEDIATION (to Remediation), FLAGGED_ON (to ReviewCycleMetric)

#### ReviewCycleMetric
Metrics flagged during review cycles.
- **Key Property**: `REVIEW_CYCLE_METRIC_ID`
- **Key Relationships**: FLAGGED_ON (from ReviewCycle)

#### Remediation
Remediation actions and recovered amounts.
- **Key Property**: `REVIEW_CYCLE_REMEDIATION_ID`
- **Properties**: `ACTUAL_RECOVERED_AMT`, `ESTIMATED_RECOVERED_AMT`, `REQUESTED_AMT`, `ACTUARIAL_SAVINGS`, `TOTAL_SAVINGS_AMT`
- **Key Relationships**: RESULT_IN_REMEDIATION (from ReviewCycle)

#### Alert
System-generated alerts for suspicious patterns and anomalies in fraud detection. Alert types include overlapping providers, multiple policy holders served by same provider, high-risk diagnoses, spousal care scenarios, low service frequency, provider denials, multiple active claims, out-of-country care, and distant caregiver check-ins.
- **Key Property**: `ALERT_ID` (with type-specific prefixes like `1-`, `3-`, `4-`, etc.)
- **Key Relationships**: ALERT_ON (to Person, Claim, ClinicalReview, Diagnosis)

### Communications

#### Call
Customer service call record.
- **Key Property**: `NORM_CALL_ID`
- **Key Relationships**: IN_MONTH (to Month), CALL_WITH_PHONE_NUMBER (to Phone)

### Financial

#### BankAccount
Bank account for payments.
- **Key Property**: `RES_BANK_ACCOUNT_ID`
- **Properties**: Masked `ROUTING_NUMBER` and `ACCOUNT_NUMBER`
- **Key Relationships**: HELD_BY (to Person/Business), PAYMENT_DEPOSITED_TO_ACCOUNT (from Care)

#### Rerate
Policy rate adjustment record.
- **Key Property**: `NORM_RERATE_ID`
- **Key Relationships**: APPROVED_RERATE (from Policy)

#### Riders
Policy riders/add-ons (contains pivoted rider attributes).
- **Key Property**: Policy-specific identifier
- **Key Relationships**: ASSOCIATED_RIDERS (from Policy)

### Temporal

#### Year
Synthetic node for temporal grouping by year.
- **Key Property**: `YEAR_ID`
- **Key Relationships**: IN_YEAR (from Month), OF_POLICY (to Policy)

#### Month
Synthetic node for temporal grouping by month.
- **Key Property**: `MONTH_ID`
- **Key Relationships**: IN_MONTH (from Call), IN_YEAR (to Year)

## Relationship Types

### Person-to-Person Relationships
| Relationship | Description |
|--------------|-------------|
| `IS_RELATED_TO` | Family relationship (property: RELATIONSHIP type) |
| `IS_SPOUSE_OF` | Spousal relationship |
| `IS_PRIMARY_CONTACT_OF` | Primary contact designation (property: SOURCE_TYPE) |
| `ACT_ON_BEHALF_OF` | Power of attorney relationship |
| `DIAGNOSED_BY` | Physician diagnosis relationship |
| `HIPAA_AUTHORIZED_ON` | HIPAA authorization relationship |
| `RECEIVE_CARE_FROM` | Individual care recipient to caregiver |

### Person-to-Entity Relationships
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `IS_COVERED_BY` | Person | Policy | Policy coverage |
| `SOLD_POLICY` | Person | Policy | Agent sold policy |
| `LOCATED_IN` | Person | Address | Person's address |
| `USE_PHONE_NUMBER` | Person | Phone | Person's phone |
| `PROVIDED_CARE` | Person | Care | Individual provided care |
| `RECEIVE_CARE_FROM` | Person | Business | Receives care from business |
| `TREATED_BY` | Person | Business | Medical treatment |
| `EMPLOYED_BY` | Person | Business | Employment relationship |
| `COMPLETE_CLINICAL_REVIEW` | Person | ClinicalReview | Completed review |
| `COMPLETE_ONSITE_ASSESSMENT` | Person | OnsiteAssessment | Completed assessment |
| `ASSESS_ELIGIBILITY` | Person | EligibilityReview | Assessed eligibility |
| `RECEIVES_REVIEW` | Person | EligibilityReview | Subject of review |

### Business Relationships
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `LOCATED_IN` | Business | Address | Business location |
| `USE_PHONE_NUMBER` | Business | Phone | Business phone |
| `SOLD_POLICY` | Business | Policy | Business sold policy |
| `PROVIDED_CARE` | Business | Care | Business provided care |
| `RECEIVES_REVIEW` | Business | EligibilityReview | Subject of eligibility review |

### Claim Relationships
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `IS_CLAIM_AGAINST_POLICY` | Claim | Policy | Claim on policy |
| `DIAGNOSIS_FOR_CLAIM` | Claim | Diagnosis | Claim diagnosis |
| `ASSIGNED_BENEFIT_TO` | Claim | Person/Business | Benefit assignment |
| `HAS_ELIGIBILITY_REVIEW` | Claim | EligibilityReview | Claim eligibility review |

### Care Relationships
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `CARE_PROVIDED_FOR_CLAIM` | Care | Claim | Care for specific claim |
| `IS_GEO_ADJACENT_TO` | Care | Address | Geographic proximity |
| `PAYMENT_DEPOSITED_TO_ACCOUNT` | Care | BankAccount | Payment information |

### Review & Investigation
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `CONDUCTED_ON` | ClinicalReview | Claim | Clinical review on claim |
| `COMPLETED_ON_CLAIM` | OnsiteAssessment | Claim | Onsite assessment on claim |
| `INVESTIGATION_ON_CLAIM` | ReviewCycle | Claim | Investigation on claim |
| `RESULT_IN_REMEDIATION` | ReviewCycle | Remediation | Remediation result |
| `FLAGGED_ON` | ReviewCycle | ReviewCycleMetric | Metric flagged |
| `ALERT_ON` | Alert | Various | Alert on entity |

### Policy & Financial
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `APPROVED_RERATE` | Policy | Rerate | Rate adjustment |
| `ASSOCIATED_RIDERS` | Policy | Riders | Policy riders |
| `HELD_BY` | BankAccount | Person/Business | Account holder |

### Communication & Temporal
| Relationship | Source | Target | Description |
|--------------|--------|--------|-------------|
| `CALL_WITH_PHONE_NUMBER` | Call | Phone | Call phone number |
| `IN_MONTH` | Call | Month | Call in month |
| `IN_YEAR` | Month | Year | Month in year |
| `OF_POLICY` | Year | Policy | Year of policy |

## Key Features

### Multi-Label Nodes
- **Person** nodes can have multiple role labels simultaneously (e.g., a person can be both a PolicyHolder and a Provider)
- **Business** nodes are specialized by type (NursingHome, AssistedLivingFacility, etc.)

### Temporal Aggregation
- Calls are aggregated by Month and Year nodes for temporal analysis
- Years are linked to Policies for policy-year analytics

### Fraud Detection
- ReviewCycle and Remediation track investigations and outcomes
- Alert nodes identify suspicious patterns
- ReviewCycleMetric captures flagged metrics

### Care Network
- Care nodes connect providers (Person/Business) to claims
- Geographic relationships tracked via IS_GEO_ADJACENT_TO
- Payment flow tracked to BankAccount entities

## Graph Traversal Patterns

### Common Query Patterns

1. **Policy Network**: `(Policy)<-[:IS_COVERED_BY]-(Person)-[:RECEIVE_CARE_FROM]->(Provider)`
2. **Care Flow**: `(Provider)-[:PROVIDED_CARE]->(Care)-[:CARE_PROVIDED_FOR_CLAIM]->(Claim)-[:IS_CLAIM_AGAINST_POLICY]->(Policy)`
3. **Investigation Path**: `(ReviewCycle)-[:INVESTIGATION_ON_CLAIM]->(Claim)-[:IS_CLAIM_AGAINST_POLICY]->(Policy)`
4. **Contact Network**: `(PolicyHolder)<-[:IS_PRIMARY_CONTACT_OF]-(Contact)`
5. **Payment Trail**: `(Care)-[:PAYMENT_DEPOSITED_TO_ACCOUNT]->(BankAccount)-[:HELD_BY]->(Provider)`

### Fraud Detection Patterns

#### Spouses Living at Same Address
Verify if spouses share the same residential address:

```cypher
MATCH (spouse1:Person)-[:IS_SPOUSE_OF]-(spouse2:Person)
MATCH (spouse1)-[:LOCATED_IN]->(address:Address)
MATCH (spouse2)-[:LOCATED_IN]->(address)
RETURN spouse1.RES_PERSON_ID, spouse2.RES_PERSON_ID, 
       address.RES_ADDRESS_ID, address.ADDRESS_LINE_1, address.CITY, address.STATE, address.ZIP_CODE
```

#### Provider Serving Multiple Family Members
Identify providers serving multiple related individuals (potential fraud indicator):

```cypher
MATCH (provider)-[:PROVIDED_CARE]->(care1:Care)-[:CARE_PROVIDED_FOR_CLAIM]->(claim1:Claim)
MATCH (provider)-[:PROVIDED_CARE]->(care2:Care)-[:CARE_PROVIDED_FOR_CLAIM]->(claim2:Claim)
MATCH (claim1)-[:IS_CLAIM_AGAINST_POLICY]->(policy1)<-[:IS_COVERED_BY]-(person1:Person)
MATCH (claim2)-[:IS_CLAIM_AGAINST_POLICY]->(policy2)<-[:IS_COVERED_BY]-(person2:Person)
MATCH (person1)-[:IS_RELATED_TO]-(person2)
WHERE care1 <> care2 AND claim1 <> claim2
RETURN provider, person1, person2, 
       count(DISTINCT care1) + count(DISTINCT care2) as total_care_instances
```

#### Geographic Anomalies - Provider and Policyholder Addresses
Find cases where care is provided but the provider and policyholder are not geographically adjacent:

```cypher
MATCH (policyholder:PolicyHolder)-[:IS_COVERED_BY]->(policy:Policy)
MATCH (claim:Claim)-[:IS_CLAIM_AGAINST_POLICY]->(policy)
MATCH (care:Care)-[:CARE_PROVIDED_FOR_CLAIM]->(claim)
MATCH (provider)-[:PROVIDED_CARE]->(care)
MATCH (policyholder)-[:LOCATED_IN]->(ph_address:Address)
MATCH (provider)-[:LOCATED_IN]->(prov_address:Address)
WHERE NOT (care)-[:IS_GEO_ADJACENT_TO]->(ph_address)
RETURN policyholder.RES_PERSON_ID, provider, 
       ph_address,
       prov_address
```

#### Shared Bank Accounts Across Multiple Providers
Detect when multiple providers use the same bank account for payment deposits:

```cypher
MATCH (provider1)-[:PROVIDED_CARE]->(care1:Care)-[:PAYMENT_DEPOSITED_TO_ACCOUNT]->(account:BankAccount)
MATCH (provider2)-[:PROVIDED_CARE]->(care2:Care)-[:PAYMENT_DEPOSITED_TO_ACCOUNT]->(account)
WHERE provider1 <> provider2
RETURN account.RES_BANK_ACCOUNT_ID, account.ACCOUNT_NUMBER,
       collect(DISTINCT provider1) as providers,
       count(DISTINCT care1) + count(DISTINCT care2) as total_care_payments
```

#### Policy Network with Spouse and Provider Relationships
Full network showing policyholder, spouse, shared provider, and geographic connections:

```cypher
MATCH (ph:Person:PolicyHolder)-[:IS_COVERED_BY]->(policy:Policy)
MATCH (ph)-[:IS_SPOUSE_OF]-(spouse:Person)
MATCH (ph)-[:RECEIVE_CARE_FROM]->(provider)
MATCH (spouse)-[:RECEIVE_CARE_FROM]->(provider)
MATCH (ph)-[:LOCATED_IN]->(address:Address)
OPTIONAL MATCH (spouse)-[:LOCATED_IN]->(spouse_address:Address)
RETURN ph, spouse, provider, policy, address, spouse_address,
       address = spouse_address as same_address
```
/*
Each entry in T_RESOLVED_PERSON_POLICY_CROSSWALK corresponds to a relationship between a person (RES_PERSON_ID) and policy (POLICY_NUMBER).

EDGE_NAME specifies the type of relation, there are two possible options:
- 'IS_COVERED_BY': Person is the policyholder for the policy identified by POLICY_NUMBER.
- 'SOLD_POLICY': Person sold the policy identified by POLICY_NUMBER. The person is the writing agent for that policy.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PERSON_POLICY_CROSSWALK
(
	RES_PERSON_ID BIGINT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	POLICY_NUMBER VARCHAR(15)
)
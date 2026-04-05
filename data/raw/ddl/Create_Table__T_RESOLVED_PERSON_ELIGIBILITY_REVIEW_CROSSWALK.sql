/*
Each row in T_RESOLVED_PERSON_ELIGIBILITY_REVIEW_CROSSWALK corresponds to a connection between a person (identified by RES_PERSON_ID) and a provider eligibility review (identified by NORM_ELIGIBILITY_REVIEW_ID).
EDGE_NAME column specifies the kind of relationship, it can have the following values:
- ASSESS_ELIGIBILITY: The person has conducted the eligibility review.
- RECEIVES_REVIEW: The person is the provider who received the eligibility review.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PERSON_ELIGIBILITY_REVIEW_CROSSWALK
(
	NORM_ELIGIBILITY_REVIEW_ID INT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	RES_PERSON_ID BIGINT
)
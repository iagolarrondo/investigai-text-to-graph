/*
Each row in T_RESOLVED_BUSINESS_ELIGIBILITY_REVIEW_CROSSWALK corresponds to a connection between a business (identified by RES_BUSINESS_ID) and a provider eligibility review (identified by NORM_ELIGIBILITY_REVIEW_ID).
EDGE_NAME column specifies the kind of relationship, it can have the following values:
- RECEIVES_REVIEW: The business is the provider who received the eligibility review.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_BUSINESS_ELIGIBILITY_REVIEW_CROSSWALK
(
	NORM_ELIGIBILITY_REVIEW_ID INT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	RES_BUSINESS_ID BIGINT
)
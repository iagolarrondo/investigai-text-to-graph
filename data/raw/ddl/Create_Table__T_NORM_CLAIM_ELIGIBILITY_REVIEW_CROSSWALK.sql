/*
Each row in T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK corresponds to a case where there is an eligibility review for a provider associated with a claim.
The only possible value for EDGE_NAME is 'HAS_ELIGIBILITY_REVIEW'.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_CLAIM_ELIGIBILITY_REVIEW_CROSSWALK
(
	CLAIM_ID VARCHAR(15),
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	NORM_ELIGIBILITY_REVIEW_ID INT
)
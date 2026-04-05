/*
Each entry in T_RESOLVED_BUSINESS_PERSON_CROSSWALK corresponds to a connection between a business (identified by RES_BUSINESS_ID) and person (identified by RES_PERSON_ID).
EDGE_NAME specifies the kind of relationship: The value for EDGE_NAME is 'RECEIVE_CARE_FROM' when a person is receiving care from a business.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_BUSINESS_PERSON_CROSSWALK
(
	RES_BUSINESS_ID BIGINT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	RES_PERSON_ID BIGINT
)
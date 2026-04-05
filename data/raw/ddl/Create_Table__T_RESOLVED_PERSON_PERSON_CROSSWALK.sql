/*
Each record in T_RESOLVED_PERSON_PERSON_CROSSWALK corresponds to a relationship between two person records (RES_PERSON_ID_SRC and RES_PERSON_ID_TGT).

EDGE_NAME column specifies what kind of relationship the two people has. The following values are possible for EDGE_NAME:
- 'IS_SPOUSE_OF': Indicates spousal relationship between two people
- 'ACT_ON_BEHALF_OF': Indicates RES_PERSON_ID_SRC is power of attorney (POA) over RES_PERSON_ID_TGT
- 'HIPAA_AUTHORIZED_ON': Indicates RES_PERSON_ID_SRC has HIPAA authorization on RES_PERSON_ID_TGT, hence they are able to access their medical records
- 'IS_RELATED_TO': Indicates some type of family/relative relationship between RES_PERSON_ID_SRC and RES_PERSON_ID_TGT. EDGE_DETAIL column may have details about what this relationship is.
- 'DIAGNOSED_BY': Indicates that RES_PERSON_ID_SRC is diagnosed by RES_PERSON_ID_TGT, a physician.
*/

CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PERSON_PERSON_CROSSWALK
(
	RES_PERSON_ID_SRC BIGINT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(500),
	EDGE_DETAIL_DSC VARCHAR(500),
	RES_PERSON_ID_TGT BIGINT
)
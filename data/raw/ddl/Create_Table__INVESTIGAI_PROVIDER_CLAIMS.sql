/* 
Provider claims table. Each entry in INVESTIGAI_PROVIDER_CLAIMS corresponds to a provider that has provided care for a claim.
This table allows for a quick lookup of providers associated with a given claim number or alternatively find all claims associated with a given provider.
The PROVIDER_ID field corresponds to a RES_PERSON_ID attribute from T_RESOLVED_PERSON table if the PROVIDER_TYPE is ICP,
otherwise it corresponds to a RES_BUSINESS_ID attribute from T_RESOLVED_BUSINESS.

IMPORTANT: CLAIM_ID field is a database internal primary key. It is not the same as CLAIM_NUMBER. If you need to find the claim number for a given claim, use CLAIM_NUMBER field with a WHERE clause to filter, NOT the CLAIM_ID field.
*/
CREATE TABLE {catalog_name}.{schema_name}.INVESTIGAI_PROVIDER_CLAIMS
(
	PROVIDER_ID BIGINT, /* Foreign key corresponding to the RES_PERSON_ID attribute in T_RESOLVED_PERSON if PROVIDER_TYPE is ICP, otherwise corresponds to RES_BUSINESS_ID attribute in T_RESOLVED_BUSINESS */
	PROVIDER_NAME VARCHAR(60), /* Full name of a provider (i.e., FIRST_NAME LAST_NAME if an ICP otherwise it is a business name) */
	PROVIDER_TYPE VARCHAR(20), /* Type of provider. Can be an ICP (Individual Care Provider), HHCA (home health care agencies), NH (nursing homes), ALF (assisted living facilities) or Other Provider for other Business Providers */
    CLAIM_ID VARCHAR(50), /* Internal claim identifier that provider provided care for */
	CLAIM_NUMBER VARCHAR(50), /* Claim number of policyholder that was provided care */
	CLAIM_STATUS_CODE VARCHAR(25), /* Status of the claim (Active or Terminated) */
	SERVICE_START_DATE DATE, /* First date that the ICP provided care for */
	SERVICE_END_DATE DATE, /* Last date that the ICP provided care for */
)
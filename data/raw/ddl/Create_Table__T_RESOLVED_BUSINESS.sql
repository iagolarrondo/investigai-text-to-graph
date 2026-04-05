/*
 * Business table. Each record corresponds to a business. Other tables can be joined to this table via RES_BUSINESS_ID key.
 * BUSINESS_NAME consists of all-uppercase characters.
 * BUSINESS_TYPE can be HHCA for home health care agencies, NH for nursing homes and ALF for assisted living facilities.
 */

CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_BUSINESS
(
	RES_BUSINESS_ID BIGINT,
	BUSINESS_NAME VARCHAR(200), /* All characters in uppercase */
	TAX_ID VARCHAR(15),
	BUSINESS_TYPE VARCHAR(50),
	DUNS_NUMBER VARCHAR(15)
)
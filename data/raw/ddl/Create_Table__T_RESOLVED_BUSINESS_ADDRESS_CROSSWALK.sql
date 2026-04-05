/*
Each record in T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK correspond to a business (RES_BUSINESS_ID) located in an address record (RES_ADDRESS_ID).
Use this table to find the address associated with a given business.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK
(
	RES_BUSINESS_ID BIGINT, /* The unique identifier for the business. Foreign key to T_RESOLVED_BUSINESS */
	RES_ADDRESS_ID BIGINT /* The unique identifier for the address. Foreign key to T_RESOLVED_ADDRESS */
)
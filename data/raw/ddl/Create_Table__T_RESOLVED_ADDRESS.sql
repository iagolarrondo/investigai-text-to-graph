/*
 * Each entry in T_RESOLVED_ADDRESS corresponds to an address record in the system. Each address record may be linked to person or business records 
 * through T_RESOLVED_PERSON_ADDRESS_CROSSWALK (for person addresses) or T_RESOLVED_BUSINESS_ADDRESS_CROSSWALK (for business addresses) tables. 
 * Joins to this table can be done through RES_ADDRESS_ID key.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_ADDRESS
(
	RES_ADDRESS_ID BIGINT,
	ADDRESS_LINE_1 VARCHAR(200),
	ADDRESS_LINE_2 VARCHAR(200),
	ADDRESS_LINE_3 VARCHAR(200),
	CITY VARCHAR(50),
	STATE VARCHAR(50),
	ZIP_CODE VARCHAR(20),
	-- Corresponding (latitude,longitude) coordinates for the address. Not available for all records.
	LATITUDE DECIMAL(8, 6),
	LONGITUDE DECIMAL(9, 6)
)
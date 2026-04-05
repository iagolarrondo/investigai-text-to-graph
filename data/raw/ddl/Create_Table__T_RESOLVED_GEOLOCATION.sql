/*
Each record in T_RESOLVED_GEOLOCATION corresponds to a geolocation for which a care session has occurred. 
This table can be joined with T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK to get the corresponding care session.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_GEOLOCATION
(
	RES_GEOLOCATION_ID BIGINT,
	LATITUDE FLOAT,
	LONGITUDE FLOAT
)
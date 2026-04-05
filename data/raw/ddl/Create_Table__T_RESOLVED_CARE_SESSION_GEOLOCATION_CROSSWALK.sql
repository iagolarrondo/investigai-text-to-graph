/*
Each entry in T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK corresponds to a care session (NORM_CARE_SESSION_ID) taking place at a geolocation (RES_GEOLOCATION_ID). 
The table also has following columns:
- EVENT_TYPE: Can be 'GEO_CHECK_IN' or 'GEO_CHECK_OUT'. 'GEO_CHECK_IN' edge means that a provider checked-in at the location during the start of the care session. 'GEO_CHECK_OUT' edge means that a provider checked-out at the location at the end of the care session.
- EVENT_DATETIME: Timestamp when the check-in or check-out occurred.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK
(
	NORM_CARE_SESSION_ID INT,
	EVENT_TYPE VARCHAR(25),
	EVENT_DATETIME DATETIME,
	RES_GEOLOCATION_ID BIGINT
)
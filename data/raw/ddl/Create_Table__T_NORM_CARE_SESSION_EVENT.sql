/* 
 * Caregiver care session pings table. 
 * Each entry is a care session ping event that is automatically sent via the Caregiver app. Other tables can be joined to this table via the NORM_CARE_SESSION_ID key.
 * Use this table to answer questions related ping information from Caregiver sessions submitted by the ICPs.
 * Note that not all care sessions will have ping information as that depends on the usage of the caregiver app and the permissions granted by the ICP.
 * IMPORTANT: DO NOT search for a claim number using CLAIM_ID field in T_NORM_CARE_SESSION_EVENT table. Join it with T_NORM_CARE_SESSION on NORM_CARE_SESSION_ID, and then JOIN with T_NORM_CLAIM on CLAIM_ID. You can then search for claim number in the CLAIM_NUMBER field of T_NORM_CLAIM. 
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_CARE_SESSION_EVENT
(
	NORM_CARE_SESSION_EVENT_ID BIGINT, /* Unique identifier for each ping (i.e., session event). */
	SOURCE_SYSTEM VARCHAR(50),	 /* Source system of the associated event */
	EVENT_LOCAL_TS DATETIME,  /* Local timestamp of the associated ping event */
	EVENT_TYPE VARCHAR(100), /* Type of event:  can be 'EXIT', 'ENTER', 'BACKGROUND_GEO_LOCATION_TRACKING_INTERVAL' or 'APP_FOREGROUND_LOCATION' */
	NORM_CARE_SESSION_ID INT /* Associated care session ID for this event */
)
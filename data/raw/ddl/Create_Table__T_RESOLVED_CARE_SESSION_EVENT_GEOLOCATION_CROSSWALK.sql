/*
Each entry in T_RESOLVED_CARE_SESSION_EVENT_GEOLOCATION_CROSSWALK corresponds to a care session event (i.e., ping) described by the NORM_CARE_SESSION_EVENT_ID property that takes places at a geolocation (RES_GEOLOCATION_ID).
This table can be used to link care session ping events described by T_NORM_CARE_SESSION_EVENT table to their resolved geolocations.
This table can then be linked with the T_RESOLVED_GEOLOCATION table via the RES_GEOLOCATION_ID property to get the LONGITUDE AND LATITUDE coordinates for each care session event (i.e., ping).
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK
(
	NORM_CARE_SESSION_EVENT_ID BIGINT, /* Unique identifier for each care session event (i.e., ping). */
	RES_GEOLOCATION_ID BIGINT /* Resolved geolocation ID associated with the care session event. */,
)
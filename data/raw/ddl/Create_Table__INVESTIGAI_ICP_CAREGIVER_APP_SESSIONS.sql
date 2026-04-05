/* 
ICP caregiver app sessions table. Each entry in INVESTIGAI_ICP_CAREGIVER_APP_SESSIONS corresponds to a care session logged by an ICP caregiver using the caregiver app.
This table allows for a quick lookup of care sessions associated with a given claim number or alternatively find all care sessions associated with a given ICP provider.
This table also contains geolocation information for the check-in and check-out of the care session, as well as device information for the check-in and check-out.
Moreover, it includes information about the number of pings recorded during the session and the maximum distance of these pings from the check-in and check-out locations.
The address associated with the policyholder on the claim that is closest to the check-in and check-out geolocations can also be found by joining the CHECK_IN_CLOSEST_ADDRESS_ID and CHECK_OUT_CLOSEST_ADDRESS_ID fields with the RES_ADDRESS_ID field in the T_RESOLVED_ADDRESS table.

The PROVIDER_ID field corresponds to a RES_PERSON_ID attribute from T_RESOLVED_PERSON table as all providers in this table are ICP providers.

IMPORTANT: CLAIM_ID field is a database internal primary key. It is not the same as CLAIM_NUMBER. If you need to find the claim number for a given claim, use CLAIM_NUMBER field with a WHERE clause to filter, NOT the CLAIM_ID field.
*/
CREATE TABLE {catalog_name}.{schema_name}.INVESTIGAI_ICP_CAREGIVER_APP_SESSIONS
(
	NORM_CARE_SESSION_ID BIGINT, /* Primary key, the unique ID of the care session logged in the caregiver app */
	PROVIDER_ID BIGINT,  /* Provider ID corresponding to the ICP RES_PERSON_ID in the T_RESOLVED_PERSON table */
	PROVIDER_NAME VARCHAR(60), /* Full name of the provider */
    CLAIM_ID VARCHAR(50), /* Internal claim identifier that provider provided care for */
	CLAIM_NUMBER VARCHAR(50), /* Claim number of policyholder that the provider provided care for */
	SESSION_START_TS TIMESTAMP, /* Session start timestamp */
	SESSION_END_TS TIMESTAMP, /* Session end timestamp */
	SESSION_SUBMISSION_STATUS VARCHAR(255),  /* Submission status: 'Approved', 'Submitted', 'Denied', 'Denied-Deleted', 'Not Submitted' */
	SESSION_REJECTION_COMMENTS VARCHAR(500), /* Comments regarding a rejection */
	SESSION_TYPE VARCHAR(255), /* Type of session: 'Manual' or 'Live' */
	NUM_HOURS DECIMAL(15, 2), /* Number of hours logged for the session */
	HOURLY_RATE DECIMAL(15, 2), /* Hourly rate charged by the provider for the session */
	CHARGE_AMT DECIMAL(15, 2), /* Total charge amount for the session */
	CHECK_IN_DEVICE_ID VARCHAR(50), /* Device ID for the check-in */
	CHECK_OUT_DEVICE_ID VARCHAR(50), /* Device ID for the check-out */
	CHECK_IN_LATITUDE DECIMAL(15, 4), /* Latitude for the check-in */
	CHECK_IN_LONGITUDE DECIMAL(15, 4), /* Longitude for the check-in */
	CHECK_OUT_LATITUDE DECIMAL(15, 4), /* Latitude for the check-out */
	CHECK_OUT_LONGITUDE DECIMAL(15, 4), /* Longitude for the check-out */
	CHECK_IN_CHECK_OUT_DISTANCE_IN_MILES DECIMAL(15, 4), /* Distance in miles between the check-in and check-out geolocations */
	CHECK_IN_DISTANCE_TO_CLOSEST_ADDRESS_IN_MILES DECIMAL(15, 4), /* Distance in miles between the check-in geolocation and the closest address geolocation associated with the policyholder on the claim. */
	CHECK_OUT_DISTANCE_TO_CLOSEST_ADDRESS_IN_MILES DECIMAL(15, 4), /* Distance in miles between the check-out geolocation and the closest address geolocation associated with the policyholder on the claim. */
	CHECK_IN_CLOSEST_ADDRESS_ID BIGINT, /* RES_ADDRESS_ID for the closest address to the check-in geolocation among all addresses associated with the policyholder on the claim. This can be joined with T_RESOLVED_ADDRESS table to get more information about the address. */
	CHECK_OUT_CLOSEST_ADDRESS_ID BIGINT, /* RES_ADDRESS_ID for the closest address to the check-out geolocation among all addresses associated with the policyholder on the claim. This can be joined with T_RESOLVED_ADDRESS table to get more information about the address. */
	NUM_PINGS INT, /* Number of pings recorded in the caregiver app for the session. Each ping corresponds to a periodic recording of geolocation and device information in the caregiver app during an active care session. */
	MAX_PING_DISTANCE_TO_CHECK_IN_MILES DECIMAL(15, 4), /* Maximum distance in miles between the geolocation of any ping recorded during the session and the check-in geolocation. This can be used as a measure of how much the provider moved during the session compared to the check-in location. */
	MAX_PING_DISTANCE_TO_CHECK_OUT_MILES DECIMAL(15, 4) /* Maximum distance in miles between the geolocation of any ping recorded during the session and the check-out geolocation. This can be used as a measure of how much the provider moved during the session compared to the check-out location. */
)
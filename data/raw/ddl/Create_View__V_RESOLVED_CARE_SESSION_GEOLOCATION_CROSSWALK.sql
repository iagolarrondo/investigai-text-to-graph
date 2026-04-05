/*
 Each record in this table has the geolocation information for a care session.
 Use this table to answer questions related to the geolocation of care sessions.
*/
CREATE TABLE {catalog_name}.{schema_name}.V_RESOLVED_CARE_SESSION_GEOLOCATION_CROSSWALK
(
    NORM_CARE_SESSION_ID INT NOT NULL,
    CLAIM_ID VARCHAR(15) NOT NULL, /* FK for T_NORM_CLAIM */
    SESSION_START_LOCAL_TS DATETIME,  /* Session check-in time. */
    SESSION_END_LOCAL_TS DATETIME,  /* Session check-out time. */
    NUM_HOURS FLOAT,
	HOURLY_RATE DECIMAL(15, 2), /* Hourly rate charged by the provider. */
    CHARGE_AMT DECIMAL(15, 2),
    SUBMISSION_STATUS VARCHAR(255),  /* Submission status: 'Approved', 'Submitted', 'Denied', 'Denied-Deleted' */
    REJECTION_COMMENTS VARCHAR(500),
    CHECK_IN_DEVICE_ID VARCHAR(50), /* Device ID for the check-in. */
	CHECK_OUT_DEVICE_ID VARCHAR(50), /* Device ID for the check-out. */
    CHECK_IN_GEO_ID BIGINT NOT NULL,
    CHECK_IN_LATITUDE FLOAT,
    CHECK_IN_LONGITUDE FLOAT,
    CHECK_OUT_GEO_ID BIGINT NOT NULL,
    CHECK_OUT_LATITUDE FLOAT,
    CHECK_OUT_LONGITUDE FLOAT,
    CHECK_IN_CHECK_OUT_DISTANCE FLOAT /* Distance between check-in and check-out (in miles) */
)
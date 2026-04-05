/* 
 * Caregiver session table. 
 * Each entry is a care session submitted via Caregiver app. Other tables can be joined to this table via NORM_CARE_SESSION_ID key.
 * Use this table to answer questions related to Caregiver sessions submitted by the ICPs.
 * IMPORTANT: DO NOT search for a claim number using CLAIM_ID field in T_NORM_CARE_SESSION table. Join it with T_NORM_CLAIM on CLAIM_ID, and then search for claim number in the CLAIM_NUMBER field of T_NORM_CLAIM. 
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_CARE_SESSION
(
	NORM_CARE_SESSION_ID INT IDENTITY(1,1) NOT NULL,
	CLAIM_ID VARCHAR(15) NOT NULL,
	SUBMISSION_STATUS VARCHAR(255),  /* Submission status: 'Approved', 'Submitted', 'Denied', 'Denied-Deleted' */
	REJECTION_COMMENTS VARCHAR(500),
	SESSION_TYPE VARCHAR(255), /* Type of session: 'Manual' or 'Live' */
	SESSION_START_LOCAL_TS DATETIME, /* Session start timestamp. */
	SESSION_END_LOCAL_TS DATETIME, /* Session end timestamp. */
	NUM_HOURS FLOAT,
	HOURLY_RATE DECIMAL(15, 2), /* Hourly rate charged by the provider. */
	CHARGE_AMT DECIMAL(15, 2),
	CHECK_IN_DEVICE_ID VARCHAR(50), /* Device ID for the check-in. */
	CHECK_OUT_DEVICE_ID VARCHAR(50), /* Device ID for the check-out. */
	/* Below columns are 0/1 indicators for whether there was assistance with bathing, dressing etc.. in the session. */
	ADL_BATHING INT,
	ADL_CONTINENCE INT,
	ADL_DRESSING INT,
	ADL_EATING INT,
	ADL_OTHER INT,
	ADL_SUPERVISION INT,
	ADL_TOILETING INT,
	ADL_TRANSFERRING INT,
	ADL_VALUE_FOR_OTHER VARCHAR(255) /* If ADL_OTHER=1, this column specifies the kind of assistance given by the provider. */
)
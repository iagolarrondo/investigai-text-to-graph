/*
 * Invoice table. Each row represents a single invoice submitted for a long term care claim.
 * An invoice covers a range of care service dates and is associated with a specific claim
 *
 * Each invoice can have multiple charge records in T_NORM_CHARGE (joined on NORM_INVOICE_ID)
 * and multiple payment records in T_NORM_PAYMENT (joined on NORM_INVOICE_ID).
 *
 * IMPORTANT: Do NOT use CLAIM_ID to search for a claim by number.
 * Join T_NORM_INVOICE with T_NORM_CLAIM on CLAIM_ID and filter on CLAIM_NUMBER in T_NORM_CLAIM.
 *
 * To determine start of care for a claim, find the invoice with the earliest INVOICE_SERVICE_START_DATE
 * for that claim.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_INVOICE
(
    NORM_INVOICE_ID     BIGINT,         /* Primary key. Unique identifier for each invoice record. */
    CLAIM_ID            VARCHAR(15),    /* Foreign key to T_NORM_CLAIM. Join on CLAIM_ID to retrieve CLAIM_NUMBER. */
	INVOICE_RECEIVED_DATE TIMESTAMP,    /* Use INVOICE_RECEIVED_DATE to filter on "invoice date"  */
	INVOICE_STATUS VARCHAR(200)         /* Invoice status */
    INVOICE_SERVICE_START_DATE  DATE,   /* Start date of the care service period covered by this invoice. Used to determine start of care. */
    INVOICE_SERVICE_END_DATE    DATE,   /* End date of the care service period covered by this invoice. */
	INVOICE_SERVICE_CHARGE_CNT INT,
	INVOICE_CHARGE_AMT DECIMAL(10, 2),  /* Total charge amount for the invoice. */
	INVOICE_PAY_AMT DECIMAL(10, 2),     /* Total paid amount for the invoice. */
	PORTAL_CARE_SETTING VARCHAR(50),    /* If available, care setting for the invoice. */
	PORTAL_INVOICE_CHARGE_AMT DECIMAL(15, 2),
	PORTAL_TOTAL_HOURS FLOAT, 			/* Total number of hours worked for the charges on invoice. */
	PORTAL_TOTAL_HOURS_INFERRED_IND INT, /* Min and max hourly rates for the invoice. If available, these values can be used to filter on "hourly rate" for a given invoice. */
	PORTAL_MIN_HOURLY_RATE DECIMAL(10, 2),
	PORTAL_MAX_HOURLY_RATE DECIMAL(10, 2)

)
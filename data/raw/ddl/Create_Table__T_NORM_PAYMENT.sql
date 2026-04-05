/*
 * Payment table. Each record in T_NORM_PAYMENT represents a payment made by the insurance company for a specific claim, specified by CLAIM_ID.
 * This table can be joined with T_NORM_CLAIM using the CLAIM_ID column to get the claim record associated with each payment.
 *
 * To link a payment to a bank account, join with T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK
 * on NORM_PAYMENT_ID, then join T_RESOLVED_BANK_ACCOUNT on RES_BANK_ACCOUNT_ID.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_PAYMENT
(
    NORM_PAYMENT_ID     BIGINT,         /* Primary key. Unique identifier for each payment record. */
    PAYMENT_DATE        DATE,           /* Date on which this payment was issued. */
    PAYMENT_AMT         DECIMAL(18,2),  /* Amount paid in this payment transaction. */
    PAYMENT_STATUS      VARCHAR(50),    /* Current status of this payment */
	CLAIM_ID 			VARCHAR(15)		/* Foreign key to T_NORM_CLAIM. Join on CLAIM_ID to retrieve CLAIM_NUMBER. */
)
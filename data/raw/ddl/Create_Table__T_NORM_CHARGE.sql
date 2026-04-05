/*
 * Charge table. Each row represents a single charge line item on an invoice.
 * An invoice (T_NORM_INVOICE) can have multiple charge records.
 *
 * Join T_NORM_CHARGE with T_NORM_INVOICE on NORM_INVOICE_ID to retrieve invoice-level
 * context such as CLAIM_ID, PROVIDER_ID, and invoice status.
 *
 * To reach claim number from charges:
 * T_NORM_CHARGE → T_NORM_INVOICE (on NORM_INVOICE_ID) → T_NORM_CLAIM (on CLAIM_ID)
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_CHARGE
(
    NORM_CHARGE_ID      BIGINT,         /* Primary key. Unique identifier for each charge record. */
    CHARGE_DATE         DATE,           /* Date on which the care service for this charge was rendered. */
    CHARGE_AMT          DECIMAL(10,2),  /* Billed amount for this individual charge line. */
    PAYMENT_AMT         DECIMAL(10,2),  /* Amount approved for payment on this charge. May differ from CHARGE_AMT if partially approved. */
	NORM_INVOICE_ID 	INT 			/* Foreign key to T_NORM_INVOICE */
)
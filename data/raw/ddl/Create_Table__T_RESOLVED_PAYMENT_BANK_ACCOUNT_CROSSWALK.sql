/*
 * Crosswalk table linking payments to resolved bank accounts.
 * Each row associates a payment record (T_NORM_PAYMENT) with a resolved bank account
 * (T_RESOLVED_BANK_ACCOUNT), identifying which bank account received a given payment.
 *
 * To find out the payment details, you can join this table with T_NORM_PAYMENT using the NORM_PAYMENT_ID column.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK
(
	NORM_PAYMENT_ID INT, 			/* Foreign key to T_NORM_PAYMENT. Identifies the payment in this association. */
	RES_BANK_ACCOUNT_ID BIGINT		/* Foreign key to T_RESOLVED_BANK_ACCOUNT. Identifies the bank account that received the payment. */
)
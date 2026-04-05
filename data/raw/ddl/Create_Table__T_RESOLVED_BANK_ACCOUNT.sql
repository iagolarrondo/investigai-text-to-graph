/*
Each record in T_RESOLVED_BANK_ACCOUNT represents a bank account record.

To find out the owner of the bank account, you can join this table with T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK
on the RES_BANK_ACCOUNT_ID column.

To find out payments going to this bank account, you can join this table with T_RESOLVED_PAYMENT_BANK_ACCOUNT_CROSSWALK
on the RES_BANK_ACCOUNT_ID column.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_BANK_ACCOUNT
(
	RES_BANK_ACCOUNT_ID BIGINT, /* Primary key */
	ROUTING_NUMBER VARCHAR(25),
	ACCOUNT_NUMBER VARCHAR(25)
)
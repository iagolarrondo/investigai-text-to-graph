/*
Each record in T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK corresponds to a bank account owned by a person.
This table can be joined with T_RESOLVED_BANK_ACCOUNT using the RES_BANK_ACCOUNT_ID column to get the bank account record associated with each person.
EDGE_NAME is always 'HOLD_BY'.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PERSON_BANK_ACCOUNT_CROSSWALK
(
	RES_BANK_ACCOUNT_ID INT, /* Foreign key for T_RESOLVED_BANK_ACCOUNT */
	EDGE_NAME VARCHAR(30),
	RES_PERSON_ID BIGINT /* Foreign key for T_RESOLVED_PERSON */
)
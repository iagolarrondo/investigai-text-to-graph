/* 
ICP work blocks table. Each entry in INVESTIGAI_ICP_WORK_BLOCKS corresponds to a work block where an ICP worked continuously without any gaps (i.e., there are no full days in the work block that the ICP did not work).
This table allows for a quick lookup work blocks associated with a given claim number or ICP.
This is particularly useful for answering no break questions of an ICP as we do not need to look at invoice or charge information to infer consecutive days that they worked and charged for.

IMPORTANT: CLAIM_ID field is a database internal primary key. It is not the same as CLAIM_NUMBER. If you need to find the claim number for a given claim, use CLAIM_NUMBER field with a WHERE clause to filter, NOT the CLAIM_ID field.
*/
CREATE TABLE {catalog_name}.{schema_name}.INVESTIGAI_ICP_WORK_BLOCKS
(
	WORK_BLOCK_ID VARCHAR(32) /* Unique identifier for the work block of a given ICP. A work block is a contiguous number of days an ICP worked without any gaps (i.e., there are no full days in the work block that the ICP did not work) */
    PROVIDER_ID BIGINT, /* Foreign key corresponding to the RES_PERSON_ID attribute in T_RESOLVED_PERSON */
	PROVIDER_NAME VARCHAR(60), /* Full name of ICP (i.e., FIRST_NAME LAST_NAME) */
	CLAIM_ID VARCHAR(50), /* Internal claim identifier that the ICP provided care for */
	CLAIM_NUMBER VARCHAR(50), /* Claim number of policyholder that the ICO provided care for */
	CLAIM_STATUS_CODE VARCHAR(25), /* Status of the claim (Active or Terminated) */
	START_DATE DATE, /* First date defining the beginning of the work block */
	END_DATE DATE, /* Last date defining the end of the work block */
    CHARGE_AMT INT, /* Total charge amount for all services provided by the ICP during the work block */
    NUM_DAYS_WORKED INT, /* Total number of days worked by the ICP during the work block */
)
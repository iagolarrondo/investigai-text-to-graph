/* 
 * Claim table. Each entry in T_NORM_CLAIM corresponds to a claim. Other tables can be joined to this table via CLAIM_ID key. 
 * To find out which policy this claim corresponds to, POLICY_NUMBER field can be used.
 * 
 * If you need to find the policyholder for a given claim, you can join T_NORM_CLAIM with T_RESOLVED_PERSON_POLICY_CROSSWALK on POLICY_NUMBER
 * where EDGE_NAME is 'IS_COVERED_BY'. RES_PERSON_ID will identify the policy holder.
 *
 * IMPORTANT: CLAIM_ID field is a database internal primary key. It is not the same as CLAIM_NUMBER. If you need to find the claim number for a given claim, use CLAIM_NUMBER field with a WHERE clause to filter, 
 * NOT the CLAIM_ID field.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_CLAIM
(
	CLAIM_ID VARCHAR(15),
	CLAIM_NUMBER VARCHAR(60),
	SOURCE_CLAIM_ID STRING,
	POLICY_NUMBER VARCHAR(200), /* Associated policy number for this claim. FK to T_NORM_POLICY. */
	FIRST_NAME VARCHAR(200), /* Claimant first name */
	LAST_NAME VARCHAR(200), /* Claimant last name */
	BIRTH_DATE DATETIME, /* Claimant birth date */
	CLAIM_OPEN_DATE DATETIME,
	CLAIM_CLOSE_DATE DATETIME,
	NOTIFICATION_DATE DATETIME,
	INCURRAL_DATE DATETIME,
	CLAIM_STATUS_CODE VARCHAR(200),
	CLAIM_SUB_STATUS_CODE VARCHAR(200),
	POLICY_STATUS VARCHAR(50),
	POLICY_SUB_STATUS VARCHAR(50),
	CLAIM_STATUS_DATE DATETIME,
	CLAIM_VALID_IND INT NOT NULL,
	TOOL_STATUS INT,
	CLAIM_SYSTEM VARCHAR(7) NOT NULL,
	TAX_QUALIFIED VARCHAR(25),
	CLINICAL_REVIEW_END_DATE DATETIME
)
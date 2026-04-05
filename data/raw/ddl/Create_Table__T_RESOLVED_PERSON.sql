/*
Person table. Each record corresponds to a person. Other tables can be joined to this table via RES_PERSON_ID key.
When you are returning records from T_RESOLVED_PERSON table, try to be explicit about the context of the person in the column names.
For example, if the person is spouse, you can name the column as SPOUSE_FIRST_NAME, instead of just FIRST_NAME and so on. Same goes for POA and HIPAA.

The person records include policyholders, policyholder contacts, ICPs (individual care providers) and claimants.
So T_RESOLVED_PERSON table can be used to find information about any of the above mentioned persons.
 
When you are searching for a person by name, such as an ICP or a claimant, always use the following format:
WHERE CONCAT(FIRST_NAME, ' ', LAST_NAME) = 'JOHN DOE'.
Do not use FIRST_NAME = 'JOHN' AND LAST_NAME = 'DOE' as it will not work for people with middle names.
This will ensure that we are matching on the full name of the person and bypass issues when it is not clear when a first or last name have more than one words. 
 */
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PERSON
(
	RES_PERSON_ID BIGINT,
	FIRST_NAME VARCHAR(100), /* All characters are in uppercase */
	MIDDLE_NAME VARCHAR(100),
	LAST_NAME VARCHAR(100), /* All characters are in uppercase */
	BIRTH_DATE DATE,
	SEX VARCHAR(10),
	SSN VARCHAR(15), /* Social security number */
	DEATH_DATE DATE,
	DECEASED_IND INT /* DECEASED_IND=1 indicates that the person has deceased, and the death date can be found in DEATH_DATE column. */
)
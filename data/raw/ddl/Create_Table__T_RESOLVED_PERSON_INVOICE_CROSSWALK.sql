/*
  Each entry in T_RESOLVED_PERSON_INVOICE_CROSSWALK corresponds to a relationship between a person (identified by RES_PERSON_ID) and an invoice (identified by NORM_INVOICE_ID).
  The EDGE_NAME column identifies the type of relationship. It can have the following values:
	- ASSESS_INVOICE: The person assessed the invoice.
	- PROVIDED_CARE_ON_INVOICE: The person was the care provider for the given invoice.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_PERSON_INVOICE_CROSSWALK
(
	RES_PERSON_ID INT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	NORM_INVOICE_ID INT
)
/*
  Each entry in T_RESOLVED_BUSINESS_INVOICE_CROSSWALK corresponds to a relationship between a business (identified by RES_BUSINESS_ID) and an invoice (identified by NORM_INVOICE_ID).
  The EDGE_NAME column identifies the type of relationship. It can only have the following value:
  - PROVIDED_CARE_ON_INVOICE: The business was the care provider for the given invoice.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_RESOLVED_BUSINESS_INVOICE_CROSSWALK
(
	RES_BUSINESS_ID BIGINT,
	EDGE_NAME VARCHAR(30),
	EDGE_DETAIL VARCHAR(200),
	EDGE_DETAIL_DSC VARCHAR(50),
	NORM_INVOICE_ID INT
)
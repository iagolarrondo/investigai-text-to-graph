/*
Each record in T_NORM_POLICY corresponds to a policy record in the system. Other tables can be joined to T_NORM_POLICY via POLICY_NUMBER column.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_POLICY
(
	COMPANY_CODE VARCHAR(2),
	POLICY_NUMBER VARCHAR(15),
	-- POLICY_STATUS column describes the current status of the policy. It can have values such as 'Active', 'Terminated', 'Inactive', 'Suspended'. POLICY_SUB_STATUS column may have more information on the details of the policy status.
	POLICY_STATUS VARCHAR(50),
	POLICY_SUB_STATUS VARCHAR(100),
	PRODUCT_CODE VARCHAR(100), /* Type of policy product. */
	ISSUE_DATE DATE, /* Issue date of the policy. */
	ISSUE_STATE VARCHAR(2), /* Issue state of the policy. */
	BILLING_CODE VARCHAR(10),
	BILLING_MODE VARCHAR(20),
	PREMIUM_AMT NUMERIC(18, 2),
	TOTAL_PREMIUM_PAID NUMERIC(18, 2),
	TAX_QUALIFY_CODE VARCHAR(5),
	MODAL_PREMIUM NUMERIC(18, 2),
	POLICY_ADMIN_SYSTEM VARCHAR(10),
	-- DMB values are daily maximum benefits for different care settings
	ALF_DMB NUMERIC(18, 2),
	NH_DMB NUMERIC(18, 2),
	HHC_DMB NUMERIC(18, 2),
	ICP_DMB NUMERIC(18, 2),
	-- MMB values are monthly maximum benefits for different care settings
	ALF_MMB NUMERIC(18, 2),
	NH_MMB NUMERIC(18, 2),
	HHC_MMB NUMERIC(18, 2),
	ICP_MMB NUMERIC(18, 2),
	IFRS_ALR_PADDED NUMERIC(18, 0),
	IFRS_DLR_PADDED NUMERIC(18, 0),
	BENEFIT_PERIOD VARCHAR(100),
	BENEFIT_INCREASE VARCHAR(100),
	ELIMINATION_PERIOD VARCHAR(100), /* Elimination period. i.e., the time passed before the insurance company starts to re-imburse the client. */
	PAIDUP_IND VARCHAR(1),
	PAIDUP_DESC VARCHAR(50),
	NFO_STATUS_IND VARCHAR(1)
)
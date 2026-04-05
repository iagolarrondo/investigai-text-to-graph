/*
Each row in T_NORM_ELIGIBILITY_REVIEW corresponds to a provider eligibility review for a particular benefit type.

REVIEW_DATE is the date when the eligibility review is conducted. STATUS column indicates the status of the review, and may contain information about the review result.
If the review is still pending, the STATUS values may be the following: "Pending", "Pending - Management Review", "Pending Requirements".
If the provider is denied, the STATUS values may be the following: "Provider Denied", "Denied - Ineligible", "Provider Denied- ICP Kit Offered".
If the provider is approved, the STATUS values may be the following: "Provider Approved", "Approved - Eligible".

BENEFIT_TYPE column indicates the care/benefit type for which the eligibility review was conducted.
*/
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_ELIGIBILITY_REVIEW
(
	NORM_ELIGIBILITY_REVIEW_ID INT IDENTITY(1,1) NOT NULL,
	STATUS VARCHAR(2000),
	REVIEW_TEXT VARCHAR(2000),
	DENIAL_REASON VARCHAR(2000),
	REVIEW_DATE DATETIME,
	BENEFIT_TYPE VARCHAR(200)
)
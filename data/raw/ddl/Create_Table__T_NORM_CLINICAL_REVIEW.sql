/*
 * Clinical review table. Each row is a clinical review for a claimant.
 * This table can be used for questions related to clinical reviews:
 * - COG impairment / no-touch status
 * - MMSE score
 * - Activities of Daily Living (ADL) assistance types and frequencies
 * - Diagnoses and medical necessity
 *
 * Each claimant can have multiple clinical reviews over time. The most recent review
 * reflects the claimant's current clinical status.
 *
 * IMPORTANT: DO NOT search for a claim number using CLAIM_ID field in T_NORM_CLINICAL_REVIEW.
 * Join it with T_NORM_CLAIM on CLAIM_ID, and then search for claim number in the CLAIM_NUMBER field of T_NORM_CLAIM.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_CLINICAL_REVIEW
(
    NORM_CLINICAL_REVIEW_ID BIGINT, /* Primary key. Unique identifier for each clinical review record. */
    CLAIM_ID VARCHAR(15), /* Foreign key to T_NORM_CLAIM. Join on CLAIM_ID to retrieve CLAIM_NUMBER. */
    START_DATE DATE, /* Start date of this clinical review period. */
    END_DATE DATE, /* End date of this clinical review period. If set to a large date like '9999-01-01', the claimant has been designated as no-touch (no future reviews scheduled). */
    EDUCATIONAL_LEVEL VARCHAR(100), /* Highest educational level attained by the claimant. */
    MEDICAL_NECESSITY VARCHAR(100), /* Indicator or description of whether care is deemed medically necessary. */
    ILLNESS_OR_INJURY VARCHAR(100), /* Primary illness or injury driving the long term care need. */

    /* Activities of Daily Living (ADL) — each ADL has two fields:
       *_ASSIST_TYPE: the type of assistance required (e.g., 'Hands on Assist', 'Independent', etc.).
       *_FREQ: the frequency at which assistance is needed (e.g., 'Daily', 'Weekly'). */
    BATHING_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for bathing. */
    BATHING_FREQ VARCHAR(100), /* Frequency of bathing assistance needed. */
    DRESSING_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for dressing. */
    DRESSING_FREQ VARCHAR(100), /* Frequency of dressing assistance needed. */
    EATING_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for eating. */
    EATING_FREQ VARCHAR(100), /* Frequency of eating assistance needed. */
    TOILETING_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for toileting. */
    TOILETING_FREQ VARCHAR(100), /* Frequency of toileting assistance needed. */
    TRANSFERRING_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for transferring (e.g., moving from bed to chair). */
    TRANSFERRING_FREQ VARCHAR(100), /* Frequency of transferring assistance needed. */
    CONTINENCE_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for continence management. */
    CONTINENCE_FREQ VARCHAR(100), /* Frequency of continence assistance needed. */
    AMBULATION_ASSIST_TYPE VARCHAR(100), /* Type of assistance required for ambulation (walking/movement). */
    AMBULATION_FREQ VARCHAR(100), /* Frequency of ambulation assistance needed. */

    MMSE_SCORE INT, /* Mini-Mental State Examination score (0–30). Measures cognitive function. Higher score = better cognitive function. Score <= 23 typically indicates cognitive impairment. */
    COG_IMPAIRMENT INT, /* 0/1 flag. 1 = claimant has cognitive (COG) impairment based on this review. Always use the most recent review record to determine current status. */
    CR_APPROVED_IND INT /* 0/1 flag. 1 = this clinical review was approved. */
)
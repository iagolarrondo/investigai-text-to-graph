/*
 * Review cycle remediation table. Each row represents a single remediation action
 * associated with a review cycle. Remediations are created when a review cycle
 * identifies issues that require a follow-up recovery or corrective action.
 *
 * A review cycle (T_NORM_REVIEW_CYCLE) can have multiple remediation records.
 * Join T_NORM_REVIEW_CYCLE_REMEDIATION with T_NORM_REVIEW_CYCLE on REVIEW_CYCLE_ID
 * to retrieve parent review cycle context such as CLAIM_NUMBER and STATUS_NAM.
 *
 * To reach claim number from remediations:
 * T_NORM_REVIEW_CYCLE_REMEDIATION → T_NORM_REVIEW_CYCLE (on REVIEW_CYCLE_ID) → CLAIM_NUMBER
 *
 * Financial fields summary:
 *   - REQUESTED_AMT:          amount formally requested for recovery from the provider/claimant
 *   - ACTUAL_RECOVERED_AMT:   amount actually recovered to date
 *   - UNRECOVERABLE_AMT:      portion of the requested amount deemed unrecoverable
 *   - ESTIMATED_RECOVERED_AMT: projected total recovery amount
 *   - ACTUARIAL_SAVINGS:      broader actuarial savings realized through this remediation
 *                             (e.g., future claim cost avoidance), separate from direct recovery
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_REVIEW_CYCLE_REMEDIATION
(
    REVIEW_CYCLE_REMEDIATION_ID INT,            /* Primary key. Unique identifier for each remediation record. */
    REVIEW_CYCLE_ID             INT,            /* Foreign key to T_NORM_REVIEW_CYCLE. Join on REVIEW_CYCLE_ID to retrieve review cycle context including CLAIM_NUMBER. */
    ACTUAL_RECOVERED_AMT        DECIMAL(15, 2), /* Dollar amount actually recovered from the provider or claimant as a result of this remediation. */
    ESTIMATED_RECOVERED_AMT     DECIMAL(15, 2), /* Projected total dollar amount expected to be recovered through this remediation. */
    REQUESTED_AMT               DECIMAL(15, 2), /* Dollar amount formally requested for recovery. This is the demand amount at the remediation level. */
    ACTUARIAL_SAVINGS           DECIMAL(15, 2), /* Actuarial savings in dollars attributed to this remediation (e.g., future claim cost avoidance beyond direct recovery). */
    UNRECOVERABLE_AMT           DECIMAL(15, 2), /* Portion of the requested amount that has been deemed unrecoverable. */
    SOCIAL_MEDIA_FLAG_IND       INT,            /* 0/1 flag. 1 = this remediation has an associated social media flag or finding. */
    MANAGEMENT_SUMMARY_TXT      VARCHAR(8000),  /* Free-text management summary describing the remediation findings, actions taken, and outcomes. */
    CREATE_TS                   DATETIME,       /* Timestamp when this remediation record was created. */
    CREATE_USER_NAM             VARCHAR(80),    /* Username of the user who created this remediation record. */
    LAST_UPDATE_TS              DATETIME,       /* Timestamp of the most recent update to this remediation record. */
    LAST_UPDATE_USER_NAM        VARCHAR(80)     /* Username of the user who last updated this remediation record. */
)
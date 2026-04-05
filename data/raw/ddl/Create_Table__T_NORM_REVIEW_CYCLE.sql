/*
 * Review cycle table. Each row represents a single review cycle / investigation of a claim.
 * A claim can have multiple review cycles over time.
 *
 * IMPORTANT: This table contains CLAIM_NUMBER directly — you can filter on CLAIM_NUMBER
 * without joining to T_NORM_CLAIM. However, CLAIM_ID is also available as a FK to T_NORM_CLAIM
 * if joining to other claim-level data is needed.
 *
 * To get the most recent review cycle for a claim, filter on LAST_REVIEW_CYCLE_IND = 1.
 *
 * Each review cycle can have multiple metric records in T_NORM_REVIEW_CYCLE_METRIC
 * (joined on REVIEW_CYCLE_ID) and multiple remediation records in
 * T_NORM_REVIEW_CYCLE_REMEDIATION (joined on REVIEW_CYCLE_ID).
 *
 * REFERRAL_SOURCE_NAME possible values:
 *   - 'BIU Referral': Manual referral by business team
 *   - 'Data Driven Referral': Referral by fraud rule engine (LEAF) or novel scenario engine
 *   - 'Pilot Referral': Referral from pilot team
 *   - 'Manual Referral': Manual referral by business
 *
 * STATUS_NAM possible values:
 *   - 'Assign': The review cycle has been assigned to a user
 *   - 'Evaluate': The review cycle is in stage 1 evaluation
 *   - 'Investigate': The review cycle is in stage 2 investigation
 *   - 'Remediate': The review cycle is complete and remediated (money was requested back)
 *
 * SUB_STATUS_NAM: if set to 'Clear', the case was closed with no fraud found.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_REVIEW_CYCLE
(
    REVIEW_CYCLE_ID             INT,                /* Primary key. Unique identifier for each review cycle record. */
    POLICY_NUMBER               VARCHAR(200),       /* Policy number associated with this review cycle. */
    CLAIM_ID                    VARCHAR(15),        /* Foreign key to T_NORM_CLAIM. Join on CLAIM_ID to retrieve additional claim-level data. */
    CLAIM_NUMBER                VARCHAR(60),        /* Claim number being investigated. Can be used directly in WHERE clause without joining T_NORM_CLAIM. */
    USER_NAM                    VARCHAR(80),        /* Username of the investigator assigned to this review cycle. */
    USER_ROLE_NAM               VARCHAR(80),        /* Role of the assigned user */
    REFERRAL_SOURCE_NAME        VARCHAR(80),        /* Source of the referral that triggered this review cycle. See header for possible values. */
    REFERRAL_SUB_SOURCE_NAME    VARCHAR(80),        /* More detailed sub-source of the referral (e.g., specific rule name or referral program). */
    SUMMARY_TXT                 VARCHAR(1000),      /* Free-text summary describing the reason or findings of this review cycle. */
    REVIEW_CYCLE_START_DATE     TIMESTAMP,          /* Start date and time of this review cycle. */
    REVIEW_CYCLE_END_DATE       DATE,               /* End date of this review cycle. NOTE: this field is never NULL even if the review cycle is still ongoing. */
    STATUS_NAM                  VARCHAR(80),        /* Current status of the review cycle. See header for possible values. */
    SUB_STATUS_NAM              VARCHAR(80),        /* Sub-status of the review cycle. A value of 'Clear' means the case was closed with no fraud found. */
    SUB_STATUS_DETAILS          VARCHAR(200),       /* Additional detail or explanation for the current sub-status. */
    COMMENT_TXT                 VARCHAR(8000),      /* Free-text comments and notes added by investigators during the review cycle. */
    IS_REFERRAL_REP_NAM         VARCHAR(50),        /* Name of the IS referral representative associated with this review cycle. */
    ICM_REVIEW_REP_NAM          VARCHAR(50),        /* Name of the ICM review representative associated with this review cycle. */
    DOI_STATE                   VARCHAR(15),        /* State of the Department of Insurance (DOI) relevant to this review cycle. */
    DEMAND_AMT                  DECIMAL(18, 2),     /* Dollar amount demanded for recovery if the review cycle resulted in a remediation. */
    REPORT_STATUS               VARCHAR(26),        /* Status of any formal report associated with this review cycle. */
    STATUS_DAYS                 INT,                /* Number of days the review cycle has been in its current status. */
    LAST_UPDATE_TS              DATETIME,           /* Timestamp of the last update made to this review cycle record. */
    REVIEW_CYCLE_COMPLETE_IND   INT,                /* 0/1 flag. 1 = this review cycle has been completed. */
    LAST_REVIEW_CYCLE_IND       INT                 /* 0/1 flag. 1 = this is the most recent review cycle for the claim. Use this to get the current review cycle. */
)
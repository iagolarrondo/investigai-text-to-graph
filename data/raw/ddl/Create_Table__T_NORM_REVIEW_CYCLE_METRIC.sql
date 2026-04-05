/*
 * Review cycle metric table. Each row represents a single metric evaluation
 * within a review cycle. A review cycle can have multiple metric records,
 * each evaluating a different fraud signal or compliance dimension.
 *
 * Join T_NORM_REVIEW_CYCLE_METRIC with T_NORM_REVIEW_CYCLE on REVIEW_CYCLE_ID
 * to retrieve parent review cycle context such as CLAIM_NUMBER and STATUS_NAM.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_REVIEW_CYCLE_METRIC
(
    REVIEW_CYCLE_METRIC_ID  INT,            /* Primary key. Unique identifier for each metric record. */
    REVIEW_CYCLE_ID         INT,            /* Foreign key to T_NORM_REVIEW_CYCLE. Join on REVIEW_CYCLE_ID to retrieve review cycle details. */
    METRIC_ID               DECIMAL(15, 3), /* Unique identifier for the metric. */
	METRIC_NAM              VARCHAR(200),   /* Name of the metric being evaluated. */
	METRIC_TYPE_NAM 		VARCHAR(20),	/* Type or category of the metric */
	METRIC_DSC 				VARCHAR(200),  	/* Description providing more detail about the metric. */
	SEVERITY 				VARCHAR(100), 	/* Severity of the fraud metric. */
	INITIAL_SOURCE_IND 		INT,			/* 0/1 flag. 1 = this metric was part of the initial referral that triggered the review cycle. */
	CLEAR_REASONS 			VARCHAR(8000) 	/* Reasons for clearing the metric, if applicable. */
)
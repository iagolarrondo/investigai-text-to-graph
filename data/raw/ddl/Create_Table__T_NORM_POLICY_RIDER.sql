/*
 * Each record in T_NORM_POLICY_RIDER corresponds to a rider
 * associated with a policy in the system.
 * When searching this table, use the POLICY_NUMBER field to
 * filter the records for a specific policy - do not do a direct filter
 * on RIDER_KEY or RIDER_VALUE, as these fields are not pre-determined.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_POLICY_RIDER
(
    NORM_POLICY_RIDER_ID BIGINT NOT NULL,
    SOURCE_SYSTEM VARCHAR(50), /* Source system: 'PROMISE' or 'LIFEPRO' */
    POLICY_NUMBER VARCHAR(15), /* Policy number, foreign key to T_NORM_POLICY */
    RIDER_KEY VARCHAR(50), /* Rider key/identifier */
    RIDER_VALUE VARCHAR(50) /* Rider value/details */
)
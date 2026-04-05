/*
 * Diagnosis table. Each row corresponds to a single diagnosis associated with a claim.
 * A claim can have multiple diagnosis records.
 *
 * This table can be used for questions related to:
 * - ICD-9 or ICD-10 diagnosis codes and descriptions for a claimant
 * - Diagnosis type
 * - Prognosis information
 * - Diagnosis category groupings (DX_CATEGORY)
 *
 * IMPORTANT: CLAIM_ID is a foreign key — do NOT use it to search for a claim by number.
 * Join T_NORM_DIAGNOSIS with T_NORM_CLAIM on CLAIM_ID and filter using the CLAIM_NUMBER field in T_NORM_CLAIM.
 */
CREATE TABLE {catalog_name}.{schema_name}.T_NORM_DIAGNOSIS
(
    NORM_DIAGNOSIS_ID BIGINT, /* Primary key. Unique identifier for each diagnosis record. */
    CLAIM_ID VARCHAR(15), /* Foreign key to T_NORM_CLAIM. Join on CLAIM_ID to retrieve CLAIM_NUMBER. */
    SOURCE_SYSTEM VARCHAR(50), /* Source system for the claim */
    ICD9_CODE VARCHAR(15), /* ICD-9 diagnosis code. May be null if only ICD-10 is available. */
    ICD9_DSC VARCHAR(200), /* Human-readable description corresponding to the ICD-9 code. */
    DIAGNOSIS_TYPE VARCHAR(100), /* Type of diagnosis (e.g., 'Debilitating', 'Preexisting', 'Precipitating'). */
    PROGNOSIS_DSC VARCHAR(100), /* Prognosis description associated with this diagnosis */
    ICD10_CODE VARCHAR(15), /* ICD-10 diagnosis code. Preferred over ICD-9 for more recent records. */
    DX_CATEGORY VARCHAR(50) /* High-level category grouping for the diagnosis (e.g., 'cancer', 'parkinson', etc.) */
)
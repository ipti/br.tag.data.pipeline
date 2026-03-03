# src/ml/features/feature_pipeline.py
"""
Feature engineering pipeline: raw DataFrame → encoded feature matrix.

Separated from neo4j_extractor.py to allow unit testing without a Neo4j connection.
All encoding decisions are driven by the dictionaries in schema.py —
no magic strings or hardcoded values here.

Key design decisions:
- Missing grades filled with -1 (not 0 or median): absence of a grade
  is meaningful information (school doesn't register grades for all students).
  Using -1 preserves the signal and lets tree models split on it explicitly.
- Missing IBGE fields are already filled in Cypher (UF proxy). If still null
  after extraction (e.g., State-level fields), they are filled with the
  column median here as a last resort.
- Temporal split is mandatory. Random split is explicitly forbidden because
  a student may appear in multiple school years, and test/train contamination
  would inflate metrics.
- Source flag columns (muni_freq_fonte etc.) are excluded from feature matrix
  but kept in DataFrame for monitoring.

References:
- Feature contracts: schema.py
- IBGE sparsity documentation: neo4_schema_and_tips.md §4.4
- Performance anti-patterns: neo4_schema_and_tips.md §6
"""
import logging
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from .schema import (
    STAGE_ENCODING, GRADE_LEVEL_ENCODING, ETHNICITY_ENCODING, RESIDENCE_ENCODING,
    FEATURES_EVASAO_EF1, FEATURES_NOTAS_EF2, NEVER_NULL_AFTER_IMPUTE,
    TARGET_DROPOUT, TARGET_GRADE, TARGET_REPROVACAO, ID_COLS,
)

logger = logging.getLogger(__name__)

# Source/flag columns that should not be included in the model feature matrix
_SOURCE_FLAG_COLS = ["muni_freq_fonte", "muni_atraso_fonte", "muni_analf_fonte"]


def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply label encoding to raw categorical columns.

    Converts the '_raw' suffix columns produced by neo4j_extractor.py
    into numeric encoded columns. Encoding dictionaries come from schema.py.
    Unknown values default to the 'unknown' category (5 for ethnicity, etc.).

    Also computes derived features that require multiple columns:
    - n_health_conditions: sum of health boolean flags
    - muni_delta_freq: student's absence rate minus municipal benchmark

    Args:
        df: Raw DataFrame from Neo4jExtractor (contains _raw suffix columns).

    Returns:
        New DataFrame with encoded columns added. Original _raw columns kept
        for debugging but excluded from FEATURES_* lists in schema.py.

    Raises:
        KeyError: if a required _raw column is missing from df.
    """
    out = df.copy()

    out["ethnicity_enc"]      = out["ethnicity_raw"].map(ETHNICITY_ENCODING).fillna(5).astype(int)
    out["stage_enc"]          = out["stage_raw"].map(STAGE_ENCODING).fillna(1).astype(int)
    out["grade_level_enc"]    = out["grade_level_raw"].map(GRADE_LEVEL_ENCODING).fillna(1).astype(int)
    out["residence_zone_enc"] = out["residence_zone_raw"].map(RESIDENCE_ENCODING).fillna(2).astype(int)

    # Derived health aggregate — sum of boolean conditions
    health_bool_cols = [
        "has_malnutrition", "has_diabetes", "has_hypertension",
        "has_obesity", "has_celiac", "has_anemia",
    ]
    out["n_health_conditions"] = out[health_bool_cols].fillna(0).astype(int).sum(axis=1)

    # Delta vs municipal benchmark (computed from already-filled IBGE and attendance)
    # Both inputs are already filled in Cypher, so this rarely produces NaN
    if "taxa_ausencia" in out.columns and "muni_freq_liq_fund" in out.columns:
        out["muni_delta_freq"] = np.where(
            out["taxa_ausencia"].notna() & out["muni_freq_liq_fund"].notna(),
            out["taxa_ausencia"] * 100 - (100.0 - out["muni_freq_liq_fund"]),
            np.nan,
        )

    _validate_never_null(out)
    return out


def build_imputer_pipeline(feature_cols: list[str]) -> Pipeline:
    """
    Build a sklearn imputation + scaling pipeline for a given feature list.

    Imputation strategy:
    - Median imputation for all columns. This handles any residual nulls
      (e.g., State-level PNAD fields that have no UF proxy because they are
      computed from PNAD and may legitimately be absent for all students of a state).
    - NOTE: grade columns (nota_*) with null values should be filled with -1
      BEFORE calling this pipeline, to preserve the 'no grade registered' signal.
      Pass the DataFrame through fill_grade_sentinel() first.

    Args:
        feature_cols: List of column names to include in the pipeline.
                      Must match schema.py FEATURES_* lists.

    Returns:
        Fitted sklearn Pipeline (impute → scale).
    """
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale",  StandardScaler()),
    ])


def fill_grade_sentinel(df: pd.DataFrame, grade_cols: list[str], sentinel: float = -1.0) -> pd.DataFrame:
    """
    Fill null grade columns with a sentinel value before imputation.

    Schools that do not register grades produce null grade columns for all their
    students. Filling with -1 (instead of median or 0) lets tree models learn
    that 'no grade registered' is a distinct state from a real grade.

    Additionally, if a student has ONLY zeros in all their available grade columns,
    this is considered a system fallback for "no grades" and is masked to null
    before applying the sentinel.

    Args:
        df: DataFrame with grade columns.
        grade_cols: Columns to fill (typically GRADE_EF1_FEATURES or GRADE_EF2_FEATURES).
        sentinel: Value to fill nulls with. Default -1.0.

    Returns:
        DataFrame with null grade values replaced by sentinel.
    """
    out = df.copy()
    available_cols = [c for c in grade_cols if c in out.columns]
    
    if available_cols:
        grade_data = out[available_cols]
        # Mask students whose max and min grade is exactly 0.0 (all non-null grades are 0)
        max_grades = grade_data.max(axis=1)
        min_grades = grade_data.min(axis=1)
        all_zeros_mask = (max_grades == 0.0) & (min_grades == 0.0)
        
        # Only mask as NaN if the student's status is NOT explicitly "REPROVADO"
        if "aluno_reprovado_flag" in out.columns:
            all_zeros_mask = all_zeros_mask & (out["aluno_reprovado_flag"] == 0)

        out.loc[all_zeros_mask, available_cols] = np.nan

    for col in available_cols:
        out[col] = out[col].fillna(sentinel)
        
    return out


def temporal_split(
    df: pd.DataFrame,
    target_col: str,
    test_year: int,
    feature_cols: list[str],
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """
    Split data temporally: train = years < test_year, test = year == test_year.

    NEVER use random train_test_split on this dataset. The same student can
    appear in multiple school years (cr.year). A random split would put the
    same student in both train and test, creating data leakage that inflates
    all metrics.

    Args:
        df: Full encoded DataFrame with ano_letivo column.
        target_col: Name of the target column (e.g., TARGET_DROPOUT from schema.py).
        test_year: The school year to hold out as test set.
        feature_cols: Feature columns to include (from schema.py FEATURES_* lists).

    Returns:
        Tuple of (X_train, y_train, X_test, y_test) as DataFrames/Series.

    Raises:
        ValueError: if train or test split is empty after the cut.
    """
    train_mask = df["ano_letivo"] < test_year
    test_mask  = df["ano_letivo"] == test_year

    if train_mask.sum() == 0:
        raise ValueError(
            f"Temporal split produced empty train set (test_year={test_year}). "
            f"Available years: {sorted(df['ano_letivo'].unique())}"
        )
    if test_mask.sum() == 0:
        raise ValueError(
            f"Temporal split produced empty test set (test_year={test_year}). "
            f"Available years: {sorted(df['ano_letivo'].unique())}"
        )

    train = df[train_mask]
    test  = df[test_mask]

    # Validate feature columns exist
    missing = set(feature_cols) - set(df.columns)
    if missing:
        logger.warning("Features present in schema but missing from DataFrame: %s", missing)
        feature_cols = [c for c in feature_cols if c in df.columns]

    logger.info(
        "Temporal split: train=%d rows (%s) | test=%d rows (year=%d)",
        len(train),
        f"years {df[train_mask]['ano_letivo'].min()}–{df[train_mask]['ano_letivo'].max()}",
        len(test),
        test_year,
    )

    return (
        train[feature_cols], train[target_col],
        test[feature_cols],  test[target_col],
    )


def _validate_never_null(df: pd.DataFrame) -> None:
    """Warn if any column in NEVER_NULL_AFTER_IMPUTE still has nulls."""
    for col in NEVER_NULL_AFTER_IMPUTE:
        if col in df.columns and df[col].isna().any():
            n = df[col].isna().sum()
            logger.warning(
                "Column '%s' should never be null but has %d nulls after encoding", col, n
            )

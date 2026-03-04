import logging
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from .schema import (
    STAGE_ENCODING,
    GRADE_LEVEL_ENCODING,
    ETHNICITY_ENCODING,
    RESIDENCE_ENCODING,
    FEATURES_EVASAO_EF1,
    FEATURES_NOTAS_EF2,
    NEVER_NULL_AFTER_IMPUTE,
    TARGET_DROPOUT,
    TARGET_GRADE,
    TARGET_REPROVACAO,
    ID_COLS,
)

logger = logging.getLogger(__name__)

# Source/flag columns that should not be included in the model feature matrix
_SOURCE_FLAG_COLS = ["muni_freq_fonte", "muni_atraso_fonte", "muni_analf_fonte"]


def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply label encoding to raw categorical columns based on schema dictionaries.

    Converts the '_raw' suffix columns produced by neo4j_extractor.py
    into numeric encoded columns.
    Unknown values default to the 'unknown' category (e.g. 5 for ethnicity).

    Also computes derived features that require multiple columns:
    - n_health_conditions: sum of health boolean flags
    - muni_delta_freq: student's absence rate minus municipal benchmark

    Args:
        df (pd.DataFrame): Raw DataFrame from Neo4jExtractor containing _raw suffix columns.

    Raises:
        KeyError: If a required _raw column is missing from the input DataFrame.
        Exception: If unexpected types prevent proper mapping or calculations.

    Returns:
        pd.DataFrame: A new DataFrame with encoded columns added (original _raw columns are kept for debugging).
    """
    out = df.copy()

    out["ethnicity_enc"] = (
        out["ethnicity_raw"].map(ETHNICITY_ENCODING).fillna(5).astype(int)
    )
    out["stage_enc"] = out["stage_raw"].map(STAGE_ENCODING).fillna(1).astype(int)
    out["grade_level_enc"] = (
        out["grade_level_raw"].map(GRADE_LEVEL_ENCODING).fillna(1).astype(int)
    )
    out["residence_zone_enc"] = (
        out["residence_zone_raw"].map(RESIDENCE_ENCODING).fillna(2).astype(int)
    )

    # Derived health aggregate — sum of boolean conditions
    health_bool_cols = [
        "has_malnutrition",
        "has_diabetes",
        "has_hypertension",
        "has_obesity",
        "has_celiac",
        "has_anemia",
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
    Build a sklearn imputation and scaling pipeline for a given feature list.

    Imputation strategy:
    Uses median imputation for all columns to handle residual nulls.
    Note: Grade columns (nota_*) with null values must be filled with -1 before calling this pipeline, using fill_grade_sentinel().

    Args:
        feature_cols (list[str]): List of column names to include in the pipeline. Must match schema.py FEATURES_* lists.

    Raises:
        Exception: If pipeline creation fails due to invalid parameters.

    Returns:
        Pipeline: Untrained sklearn Pipeline containing 'impute' and 'scale' steps.
    """
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median")),
            ("scale", StandardScaler()),
        ]
    )


def fill_grade_sentinel(
    df: pd.DataFrame, grade_cols: list[str], sentinel: float = -1.0
) -> pd.DataFrame:
    """
    Fill null grade columns with a sentinel value before imputation.

    This preserves the 'no grade registered' signal for tree models.
    Also masks students with ONLY zero grades as null before applying the sentinel (if not 'REPROVADO').

    Args:
        df (pd.DataFrame): DataFrame containing expected grade columns.
        grade_cols (list[str]): List of grade column names to fill.
        sentinel (float, optional): The numerical value to fill nulls with. Defaults to -1.0.

    Raises:
        KeyError: If an expected check like 'aluno_reprovado_flag' relies on missing DataFrame columns without appropriate handling.
        Exception: If computation fails.

    Returns:
        pd.DataFrame: DataFrame with all specified null grade values successfully replaced by the sentinel.
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
    Split data temporally into train and test sets to prevent data leakage.

    Splits by putting years < test_year in train and years == test_year in test.
    This replaces random splits as a single student may appear in multiple years.

    Args:
        df (pd.DataFrame): Full encoded DataFrame containing an 'ano_letivo' column and features.
        target_col (str): The column name to use as target variable.
        test_year (int): The school year corresponding to the hold-out test set.
        feature_cols (list[str]): List of features to include in the returned DataFrames.

    Raises:
        ValueError: If train or test split is completely empty after applying the temporal cut.
        KeyError: If target_col or required features are not present.

    Returns:
        tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]: Specifically (X_train, y_train, X_test, y_test).
    """
    train_mask = df["ano_letivo"] < test_year
    test_mask = df["ano_letivo"] == test_year

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
    test = df[test_mask]

    # Validate feature columns exist
    missing = set(feature_cols) - set(df.columns)
    if missing:
        logger.warning(
            "Features present in schema but missing from DataFrame: %s", missing
        )
        feature_cols = [c for c in feature_cols if c in df.columns]

    logger.info(
        "Temporal split: train=%d rows (%s) | test=%d rows (year=%d)",
        len(train),
        f"years {df[train_mask]['ano_letivo'].min()}–{df[train_mask]['ano_letivo'].max()}",
        len(test),
        test_year,
    )

    return (
        train[feature_cols],
        train[target_col],
        test[feature_cols],
        test[target_col],
    )


def _validate_never_null(df: pd.DataFrame) -> None:
    """
    Warn if any column in NEVER_NULL_AFTER_IMPUTE still has nulls.

    Args:
        df (pd.DataFrame): The DataFrame to validate.

    Raises:
        None

    Returns:
        None
    """
    for col in NEVER_NULL_AFTER_IMPUTE:
        if col in df.columns and df[col].isna().any():
            n = df[col].isna().sum()
            logger.warning(
                "Column '%s' should never be null but has %d nulls after encoding",
                col,
                n,
            )

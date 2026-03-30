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
    MUNICIPAL_FEATURES,
    STATE_QEDU_FEATURES,
    STATE_PNAD_FEATURES,
)

logger = logging.getLogger(__name__)

# Source/flag columns that should not be included in the model feature matrix
_SOURCE_FLAG_COLS = ["muni_freq_fonte", "muni_atraso_fonte", "muni_analf_fonte"]


def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply label encoding to raw categorical columns based on schema dictionaries.

    Converts the '_raw' suffix columns produced by neo4j_extractor.py
    into numeric encoded columns in-place.
    Unknown values default to the 'unknown' category (e.g. 5 for ethnicity).

    Also computes derived features that require multiple columns:
    - n_health_conditions: sum of health boolean flags
    - muni_delta_freq: student's absence rate minus municipal benchmark

    Args:
        df (pd.DataFrame): Raw DataFrame from Neo4jExtractor containing _raw suffix columns. Modifies directly.

    Returns:
        pd.DataFrame: The same DataFrame modified in-place to avoid peak memory allocations.
    """
    if "ethnicity_raw" in df.columns:
        df["ethnicity_enc"] = (
            df["ethnicity_raw"].map(ETHNICITY_ENCODING).fillna(5).astype(int)
        )
    if "stage_raw" in df.columns:
        df["stage_enc"] = df["stage_raw"].map(STAGE_ENCODING).fillna(1).astype(int)
    if "grade_level_raw" in df.columns:
        df["grade_level_enc"] = (
            df["grade_level_raw"].map(GRADE_LEVEL_ENCODING).fillna(1).astype(int)
        )
    if "residence_zone_raw" in df.columns:
        df["residence_zone_enc"] = (
            df["residence_zone_raw"].map(RESIDENCE_ENCODING).fillna(2).astype(int)
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
    # Check which health columns actually exist
    existing_health = [c for c in health_bool_cols if c in df.columns]
    if existing_health:
        df["n_health_conditions"] = (
            df[existing_health].fillna(0).astype(int).sum(axis=1)
        )

    # Delta vs municipal benchmark
    if "taxa_ausencia" in df.columns and "muni_freq_liq_fund" in df.columns:
        df["muni_delta_freq"] = np.where(
            df["taxa_ausencia"].notna() & df["muni_freq_liq_fund"].notna(),
            df["taxa_ausencia"] * 100 - (100.0 - df["muni_freq_liq_fund"]),
            np.nan,
        )

    _validate_never_null(df)
    return df


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
        df (pd.DataFrame): DataFrame containing expected grade columns. In-place modification.
        grade_cols (list[str]): List of grade column names to fill.
        sentinel (float, optional): The numerical value to fill nulls with. Defaults to -1.0.

    Returns:
        pd.DataFrame: DataFrame modified in-place to avoid deepcopy memory overheads.
    """
    available_cols = [c for c in grade_cols if c in df.columns]

    if available_cols:
        grade_data = df[available_cols]
        # Mask students whose max and min grade is exactly 0.0 (all non-null grades are 0)
        max_grades = grade_data.max(axis=1)
        min_grades = grade_data.min(axis=1)
        all_zeros_mask = (max_grades == 0.0) & (min_grades == 0.0)

        # Only mask as NaN if the student's status is NOT explicitly "REPROVADO"
        if "aluno_reprovado_flag" in df.columns:
            all_zeros_mask = all_zeros_mask & (df["aluno_reprovado_flag"] == 0)

        df.loc[all_zeros_mask, available_cols] = np.nan

    for col in available_cols:
        df[col] = df[col].fillna(sentinel)

    return df


def fill_missing_values(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill remaining NaN values with semantically correct strategies per feature group.

    Must be called AFTER fill_grade_sentinel() (which handles grade columns with -1 sentinel)
    and AFTER encode_categoricals() (which handles demographic encodings).

    Strategies:
    - Attendance (taxa_ausencia, falta_critica, total_faltas_abs): -1 sentinel.
      Null means the school does not use an electronic attendance journal (tem_diario=0).
      It is NOT zero absences — it is absence of data. -1 is consistent with grade sentinel.
    - Health booleans (has_malnutrition, etc.): 0.
      Null means the Health node is absent in Neo4j, i.e., no condition was registered.
    - Municipal + State socioeconomic indicators: column median.
      These are regional statistics (IBGE/INEP) with no meaningful "unknown" value.
      Median of the training sample is a reasonable proxy for missing regions.

    Args:
        df (pd.DataFrame): DataFrame post encode_categoricals and fill_grade_sentinel.

    Returns:
        pd.DataFrame: DataFrame modified in-place.
    """
    # Attendance sentinel: -1 signals "school has no electronic journal" (not zero absences)
    att_cols = [
        c
        for c in ["taxa_ausencia", "falta_critica", "total_faltas_abs"]
        if c in df.columns
    ]
    if att_cols:
        n_null = df[att_cols].isna().sum().sum()
        df[att_cols] = df[att_cols].fillna(-1.0)
        logger.info(
            "fill_missing_values: attendance sentinel -1 applied to %d NaN cells",
            n_null,
        )

    # Health booleans: 0 = no Health node = no condition registered
    health_bool_cols = [
        c
        for c in [
            "has_malnutrition",
            "has_diabetes",
            "has_hypertension",
            "has_obesity",
            "has_celiac",
            "has_anemia",
        ]
        if c in df.columns
    ]
    if health_bool_cols:
        n_null = df[health_bool_cols].isna().sum().sum()
        df[health_bool_cols] = df[health_bool_cols].fillna(0)
        logger.info(
            "fill_missing_values: health booleans filled 0 for %d NaN cells", n_null
        )

    # Municipal + State socioeconomic indicators: median imputation
    socio_cols = [
        c
        for c in (MUNICIPAL_FEATURES + STATE_QEDU_FEATURES + STATE_PNAD_FEATURES)
        if c in df.columns
    ]
    if socio_cols:
        n_null = df[socio_cols].isna().sum().sum()
        df[socio_cols] = df[socio_cols].fillna(df[socio_cols].median())
        logger.info(
            "fill_missing_values: socioeconomic median fill for %d NaN cells", n_null
        )

    return df


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
        max_year = df["ano_letivo"].max()
        if test_year > max_year:
            logger.warning(
                "Requested test_year=%d not found in data. Falling back to maximum available year=%d",
                test_year,
                max_year,
            )
            test_year = max_year
            train_mask = df["ano_letivo"] < test_year
            test_mask = df["ano_letivo"] == test_year
            if train_mask.sum() == 0 or test_mask.sum() == 0:
                raise ValueError("Fallback still produced an empty set.")
        else:
            raise ValueError(
                f"Temporal split produced empty test set (test_year={test_year}). "
                f"Available years: {sorted(df['ano_letivo'].unique())}"
            )

    # Validate feature columns exist before masking
    missing = set(feature_cols) - set(df.columns)
    if missing:
        logger.warning(
            "Features present in schema but missing from DataFrame: %s", missing
        )
        feature_cols = [c for c in feature_cols if c in df.columns]

    logger.info(
        "Temporal split: train=%d rows (%s) | test=%d rows (year=%d)",
        train_mask.sum(),
        f"years {df.loc[train_mask, 'ano_letivo'].min()}–{df.loc[train_mask, 'ano_letivo'].max()}",
        test_mask.sum(),
        test_year,
    )

    X_train = df.loc[train_mask, feature_cols]
    y_train = df.loc[train_mask, target_col]
    X_test = df.loc[test_mask, feature_cols]
    y_test = df.loc[test_mask, target_col]

    return X_train, y_train, X_test, y_test


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

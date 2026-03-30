import numpy as np
import pandas as pd


def clean_dataframe_for_sql(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans a pandas DataFrame for SQL Server insertion using pyodbc with fastexecutemany.

    This function prepares a DataFrame for bulk insert by:
      - Replacing NaN and NaT values with None (so pyodbc inserts NULLs)
      - Converting float columns that only contain 0.0/1.0 to nullable integer (Int64), for BIT columns
      - Converting other float columns to float, with None for missing values
      - Converting boolean columns to nullable integer (Int64)
      - Converting datetime columns to native Python datetime objects, with None for missing values
      - Converting the 'bolsa_familia_participator' column to BIT (0/1) if present, using a robust mapping

    This is necessary because pyodbc with fastexecutemany expects native Python types and None for nulls.

    Args:
        df (pd.DataFrame): Input DataFrame to be cleaned.

    Returns:
        pd.DataFrame: Cleaned DataFrame suitable for SQL Server insertion.

    Example:
        >>> import pandas as pd
        >>> import numpy as np
        >>> from datetime import datetime
        >>> df = pd.DataFrame({
        ...     'float_col': [1.0, 0.0, np.nan],
        ...     'bool_col': [True, False, None],
        ...     'date_col': [datetime(2020, 1, 1), pd.NaT, datetime(2021, 1, 1)],
        ...     'bolsa_familia_participator': ['yes', 'no', None]
        ... })
        >>> clean_df = clean_dataframe_for_sql(df)
        >>> print(clean_df.dtypes)
        float_col                       Int64
        bool_col                        Int64
        date_col               datetime64[ns]
        bolsa_familia_participator      Int64
        dtype: object
        >>> print(clean_df)
           float_col  bool_col   date_col  bolsa_familia_participator
        0          1         1 2020-01-01                          1
        1          0         0        NaT                          0
        2       <NA>      <NA> 2021-01-01                       <NA>
    """
    df = df.copy(deep=False)
    df = df.replace({np.nan: None, pd.NaT: None})

    problematic_columns = [
        "contract_type",
        "role",
        "aggregated_stage",
        "regent",
        "discipline_1_fk",
        "discipline_2_fk",
        "discipline_3_fk",
        "discipline_4_fk",
        "discipline_5_fk",
        "discipline_6_fk",
        "discipline_7_fk",
        "discipline_8_fk",
        "discipline_9_fk",
        "discipline_10_fk",
        "discipline_11_fk",
        "discipline_12_fk",
        "discipline_13_fk",
        "discipline_14_fk",
        "discipline_15_fk",
        "edcenso_stage_vs_modality_fk",
        "Vaccine_id",
        "grade_faults_1",
        "grade_faults_2",
        "grade_faults_3",
        "grade_faults_4",
        "grade_faults_5",
        "grade_faults_6",
        "grade_faults_7",
        "grade_faults_8",
        "given_classes_1",
        "given_classes_2",
        "given_classes_3",
        "given_classes_4",
        "given_classes_5",
        "given_classes_6",
        "given_classes_7",
        "given_classes_8",
        "final_concept",
    ]

    for col in problematic_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

    for col in df.select_dtypes(include=[np.floating]).columns:
        if col in problematic_columns:
            continue

        non_null_vals = df[col].dropna()

        if len(non_null_vals) == 0:
            df[col] = df[col].astype("Int64")
        elif (non_null_vals % 1 == 0).all():
            df[col] = df[col].astype("Int64")
        else:
            df[col] = df[col].astype(float)
            df[col] = df[col].where(df[col].notnull(), None)

    for col in df.select_dtypes(include=["boolean"]).columns:
        df[col] = df[col].astype("Int64")

    for col in df.select_dtypes(include=["datetime"]).columns:
        df[col] = df[col].where(df[col].notnull(), None)

    bit_columns = {
        "bolsa_familia_participator",
        "celiac_desase",
        "diabetes_desease",
        "hypertension_desease",
        "iron_deficiency_anemia_desease",
        "lactose_intolerance_desease",
        "malnutrition_desease",
        "obesity_desease",
        "sickle_cell_anemia",
        "StudentBolsaFamilia",
    }

    for col in df.columns:
        if col in bit_columns:
            df[col] = (
                df[col]
                .apply(
                    lambda x: (
                        1
                        if str(x).strip().lower() in {"1", "1.0", "true", "yes"}
                        else (
                            0
                            if str(x).strip().lower() in {"0", "0.0", "false", "no"}
                            else None
                        )
                    )
                )
                .astype("Int64")
            )

    return df

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
    df = df.copy()
    df = df.replace({np.nan: None, pd.NaT: None})

    for col in df.select_dtypes(include=[np.floating]).columns:
        unique_vals = set(df[col].dropna().unique())
        if unique_vals.issubset({0.0, 1.0}):
            df[col] = df[col].astype("Int64")
        else:
            df[col] = df[col].astype(float)
            df[col] = df[col].where(df[col].notnull(), None)

    for col in df.select_dtypes(include=["boolean"]).columns:
        df[col] = df[col].astype("Int64")

    for col in df.select_dtypes(include=["datetime"]).columns:
        df[col] = df[col].dt.to_pydatetime()
        df[col] = df[col].where(df[col].notnull(), None)

    if "bolsa_familia_participator" in df.columns:
        df["bolsa_familia_participator"] = (
            df["bolsa_familia_participator"]
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

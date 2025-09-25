import numpy as np
import pandas as pd


def clean_dataframe_for_sql(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cleans a pandas DataFrame for SQL Server insertion using pyodbc with fastexecutemany.

    This function replaces NaN and NaT values with None, converts floating columns to float,
    and ensures datetime columns are Python datetime objects. These conversions are necessary
    because pyodbc with fastexecutemany requires native Python types and None for nulls to
    correctly insert data into SQL Server tables.

    Args:
        df (pd.DataFrame): Input DataFrame to be cleaned.

    Returns:
        pd.DataFrame: Cleaned DataFrame suitable for SQL Server insertion.
    """
    df = df.copy()

    df = df.replace({np.nan: None, pd.NaT: None})

    for col in df.select_dtypes(include=[np.floating]).columns:
        df[col] = df[col].astype(float)
        df[col] = df[col].where(df[col].notnull(), None)

    for col in df.select_dtypes(include=["datetime"]).columns:
        df[col] = df[col].dt.to_pydatetime()
        df[col] = df[col].where(df[col].notnull(), None)

    return df

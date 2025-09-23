import numpy as np
import pandas as pd

def clean_dataframe_for_sql(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df = df.replace({np.nan: None, pd.NaT: None})

    for col in df.select_dtypes(include=[np.floating]).columns:
        df[col] = df[col].astype(float)
        df[col] = df[col].where(df[col].notnull(), None)  

    for col in df.select_dtypes(include=["datetime"]).columns:
        df[col] = df[col].dt.to_pydatetime()
        df[col] = df[col].where(df[col].notnull(), None)

    return df
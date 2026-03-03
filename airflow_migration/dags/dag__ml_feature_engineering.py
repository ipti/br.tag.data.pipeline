# dags/dag__ml_feature_engineering.py
"""
Daily feature extraction DAG.

Extracts EF1 and EF2 features from Neo4j and saves as Parquet files.
Parquet acts as a cache layer between the graph and the training DAG,
so the training DAG can iterate without re-querying Neo4j each run.

Schedule: 3:00 AM daily (after any Neo4j data loads are expected to complete).
Output: /data/features/ef1_{date}.parquet and ef2_grades_{date}.parquet
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

_DEFAULT_ARGS = {
    "owner": "ml-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def extract_ef1_task(**ctx):
    """Extract EF1 features and save to Parquet."""
    import os, pandas as pd
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.feature_pipeline import encode_categoricals, fill_grade_sentinel
    from src.ml.features.schema import GRADE_EF1_FEATURES

    ext = Neo4jExtractor.from_env()
    df  = encode_categoricals(ext.extract_students_base("EF1"))
    df  = fill_grade_sentinel(df, GRADE_EF1_FEATURES)
    ext.close()

    out = f"/data/features/ef1_{ctx['ds_nodash']}.parquet"
    os.makedirs("/data/features", exist_ok=True)
    df.to_parquet(out, index=False)
    ctx["ti"].xcom_push(key="ef1_parquet", value=out)
    return out


def extract_ef2_task(**ctx):
    """Extract EF2 base features and grade pivot, then save to Parquet."""
    import os
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.feature_pipeline import encode_categoricals

    ext = Neo4jExtractor.from_env()
    df_base = encode_categoricals(ext.extract_students_base("EF2"))
    df_grades = ext.extract_ef2_grades()
    ext.close()

    out_base = f"/data/features/ef2_base_{ctx['ds_nodash']}.parquet"
    out_grades = f"/data/features/ef2_grades_{ctx['ds_nodash']}.parquet"
    df_base.to_parquet(out_base, index=False)
    df_grades.to_parquet(out_grades, index=False)
    ctx["ti"].xcom_push(key="ef2_base_parquet", value=out_base)
    ctx["ti"].xcom_push(key="ef2_grades_parquet", value=out_grades)
    return out_base


def extract_classrooms_task(**ctx):
    """
    Extract classroom-level features (Q15 God Matrix) and save to Parquet.

    Output can be joined to student rows by (school_id, classroom_name, ano_letivo).
    Used by enriched model training and school report endpoint.
    """
    import os
    from src.ml.features.neo4j_extractor import Neo4jExtractor

    ext = Neo4jExtractor.from_env()
    df  = ext.extract_classroom_features(segment="EF1")
    ext.close()

    out = f"/data/features/classrooms_ef1_{ctx['ds_nodash']}.parquet"
    df.to_parquet(out, index=False)
    ctx["ti"].xcom_push(key="classrooms_parquet", value=out)
    return out


with DAG(
    dag_id="dag__ml_feature_engineering",
    default_args=_DEFAULT_ARGS,
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "features"],
) as dag:
    t_ef1 = PythonOperator(task_id="extract_ef1", python_callable=extract_ef1_task)
    t_ef2 = PythonOperator(task_id="extract_ef2", python_callable=extract_ef2_task)
    t_classrooms = PythonOperator(task_id="extract_classrooms", python_callable=extract_classrooms_task)
    
    t_ef1 >> t_ef2
    t_ef1 >> t_classrooms

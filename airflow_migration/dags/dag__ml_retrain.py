# dags/dag__ml_retrain.py
"""
Weekly retrain DAG.

Runs every Monday at 4:00 AM, after the feature engineering DAG.
Pipeline: extract → validate → train → evaluate → compare → promote.

Retrain is triggered either on schedule or when the drift DAG sets
the retrain flag (/data/drift/retrain_needed.flag file exists).
"""
from datetime import datetime, timedelta
import subprocess, sys
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

_DEFAULT_ARGS = {"owner": "ml-team", "retries": 1, "retry_delay": timedelta(minutes=10)}


def validate_features_task(**ctx):
    """Check that EF1 Parquet has expected columns and non-null targets."""
    import pandas as pd, os
    from src.ml.features.schema import TARGET_DROPOUT, NEVER_NULL_AFTER_IMPUTE

    # Use most recent Parquet
    parquet_dir = "/data/features"
    files = sorted(f for f in os.listdir(parquet_dir) if f.startswith("ef1_"))
    if not files:
        raise RuntimeError(
            "No EF1 Parquet files found. Run feature engineering DAG first."
        )

    df = pd.read_parquet(f"{parquet_dir}/{files[-1]}")
    # Check target is not all-zero (would indicate extraction filter issue)
    pos_rate = df[TARGET_DROPOUT].mean()
    if pos_rate < 0.005:
        raise ValueError(
            f"Positive rate for {TARGET_DROPOUT} is {pos_rate:.4f} — suspiciously low."
        )

    for col in NEVER_NULL_AFTER_IMPUTE:
        if col in df.columns and df[col].isna().any():
            raise ValueError(
                f"Column '{col}' has nulls after encoding — check extraction query."
            )

    return {"n_rows": len(df), "pos_rate": round(pos_rate, 4)}


def train_evasao_task(**ctx):
    """Run dropout model training entrypoint as subprocess."""
    test_year = ctx["params"].get("test_year", datetime.now().year)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.ml.training.train_evasao",
            "--test-year",
            str(test_year),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Training failed:\n{result.stderr[-2000:]}")
    return {"returncode": result.returncode}


def train_notas_task(**ctx):
    """Run grade model training entrypoint as subprocess."""
    test_year = ctx["params"].get("test_year", datetime.now().year)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.ml.training.train_notas",
            "--test-year",
            str(test_year),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Grade model training failed:\n{result.stderr[-2000:]}")
    return {"returncode": result.returncode}


with DAG(
    dag_id="dag__ml_retrain",
    default_args=_DEFAULT_ARGS,
    schedule="0 4 * * 1",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    params={"test_year": datetime.now().year},
    tags=["ml", "retrain"],
) as dag:
    t_validate = PythonOperator(
        task_id="validate_features", python_callable=validate_features_task
    )
    t_train_evasao = PythonOperator(
        task_id="train_evasao", python_callable=train_evasao_task
    )
    t_train_notas = PythonOperator(
        task_id="train_notas", python_callable=train_notas_task
    )
    t_validate >> t_train_evasao >> t_train_notas

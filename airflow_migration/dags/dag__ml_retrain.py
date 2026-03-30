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


def _apply_storage_mode(ctx: dict) -> None:
    mode = ctx.get("params", {}).get("storage_mode", "local")
    if mode == "local":
        import os

        os.environ.pop("AZURE_STORAGE_ACCOUNT_NAME", None)


def validate_features_task(**ctx):
    """Check that EF1 Parquet has expected columns and non-null targets."""
    _apply_storage_mode(ctx)
    import pandas as pd, os
    from src.ml.features.schema import TARGET_DROPOUT, NEVER_NULL_AFTER_IMPUTE
    from src.ml.features._azure_storage import is_configured, get_fs, CONTAINER
    import glob

    fs = get_fs() if is_configured() else None

    # Use most recent Parquet
    if fs:
        pattern = f"{CONTAINER}/features/segment=EF1/year=*/run=*/delta.parquet"
        files = sorted(fs.glob(pattern))
    else:
        parquet_dir = "/opt/airflow/src/ml/data/features"
        files = sorted(glob.glob(f"{parquet_dir}/ef1_*_delta_*.parquet"))

    if not files:
        raise RuntimeError(
            "No EF1 Parquet files found. Run feature engineering DAG first."
        )

    if fs:
        df = pd.read_parquet(files[-1], filesystem=fs)
    else:
        df = pd.read_parquet(files[-1])
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
    _apply_storage_mode(ctx)

    # Pass storage mode to subprocess via env var if needed,
    # but _apply_storage_mode already unsets AZURE_STORAGE_ACCOUNT_NAME from os.environ
    # which is inherited by subprocess.run
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
    _apply_storage_mode(ctx)
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
    params={"test_year": datetime.now().year, "storage_mode": "local"},
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

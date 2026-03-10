# dags/dag__ml_drift_detection.py
"""
Weekly drift detection DAG.

Compares current week's feature distribution against the training reference
(saved at last retrain). If drift is detected on > 30% of key features,
sets a flag that triggers dag__ml_retrain on next schedule.

Uses Evidently AI for PSI (Population Stability Index) computation.
PSI > 0.2 per feature = significant drift.
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

_DEFAULT_ARGS = {"owner": "ml-team", "retries": 1, "retry_delay": timedelta(minutes=5)}
_DRIFT_SHARE_THRESHOLD = 0.30  # fraction of features drifted to trigger retrain


def _apply_storage_mode(ctx: dict) -> None:
    mode = ctx.get("params", {}).get("storage_mode", "local")
    if mode == "local":
        import os

        os.environ.pop("AZURE_STORAGE_ACCOUNT_NAME", None)


def detect_drift_task(**ctx):
    """Run Evidently drift report. Write retrain flag if drift exceeds threshold."""
    _apply_storage_mode(ctx)
    import json, os, pandas as pd
    import glob
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset
    from src.ml.features.schema import FEATURES_EVASAO_EF1
    from src.ml.features._azure_storage import is_configured, get_fs, CONTAINER
    import logging

    logger = logging.getLogger(__name__)

    run_nodash = ctx["ds_nodash"]
    fs = get_fs() if is_configured() else None

    if fs:
        # Search blob paths formatted as features/segment=EF1/year=*/run=*/delta.parquet
        pattern = f"{CONTAINER}/features/segment=EF1/year=*/run=*/delta.parquet"
        files = sorted(fs.glob(pattern))
    else:
        parquet_dir = "/opt/airflow/src/ml/data/features"
        files = sorted(glob.glob(f"{parquet_dir}/ef1_*_delta_*.parquet"))

    if len(files) < 2:
        return {
            "drift_detected": False,
            "reason": f"Not enough history for drift check (found {len(files)} files)",
        }

    # Grab the most recent run and the run prior to it.
    # Because of sort ordering, files[-1] is the newest, files[-2] is the older.
    logger.info("Comparing current %s vs reference %s", files[-1], files[-2])

    if fs:
        reference = pd.read_parquet(files[-2], filesystem=fs)
        current = pd.read_parquet(files[-1], filesystem=fs)
    else:
        reference = pd.read_parquet(files[-2])
        current = pd.read_parquet(files[-1])

    valid_cols = [
        c
        for c in FEATURES_EVASAO_EF1
        if c in reference.columns and c in current.columns
    ]
    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference[valid_cols], current_data=current[valid_cols])

    # Save report html
    tmp_report = f"/tmp/report_{run_nodash}.html"
    report.save_html(tmp_report)

    if fs:
        fs.put(tmp_report, f"{CONTAINER}/drift/report_{run_nodash}.html")
    else:
        drift_dir = "/opt/airflow/src/ml/data/drift"
        os.makedirs(drift_dir, exist_ok=True)
        import shutil

        shutil.copy(tmp_report, f"{drift_dir}/report_{run_nodash}.html")

    summary = report.as_dict()
    n_drifted = summary["metrics"][0]["result"]["number_of_drifted_columns"]
    n_total = summary["metrics"][0]["result"]["number_of_columns"]
    share = n_drifted / max(n_total, 1)

    drift_detected = share > _DRIFT_SHARE_THRESHOLD
    if drift_detected:
        if fs:
            with fs.open(f"{CONTAINER}/checkpoints/retrain_needed.flag", "w") as f:
                f.write(f"{run_nodash}\n")
        else:
            chk_dir = "/opt/airflow/src/ml/data/checkpoints"
            os.makedirs(chk_dir, exist_ok=True)
            with open(f"{chk_dir}/retrain_needed.flag", "w") as f:
                f.write(f"{run_nodash}\n")

        logger.warning(
            "DRIFT detected: %d/%d features drifted (%.0f%%). Retrain flag set.",
            n_drifted,
            n_total,
            share * 100,
        )
    else:
        logger.info(
            "No significant drift: %d/%d features drifted (%.0f%%)",
            n_drifted,
            n_total,
            share * 100,
        )

    return {
        "drift_detected": drift_detected,
        "n_drifted": n_drifted,
        "share": round(share, 3),
    }


with DAG(
    dag_id="dag__ml_drift_detection",
    default_args=_DEFAULT_ARGS,
    schedule="0 3 * * 3",  # Wednesday at 3AM
    start_date=datetime(2026, 1, 1),
    catchup=False,
    params={"storage_mode": "local"},
    tags=["ml", "drift"],
) as dag:
    t_drift = PythonOperator(task_id="detect_drift", python_callable=detect_drift_task)

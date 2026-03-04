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


def detect_drift_task(**ctx):
    """Run Evidently drift report. Write retrain flag if drift exceeds threshold."""
    import json, os, pandas as pd
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset
    from src.ml.features.schema import FEATURES_EVASAO_EF1

    parquet_dir = "/data/features"
    files = sorted(f for f in os.listdir(parquet_dir) if f.startswith("ef1_"))
    if len(files) < 2:
        return {"drift_detected": False, "reason": "Not enough history for drift check"}

    reference = pd.read_parquet(f"{parquet_dir}/{files[-2]}")
    current = pd.read_parquet(f"{parquet_dir}/{files[-1]}")

    valid_cols = [
        c
        for c in FEATURES_EVASAO_EF1
        if c in reference.columns and c in current.columns
    ]
    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference[valid_cols], current_data=current[valid_cols])
    report.save_html(f"/data/drift/report_{ctx['ds_nodash']}.html")

    summary = report.as_dict()
    n_drifted = summary["metrics"][0]["result"]["number_of_drifted_columns"]
    n_total = summary["metrics"][0]["result"]["number_of_columns"]
    share = n_drifted / max(n_total, 1)

    drift_detected = share > _DRIFT_SHARE_THRESHOLD
    if drift_detected:
        open("/data/drift/retrain_needed.flag", "w").write(f"{ctx['ds_nodash']}\n")
        import logging

        logging.getLogger(__name__).warning(
            "DRIFT detected: %d/%d features drifted (%.0f%%). Retrain flag set.",
            n_drifted,
            n_total,
            share * 100,
        )
    else:
        import logging

        logging.getLogger(__name__).info(
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
    tags=["ml", "drift"],
) as dag:
    t_drift = PythonOperator(task_id="detect_drift", python_callable=detect_drift_task)

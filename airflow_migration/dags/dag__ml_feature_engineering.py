# dags/dag__ml_feature_engineering.py
"""
Daily feature extraction DAG — incremental mode.

Tasks (sequential — one Neo4j query at a time, protects the 3 GB heap):
  extract_ef1_delta >> extract_ef2 >> extract_classrooms >> fine_tune

EF1:
  Already bootstrapped (EF1_{year}.parquet + watermark.json exist).
  Extracts only new/changed rows for open years going forward.

EF2 — first run:
  No EF2_{year}.parquet exists yet. Extracts ALL years (year=None) from
  Neo4j, splits by ano_letivo, writes EF2_{year}.parquet for every year
  found — including years the watermark marks as closed for EF1.
  This guarantees no EF2 student is missed on the first run.

EF2 — subsequent runs:
  Delta-only for current_years (same fingerprint logic as EF1).

Classrooms:
  Not incremental — aggregate rows change with every new enrollment.
  Full re-extraction for open years only (fast: thousands of rows).
"""
import shutil
from datetime import datetime, timedelta, date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

_DEFAULT_ARGS = {
    "owner": "ml-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

_FEATURES_DIR = Path("/opt/airflow/src/ml/data/features")


def _get_ds(ctx: dict) -> str:
    """Airflow 3.x removed ctx['ds'] — use logical_date instead."""
    if "ds" in ctx:
        return ctx["ds"]
    ld = ctx.get("logical_date") or ctx.get("data_interval_start")
    return ld.strftime("%Y-%m-%d")


def _get_ds_nodash(ctx: dict) -> str:
    return _get_ds(ctx).replace("-", "")


_ENCODE_BATCH = 200_000
MIN_DELTA_ROWS = 500


# ── Helpers ───────────────────────────────────────────────────────────────────


def _encode_parquet_inplace(src_path: Path, dst_path: Path) -> None:
    """Read src in batches, encode categoricals + fill sentinels, write dst."""
    from src.ml.features.feature_pipeline import (
        encode_categoricals,
        fill_grade_sentinel,
    )
    from src.ml.features.schema import GRADE_EF1_FEATURES

    same = src_path.resolve() == dst_path.resolve()
    write_path = dst_path.with_suffix(".tmp.parquet") if same else dst_path
    write_path.parent.mkdir(parents=True, exist_ok=True)

    writer: pq.ParquetWriter | None = None
    try:
        for batch in pq.ParquetFile(str(src_path)).iter_batches(
            batch_size=_ENCODE_BATCH
        ):
            df = batch.to_pandas()
            df = encode_categoricals(df)
            df = fill_grade_sentinel(df, GRADE_EF1_FEATURES)
            tbl = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(
                    str(write_path), tbl.schema, compression="snappy"
                )
            writer.write_table(tbl)
            del df, tbl
    finally:
        if writer:
            writer.close()
    if same:
        write_path.replace(dst_path)


def _ef2_is_bootstrapped(raw_dir: Path, current_years: list[int]) -> bool:
    """True if EF2_{year}.parquet exists for every current year."""
    return all((raw_dir / f"EF2_{y}.parquet").exists() for y in current_years)


def _get_raw_dir() -> Path:
    """Resolve src/ml/data/raw/ relative to neo4j_extractor.py."""
    from src.ml.features import neo4j_extractor as _mod

    return Path(_mod.__file__).parent.parent / "data" / "raw"


# ── Task 1: EF1 delta ─────────────────────────────────────────────────────────


def extract_ef1_delta_task(**ctx):
    """Delta-only EF1 extraction for open years. Skips closed years entirely."""
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.incremental.delta_extractor import DeltaExtractor
    from src.ml.features.incremental.watermark import Watermark

    run_date = date.fromisoformat(_get_ds(ctx))
    wm = Watermark()
    _FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    ext = Neo4jExtractor.from_env()
    try:
        results = DeltaExtractor(ext, segment="EF1").extract_delta(
            current_years=wm.current_years,
            run_date=run_date,
        )
    finally:
        ext.close()

    total_rows = 0
    encoded_paths: dict[str, str] = {}
    for year, delta_path in results.items():
        if delta_path is None:
            continue
        dst = _FEATURES_DIR / f"ef1_{year}_delta_{_get_ds_nodash(ctx)}.parquet"
        _encode_parquet_inplace(delta_path, dst)
        encoded_paths[str(year)] = str(dst)
        total_rows += pq.read_metadata(str(dst)).num_rows

    years_with_delta = [int(y) for y, p in results.items() if p is not None]
    wm.mark_run(run_date, years_with_delta)

    ctx["ti"].xcom_push(key="ef1_delta_paths", value=encoded_paths)
    ctx["ti"].xcom_push(key="ef1_delta_rows", value=total_rows)
    return encoded_paths


# ── Task 2: EF2 ───────────────────────────────────────────────────────────────


def extract_ef2_task(**ctx):
    """
    First run:  extracts ALL years (year=None) → splits into EF2_{year}.parquet.
                Guaranteed to capture every EF2 student regardless of year.
    Next runs:  delta-only for current_years (same fingerprint logic as EF1).

    EF2 grades (discipline pivot) always re-extracted for open years —
    pivots are aggregates that change whenever any grade changes.
    """
    import logging
    import pandas as pd

    logger = logging.getLogger(__name__)

    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.incremental.delta_extractor import DeltaExtractor
    from src.ml.features.incremental.watermark import Watermark

    run_date = date.fromisoformat(_get_ds(ctx))
    wm = Watermark()
    raw_dir = _get_raw_dir()
    _FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    ext = Neo4jExtractor.from_env()
    try:
        if not _ef2_is_bootstrapped(raw_dir, wm.current_years):
            # ── First run: full extraction, ALL years ─────────────────────────
            logger.info(
                "EF2 not bootstrapped — extracting ALL years from Neo4j. "
                "This run will take longer than subsequent delta runs."
            )
            raw_path = ext.extract_students_base("EF2", year=None)

            # Split into per-year Parquets (same layout as EF1 bootstrap)
            year_writers: dict[int, pq.ParquetWriter] = {}
            try:
                for batch in pq.ParquetFile(str(raw_path)).iter_batches(
                    batch_size=_ENCODE_BATCH
                ):
                    df = batch.to_pandas()
                    for year, group in df.groupby("ano_letivo"):
                        year = int(year)
                        tbl = pa.Table.from_pandas(group, preserve_index=False)
                        yr_path = raw_dir / f"EF2_{year}.parquet"
                        if year not in year_writers:
                            year_writers[year] = pq.ParquetWriter(
                                str(yr_path), tbl.schema, compression="snappy"
                            )
                            logger.info("Creating %s...", yr_path.name)
                        year_writers[year].write_table(tbl)
                        del tbl
            finally:
                for w in year_writers.values():
                    w.close()

            logger.info("EF2 bootstrap complete: %d year files.", len(year_writers))

            # Encode current years → features dir
            encoded_base: dict[str, str] = {}
            for year in wm.current_years:
                yr_path = raw_dir / f"EF2_{year}.parquet"
                if not yr_path.exists():
                    continue
                dst = _FEATURES_DIR / f"ef2_{year}_{_get_ds_nodash(ctx)}.parquet"
                _encode_parquet_inplace(yr_path, dst)
                encoded_base[str(year)] = str(dst)

        else:
            # ── Subsequent runs: delta only ───────────────────────────────────
            logger.info("EF2 bootstrapped — running delta extraction.")
            base_results = DeltaExtractor(ext, segment="EF2").extract_delta(
                current_years=wm.current_years,
                run_date=run_date,
            )
            encoded_base = {}
            for year, delta_path in base_results.items():
                if delta_path is None:
                    continue
                dst = _FEATURES_DIR / f"ef2_{year}_delta_{_get_ds_nodash(ctx)}.parquet"
                _encode_parquet_inplace(delta_path, dst)
                encoded_base[str(year)] = str(dst)

        # Grades: always re-extract for open years
        grades_path = ext.extract_ef2_grades()
    finally:
        ext.close()

    dst_grades = _FEATURES_DIR / f"ef2_grades_{_get_ds_nodash(ctx)}.parquet"
    shutil.copy2(grades_path, dst_grades)

    ctx["ti"].xcom_push(key="ef2_base_paths", value=encoded_base)
    ctx["ti"].xcom_push(key="ef2_grades_path", value=str(dst_grades))
    return encoded_base


# ── Task 3: classrooms ────────────────────────────────────────────────────────


def extract_classrooms_task(**ctx):
    """Full re-extraction for open years. Aggregate rows — not incremental."""
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.incremental.watermark import Watermark

    wm = Watermark()
    _FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    ext = Neo4jExtractor.from_env()
    try:
        raw_path = ext.extract_classroom_features(segment="EF1")
    finally:
        ext.close()

    written: dict[str, str] = {}
    for year in wm.current_years:
        dst = _FEATURES_DIR / f"classrooms_ef1_{year}_{_get_ds_nodash(ctx)}.parquet"
        writer: pq.ParquetWriter | None = None
        try:
            for batch in pq.ParquetFile(str(raw_path)).iter_batches(
                batch_size=_ENCODE_BATCH
            ):
                import pandas as pd

                df = batch.to_pandas()
                df = df[df["ano_letivo"] == year]
                if df.empty:
                    continue
                tbl = pa.Table.from_pandas(df, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(
                        str(dst), tbl.schema, compression="snappy"
                    )
                writer.write_table(tbl)
                del df, tbl
        finally:
            if writer:
                writer.close()
        if dst.exists():
            written[str(year)] = str(dst)

    ctx["ti"].xcom_push(key="classrooms_paths", value=written)
    return written


# ── Task 4: fine-tune ─────────────────────────────────────────────────────────


def fine_tune_task(**ctx):
    """Fine-tune on EF1 delta. Full re-train on Mondays."""
    import logging
    import pandas as pd

    logger = logging.getLogger(__name__)

    ti = ctx["ti"]
    run_date = date.fromisoformat(_get_ds(ctx))
    delta_rows = ti.xcom_pull(key="ef1_delta_rows", task_ids="extract_ef1_delta")
    delta_paths = ti.xcom_pull(key="ef1_delta_paths", task_ids="extract_ef1_delta")
    is_monday = run_date.weekday() == 0
    has_delta = (delta_rows or 0) >= MIN_DELTA_ROWS

    if not has_delta and not is_monday:
        logger.info("Skipping fine-tune: delta=%d rows, not Monday.", delta_rows or 0)
        return {"skipped": True, "reason": "insufficient_delta"}

    if is_monday:
        logger.info("Monday — full re-train across all years.")
        # TODO: implement full re-train
        return {"status": "full_retrain_placeholder"}

    dfs = [
        batch.to_pandas()
        for path in (delta_paths or {}).values()
        for batch in pq.ParquetFile(path).iter_batches(batch_size=_ENCODE_BATCH)
    ]
    if not dfs:
        return {"skipped": True, "reason": "empty_delta"}

    df_delta = pd.concat(dfs, ignore_index=True)
    logger.info("Fine-tuning on %d delta rows.", len(df_delta))
    # TODO: xgb.train(..., xgb_model=existing_model)
    return {"delta_rows": len(df_delta), "status": "fine_tune_placeholder"}


# ── DAG ───────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="dag__ml_feature_engineering",
    default_args=_DEFAULT_ARGS,
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "features", "incremental"],
) as dag:

    t_ef1_delta = PythonOperator(
        task_id="extract_ef1_delta", python_callable=extract_ef1_delta_task
    )
    t_ef2 = PythonOperator(task_id="extract_ef2", python_callable=extract_ef2_task)
    t_classrooms = PythonOperator(
        task_id="extract_classrooms", python_callable=extract_classrooms_task
    )
    t_finetune = PythonOperator(task_id="fine_tune", python_callable=fine_tune_task)

    # Sequential — one Neo4j query at a time to protect the 3 GB heap
    t_ef1_delta >> t_ef2 >> t_classrooms >> t_finetune

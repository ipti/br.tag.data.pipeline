# dags/dag__ml_feature_engineering.py
"""
Daily feature extraction DAG — incremental mode.

Tasks (sequential — one Neo4j query at a time, protects the 3 GB heap):
  extract_ef1_delta >> extract_ef2 >> extract_classrooms >> fine_tune

Storage backend is selected automatically:
- Azure Blob Storage when AZURE_STORAGE_ACCOUNT_NAME is set in the environment
- Local filesystem as fallback (development / CI)

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

import logging
import shutil
from datetime import datetime, timedelta, date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

logger = logging.getLogger(__name__)

_DEFAULT_ARGS = {
    "owner": "ml-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

# Local fallback paths (used only when Azure is not configured)
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


# ── Storage helpers ───────────────────────────────────────────────────────────


def _apply_storage_mode(ctx: dict) -> None:
    """Forces local storage if the user selects 'local' in DAG params."""
    mode = ctx.get("params", {}).get("storage_mode", "local")
    if mode == "local":
        import os

        os.environ.pop("AZURE_STORAGE_ACCOUNT_NAME", None)
        logger.info(
            "[storage] param 'storage_mode' is local. Forcing local fallback by unsetting Azure vars."
        )
    else:
        logger.info(
            "[storage] param 'storage_mode' is %s. Preserving environment vars.", mode
        )


def _get_azure_fs():
    """Return adlfs filesystem or None if not configured."""
    from src.ml.features._azure_storage import is_configured, get_fs
    import os

    if is_configured():
        account = os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", "?")
        logger.info(
            "[storage] mode=Azure  account=%s  container=machine-learning", account
        )
        return get_fs()
    logger.info("[storage] mode=local  fallback=%s", _FEATURES_DIR)
    return None


def _feature_blob_key(segment: str, year: int, run_nodash: str, kind: str) -> str:
    """adlfs-compatible features key: container/features/segment=.../..."""
    from src.ml.features._azure_storage import CONTAINER

    return f"{CONTAINER}/features/segment={segment}/year={year}/run={run_nodash}/{kind}.parquet"


def _raw_blob_key(segment: str, year: int) -> str:
    """adlfs-compatible raw key for a given segment+year."""
    from src.ml.features._azure_storage import CONTAINER

    return f"{CONTAINER}/raw/segment={segment}/year={year}/{segment}_{year}.parquet"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _encode_parquet_inplace(src: str | Path, dst: str | Path, fs=None) -> None:
    """Read src in batches, encode categoricals + fill sentinels, write dst.

    Works with both local paths (Path) and blob paths (str + fs).
    """
    from src.ml.features.feature_pipeline import (
        encode_categoricals,
        fill_grade_sentinel,
    )
    from src.ml.features.schema import GRADE_EF1_FEATURES

    src_str, dst_str = str(src), str(dst)
    same = src_str == dst_str
    write_dst = dst_str.replace(".parquet", "_tmp.parquet") if same else dst_str

    mode = "blob" if fs else "local"
    logger.info(
        "[encode] %s  src=%s  →  dst=%s",
        mode,
        src_str.split("/")[-1],
        dst_str.split("/")[-1],
    )

    if fs is None:
        Path(write_dst).parent.mkdir(parents=True, exist_ok=True)

    writer: pq.ParquetWriter | None = None
    pf = pq.ParquetFile(src_str, filesystem=fs) if fs else pq.ParquetFile(src_str)
    try:
        for batch in pf.iter_batches(batch_size=_ENCODE_BATCH):
            df = batch.to_pandas()
            df = encode_categoricals(df)
            df = fill_grade_sentinel(df, GRADE_EF1_FEATURES)
            tbl = pa.Table.from_pandas(df, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(
                    write_dst,
                    tbl.schema,
                    compression="snappy",
                    **({"filesystem": fs} if fs else {}),
                )
            writer.write_table(tbl)
            del df, tbl
    finally:
        if writer:
            writer.close()

    if same:
        if fs:
            fs.rm(dst_str)
            fs.copy(write_dst, dst_str)
            fs.rm(write_dst)
        else:
            Path(write_dst).replace(Path(dst_str))


def _ef2_is_bootstrapped(current_years: list[int], fs=None) -> bool:
    """True if EF2_{year}.parquet exists for every current year (blob or local)."""
    if fs is not None:
        return all(fs.exists(_raw_blob_key("EF2", y)) for y in current_years)
    raw_dir = _get_local_raw_dir()
    return all((raw_dir / f"EF2_{y}.parquet").exists() for y in current_years)


def _get_local_raw_dir() -> Path:
    """Resolve src/ml/data/raw/ relative to neo4j_extractor.py."""
    from src.ml.features import neo4j_extractor as _mod

    return Path(_mod.__file__).parent.parent / "data" / "raw"


# ── Task 1: EF1 delta ─────────────────────────────────────────────────────────


def extract_ef1_delta_task(**ctx):
    """Delta-only EF1 extraction for open years. Skips closed years entirely."""
    _apply_storage_mode(ctx)

    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.incremental.delta_extractor import DeltaExtractor
    from src.ml.features.incremental.watermark import Watermark

    run_date = date.fromisoformat(_get_ds(ctx))
    run_nodash = _get_ds_nodash(ctx)
    wm = Watermark()
    fs = _get_azure_fs()

    logger.info("[ef1_delta] run_date=%s  open_years=%s", run_date, wm.current_years)

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
            logger.info("[ef1_delta] year=%d  → no changes, skipping encode", year)
            continue
        if fs is not None:
            dst = _feature_blob_key("EF1", year, run_nodash, "delta")
        else:
            _FEATURES_DIR.mkdir(parents=True, exist_ok=True)
            dst = str(_FEATURES_DIR / f"ef1_{year}_delta_{run_nodash}.parquet")

        logger.info(
            "[ef1_delta] year=%d  src=%s  →  feature dst=%s",
            year,
            str(delta_path).split("/")[-1],
            dst,
        )
        _encode_parquet_inplace(delta_path, dst, fs=fs)
        encoded_paths[str(year)] = dst

        if fs is not None:
            total_rows += pq.read_metadata(dst, filesystem=fs).num_rows
        else:
            total_rows += pq.read_metadata(dst).num_rows

    years_with_delta = [int(y) for y, p in results.items() if p is not None]
    wm.mark_run(run_date, years_with_delta)

    logger.info(
        "[ef1_delta] done  years_with_delta=%s  total_rows=%d",
        years_with_delta,
        total_rows,
    )
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
    _apply_storage_mode(ctx)
    import pandas as pd

    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.incremental.delta_extractor import DeltaExtractor
    from src.ml.features.incremental.watermark import Watermark

    run_date = date.fromisoformat(_get_ds(ctx))
    run_nodash = _get_ds_nodash(ctx)
    wm = Watermark()
    fs = _get_azure_fs()

    logger.info("[ef2] run_date=%s  open_years=%s", run_date, wm.current_years)

    if fs is None:
        _FEATURES_DIR.mkdir(parents=True, exist_ok=True)
        raw_dir = _get_local_raw_dir()

    ext = Neo4jExtractor.from_env()
    try:
        if not _ef2_is_bootstrapped(wm.current_years, fs=fs):
            # ── First run: full extraction, ALL years ─────────────────────────
            logger.info(
                "[ef2] bootstrap=True — extracting ALL years from Neo4j (first run, takes longer)."
            )
            raw_path = ext.extract_students_base("EF2", year=None)
            logger.info("[ef2] raw extracted → %s", raw_path)

            # Split into per-year Parquets
            year_writers: dict[int, pq.ParquetWriter] = {}
            src_pf = (
                pq.ParquetFile(raw_path, filesystem=fs)
                if fs
                else pq.ParquetFile(str(raw_path))
            )
            try:
                for batch in src_pf.iter_batches(batch_size=_ENCODE_BATCH):
                    df = batch.to_pandas()
                    for year, group in df.groupby("ano_letivo"):
                        year = int(year)
                        tbl = pa.Table.from_pandas(group, preserve_index=False)
                        if fs is not None:
                            yr_dest = _raw_blob_key("EF2", year)
                        else:
                            yr_dest = str(raw_dir / f"EF2_{year}.parquet")
                        if year not in year_writers:
                            year_writers[year] = pq.ParquetWriter(
                                yr_dest,
                                tbl.schema,
                                compression="snappy",
                                **({"filesystem": fs} if fs else {}),
                            )
                            logger.info(
                                "[ef2] bootstrap  writing EF2_%d → %s", year, yr_dest
                            )
                        year_writers[year].write_table(tbl)
                        del tbl
            finally:
                for w in year_writers.values():
                    w.close()

            logger.info(
                "[ef2] bootstrap complete: %d year files written", len(year_writers)
            )

            encoded_base: dict[str, str] = {}
            for year in wm.current_years:
                if fs is not None:
                    yr_src = _raw_blob_key("EF2", year)
                    if not fs.exists(yr_src):
                        logger.info(
                            "[ef2] bootstrap  year=%d not found in blob, skipping encode",
                            year,
                        )
                        continue
                    dst = _feature_blob_key("EF2", year, run_nodash, "delta")
                else:
                    yr_src = str(raw_dir / f"EF2_{year}.parquet")
                    if not Path(yr_src).exists():
                        continue
                    dst = str(_FEATURES_DIR / f"ef2_{year}_{run_nodash}.parquet")
                logger.info("[ef2] bootstrap  encoding year=%d → %s", year, dst)
                _encode_parquet_inplace(yr_src, dst, fs=fs)
                encoded_base[str(year)] = dst

        else:
            # ── Subsequent runs: delta only ───────────────────────────────────
            logger.info("[ef2] bootstrap=False — delta extraction only.")
            base_results = DeltaExtractor(ext, segment="EF2").extract_delta(
                current_years=wm.current_years,
                run_date=run_date,
            )
            encoded_base = {}
            for year, delta_path in base_results.items():
                if delta_path is None:
                    logger.info("[ef2] delta  year=%d  → no changes", year)
                    continue
                if fs is not None:
                    dst = _feature_blob_key("EF2", year, run_nodash, "delta")
                else:
                    dst = str(_FEATURES_DIR / f"ef2_{year}_delta_{run_nodash}.parquet")
                logger.info("[ef2] delta  year=%d  → %s", year, dst)
                _encode_parquet_inplace(delta_path, dst, fs=fs)
                encoded_base[str(year)] = dst

        # Grades: always re-extract for open years
        grades_path = ext.extract_ef2_grades()
        logger.info("[ef2] grades extracted → %s", grades_path)
    finally:
        ext.close()

    if fs is not None:
        from src.ml.features._azure_storage import CONTAINER

        dst_grades = (
            f"{CONTAINER}/features/segment=EF2_grades/run={run_nodash}/grades.parquet"
        )
        logger.info("[ef2] grades  blob → %s", dst_grades)
        fs.put(str(grades_path), dst_grades)
    else:
        dst_grades = str(_FEATURES_DIR / f"ef2_grades_{run_nodash}.parquet")
        logger.info("[ef2] grades  local → %s", dst_grades)
        shutil.copy2(grades_path, dst_grades)

    logger.info("[ef2] done  encoded_years=%s", list(encoded_base.keys()))
    ctx["ti"].xcom_push(key="ef2_base_paths", value=encoded_base)
    ctx["ti"].xcom_push(key="ef2_grades_path", value=dst_grades)
    return encoded_base


# ── Task 3: classrooms ────────────────────────────────────────────────────────


def extract_classrooms_task(**ctx):
    """Full re-extraction for open years. Aggregate rows — not incremental."""
    _apply_storage_mode(ctx)
    import pandas as pd

    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.incremental.watermark import Watermark

    run_nodash = _get_ds_nodash(ctx)
    wm = Watermark()
    fs = _get_azure_fs()

    logger.info("[classrooms] open_years=%s  run=%s", wm.current_years, run_nodash)

    if fs is None:
        _FEATURES_DIR.mkdir(parents=True, exist_ok=True)

    ext = Neo4jExtractor.from_env()
    try:
        raw_path = ext.extract_classroom_features(segment="EF1")
        logger.info("[classrooms] raw extracted → %s", raw_path)
    finally:
        ext.close()

    written: dict[str, str] = {}
    src_pf = (
        pq.ParquetFile(raw_path, filesystem=fs) if fs else pq.ParquetFile(str(raw_path))
    )

    for year in wm.current_years:
        if fs is not None:
            from src.ml.features._azure_storage import CONTAINER

            dst = f"{CONTAINER}/features/segment=classrooms/year={year}/run={run_nodash}/classrooms.parquet"
        else:
            dst = str(_FEATURES_DIR / f"classrooms_ef1_{year}_{run_nodash}.parquet")

        logger.info("[classrooms] year=%d  writing → %s", year, dst)
        writer: pq.ParquetWriter | None = None
        try:
            for batch in src_pf.iter_batches(batch_size=_ENCODE_BATCH):
                df = batch.to_pandas()
                df = df[df["ano_letivo"] == year]
                if df.empty:
                    continue
                tbl = pa.Table.from_pandas(df, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(
                        dst,
                        tbl.schema,
                        compression="snappy",
                        **({"filesystem": fs} if fs else {}),
                    )
                writer.write_table(tbl)
                del df, tbl
        finally:
            if writer:
                writer.close()

        exists = fs.exists(dst) if fs else Path(dst).exists()
        if exists:
            written[str(year)] = dst
        else:
            logger.warning(
                "[classrooms] year=%d  no rows found — file not written", year
            )

    logger.info("[classrooms] done  written_years=%s", list(written.keys()))
    ctx["ti"].xcom_push(key="classrooms_paths", value=written)
    return written


# ── Task 4: fine-tune ─────────────────────────────────────────────────────────


def fine_tune_task(**ctx):
    """Fine-tune on EF1 delta. Full re-train on Mondays."""
    _apply_storage_mode(ctx)
    import pandas as pd

    ti = ctx["ti"]
    run_date = date.fromisoformat(_get_ds(ctx))
    delta_rows = ti.xcom_pull(key="ef1_delta_rows", task_ids="extract_ef1_delta")
    delta_paths = ti.xcom_pull(key="ef1_delta_paths", task_ids="extract_ef1_delta")
    is_monday = run_date.weekday() == 0
    has_delta = (delta_rows or 0) >= MIN_DELTA_ROWS

    logger.info(
        "[fine_tune] run_date=%s  delta_rows=%d  is_monday=%s  has_delta=%s",
        run_date,
        delta_rows or 0,
        is_monday,
        has_delta,
    )

    if not has_delta and not is_monday:
        logger.info(
            "[fine_tune] skipped — delta=%d rows < %d threshold, not Monday.",
            delta_rows or 0,
            MIN_DELTA_ROWS,
        )
        return {"skipped": True, "reason": "insufficient_delta"}

    if is_monday:
        logger.info(
            "[fine_tune] Monday — full re-train across all years (placeholder)."
        )
        # TODO: implement full re-train
        return {"status": "full_retrain_placeholder"}

    fs = _get_azure_fs()
    logger.info(
        "[fine_tune] loading delta features from %d paths", len(delta_paths or {})
    )
    dfs = [
        batch.to_pandas()
        for path in (delta_paths or {}).values()
        for batch in (
            pq.ParquetFile(path, filesystem=fs) if fs else pq.ParquetFile(path)
        ).iter_batches(batch_size=_ENCODE_BATCH)
    ]
    if not dfs:
        logger.info("[fine_tune] skipped — delta feature files are empty.")
        return {"skipped": True, "reason": "empty_delta"}

    df_delta = pd.concat(dfs, ignore_index=True)
    logger.info(
        "[fine_tune] fine-tuning on %d delta rows (placeholder).", len(df_delta)
    )
    # TODO: xgb.train(..., xgb_model=existing_model)
    return {"delta_rows": len(df_delta), "status": "fine_tune_placeholder"}


# ── DAG ───────────────────────────────────────────────────────────────────────

with DAG(
    dag_id="dag__ml_feature_engineering",
    default_args=_DEFAULT_ARGS,
    schedule="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    params={"storage_mode": "local"},
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

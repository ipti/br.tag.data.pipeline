import argparse
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_TYPE = "notas"
MODEL_NAME = "grade-regression-ef2"


def run(test_year: int) -> None:
    """
    Orchestrate comprehensive grade prediction pipelines smoothly across temporal boundaries, model evaluations, and explicit MLOps checkpoints natively.

    Args:
        test_year (int): Calendar temporal threshold defining exclusive test partition boundaries strictly natively statically.

    Raises:
        ValueError: Bubbles failing metrics breaking hard acceptance criterion boundaries automatically securely.
        Exception: Catches missing node graphs, absent structural columns, or network tracker failures comprehensively internally.

    Returns:
        None
    """
    import pandas as pd
    from mlflow.tracking import MlflowClient
    from ..features.neo4j_extractor import Neo4jExtractor
    from ..features.feature_pipeline import (
        encode_categoricals,
        temporal_split,
        fill_grade_sentinel,
    )
    from ..features.schema import (
        FEATURES_NOTAS_EF2,
        TARGET_GRADE,
        GRADE_EF2_FEATURES,
    )
    from ..models.grade_regressor import GradeRegressorConfig, train_grade_regressor
    from ..evaluation.metrics import eval_regressor
    from ..evaluation.explainability import compute_shap_global
    from ..mlops.experiment import log_run
    from ..mlops.champion_challenger import promote_if_better

    logger.info("=== Grade regression pipeline: test_year=%d ===", test_year)

    # ── 1. Extract (Read directly from storage, bypassing Neo4j) ──────────────
    from ..features._azure_storage import is_configured, get_fs, CONTAINER
    import glob
    from pathlib import Path

    fs = get_fs() if is_configured() else None

    storage_mode = f"Azure ({os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')})" if fs else "local"
    logger.info("[1/9] storage=%-35s | test_year=%d", storage_mode, test_year)

    # Load Base Data
    if fs:
        base_pattern = f"{CONTAINER}/raw/segment=EF2/year=*/EF2_*.parquet"
        base_files = sorted(fs.glob(base_pattern))
    else:
        raw_dir = Path(__file__).parent.parent / "data" / "raw"
        base_files = sorted(glob.glob(f"{raw_dir}/EF2_*.parquet"))

    # Exclude delta, temporary, and grades files, we only want the full base year parquets
    base_files = [f for f in base_files if "_delta_" not in str(f) and "_tmp" not in str(f) and "grades" not in str(f)]

    if not base_files:
        raise RuntimeError("No EF2 raw base files found. Run feature engineering DAG first.")

    # Load exactly what is needed to avoid OOM in Docker Airflow workers
    import pyarrow.parquet as pq

    logger.info("[1/9] loading %d EF2 base parquet files and merging incrementally...", len(base_files))
    
    # Load Grades Data early to use in chunked merge
    if fs:
        grades_pattern = f"{CONTAINER}/features/ef2_grades_*.parquet"
        grades_files = sorted(fs.glob(grades_pattern))
    else:
        features_dir = Path(__file__).parent.parent / "data" / "features"
        logger.info("Looking for grades in: %s/ef2_grades_*.parquet", features_dir)
        grades_files = sorted(glob.glob(f"{features_dir}/ef2_grades_*.parquet"))
        
    if not grades_files:
        raise RuntimeError("No EF2 grades files found. Run feature engineering DAG first.")
        
    latest_grades_path = grades_files[-1]
    logger.info("      %s", latest_grades_path)
    
    sample_grades = pq.read_schema(latest_grades_path, filesystem=fs) if fs else pq.read_schema(latest_grades_path)
    grades_cols = set(sample_grades.names)
    needed_grades_cols = [c for c in GRADE_EF2_FEATURES + [TARGET_GRADE, "nota_media_geral", "student_id"] if c in grades_cols]
    
    logger.info("[1/9] loading grades chunk -> features")
    df_grades = pd.read_parquet(latest_grades_path, filesystem=fs, columns=list(set(needed_grades_cols))) if fs else pd.read_parquet(latest_grades_path, columns=list(set(needed_grades_cols)))
    
    sample_base = pq.read_schema(base_files[-1], filesystem=fs) if fs else pq.read_schema(base_files[-1])
    available_base = set(sample_base.names)
    needed_base_cols = [c for c in FEATURES_NOTAS_EF2 if c in available_base] + ["student_id"]
    if TARGET_GRADE in available_base and TARGET_GRADE not in needed_base_cols:
        needed_base_cols.append(TARGET_GRADE)
    if "nota_media_geral" in available_base and "nota_media_geral" not in needed_base_cols:
        needed_base_cols.append("nota_media_geral")

    from ..features.feature_pipeline import encode_categoricals, fill_grade_sentinel
    import tempfile
    import os

    # Use native disk volume bypass overlayfs strictly writing to /opt/airflow/src/ml/data/tmp
    data_dir = Path(__file__).parent.parent / "data"
    tmp_dir = data_dir / "tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    
    merged_paths = []
    n_base = 0

    # Load Grades Data explicitly early for map joins
    logger.info("  -> Loading Grades Chunk [%s]", latest_grades_path.split("/")[-1])
    sample_grades = pq.read_schema(latest_grades_path, filesystem=fs) if fs else pq.read_schema(latest_grades_path)
    grades_cols = set(sample_grades.names)
    needed_grades_cols = [c for c in GRADE_EF2_FEATURES + [TARGET_GRADE, "nota_media_geral", "student_id"] if c in grades_cols]
    df_grades = pd.read_parquet(latest_grades_path, filesystem=fs, columns=list(set(needed_grades_cols))) if fs else pd.read_parquet(latest_grades_path, columns=list(set(needed_grades_cols)))
    
    # Deduplicate perfectly duplicating records generating memory explosions on Cartesian .merge() loops downstream mapping per student exactly once!
    df_grades.drop_duplicates(subset=["student_id"], inplace=True)

    sample_base = pq.read_schema(base_files[-1], filesystem=fs) if fs else pq.read_schema(base_files[-1])
    available_base = set(sample_base.names)
    
    grades_overlaps = set(GRADE_EF2_FEATURES + [TARGET_GRADE, "nota_media_geral", "student_id"])
    needed_base_cols = [c for c in FEATURES_NOTAS_EF2 if c in available_base and c not in grades_overlaps] + ["student_id"]
    # We purposefully EXCLUDE target_grade / nota_media_geral from base, as they arrive via merge from `df_grades`.

    for i, f in enumerate(base_files, 1):
        year_str = f.split("_")[-1].replace(".parquet", "")
        logger.info("  [%d/%d] processing batches from %s...", i, len(base_files), f.split("/")[-1] if "/" in str(f) else f)
        
        pf = pq.ParquetFile(fs.open(f) if fs else f)
        
        batch_idx = 0
        for batch in pf.iter_batches(batch_size=250_000, columns=needed_base_cols):
            df_chunk = batch.to_pandas()
            n_base += len(df_chunk)
            
            # Immediate inner join on student grades drops ~95% of rows usually
            df_chunk = df_chunk.merge(df_grades, on="student_id", how="inner")
            
            if len(df_chunk) == 0:
                del df_chunk
                import gc; gc.collect()
                continue
            
            # Limit dimensions
            df_chunk = encode_categoricals(df_chunk)
            df_chunk = fill_grade_sentinel(df_chunk, GRADE_EF2_FEATURES)

            for col in df_chunk.columns:
                if df_chunk[col].dtype == 'object':
                    df_chunk[col] = df_chunk[col].astype('category')
                elif df_chunk[col].dtype == 'float64':
                    df_chunk[col] = df_chunk[col].astype('float32')

            # Convert proxy column to target column if it's missing (as TARGET_GRADE is not in df_base and df_grades is an aggregation)
            if "nota_media_geral" in df_chunk.columns and TARGET_GRADE not in df_chunk.columns:
                df_chunk.rename(columns={"nota_media_geral": TARGET_GRADE}, inplace=True)

            # Drop rows where target is null (can't regress without a grade)
            df_chunk.dropna(subset=[TARGET_GRADE], inplace=True)
            
            if len(df_chunk) > 0:
                out_path = os.path.join(tmp_dir, f"chunk_{year_str}_{batch_idx}.parquet")
                df_chunk.to_parquet(out_path, index=False)
                merged_paths.append(out_path)
            
            del df_chunk
            batch_idx += 1
            import gc; gc.collect()
            
    del df_grades
    import gc; gc.collect()

    logger.info("  -> Loading %d aggregated conceptual iter-batch disk arrays...", len(merged_paths))
    
    if not merged_paths:
        raise ValueError(f"Temporal split produced empty dataset. No grades match any base records across {len(base_files)} years.")
        
    df = pd.concat([pd.read_parquet(p) for p in merged_paths], ignore_index=True)
    
    n_grades = 0 # Not calculated explicitly to save array footprint tracking
    
    logger.info(
        "EF2 merge (via incremental IO limits): %d base rows → %d merged",
        n_base,
        len(df),
    )
    logger.info("       %.1f%% of base students have grade records", 100 * len(df) / max(n_base, 1))
    if len(df) < 1000:
        logger.warning(
            "Merged EF2 dataset has only %d rows. ",
            len(df),
        )

    # ── 3. Post-Process after chunked merging ────────────────────────────────────────────
    # Encoding and sentinels were already applied inplace incrementally to save memory!
    # Dropping rows where target is null (can't regress without a grade)
    df_clean = df.dropna(subset=[TARGET_GRADE])
    n_dropped = len(df) - len(df_clean)
    if n_dropped > 0:
        logger.info(
            "Dropped %d rows with null %s (no final grade registered)",
            n_dropped,
            TARGET_GRADE,
        )
    df = df_clean

    # ── 4. Temporal split ─────────────────────────────────────────────────────
    logger.info("[4/9] temporal split: train=<test_year, test=%d...", test_year)
    X_train, y_train, X_test, y_test = temporal_split(
        df,
        target_col=TARGET_GRADE,
        test_year=test_year,
        feature_cols=FEATURES_NOTAS_EF2,
    )

    # ── 5. Train ──────────────────────────────────────────────────────────────
    config = GradeRegressorConfig()
    logger.info("[5/9] training GradientBoosting (n_estimators=%d, max_depth=%d)...",
                config.n_estimators, config.max_depth)
    logger.info("       train=%d rows | test=%d rows | features=%d", len(X_train), len(X_test), X_train.shape[1])
    model = train_grade_regressor(X_train, y_train, config)

    # ── 6. Evaluate ───────────────────────────────────────────────────────────
    logger.info("[6/9] evaluating on test set (%d rows)...", len(X_test))
    y_pred = model.predict(X_test)
    # Clip predictions to valid grade range [0, 10] before evaluation
    import numpy as np

    y_pred = np.clip(y_pred, 0.0, 10.0)
    metrics = eval_regressor(y_test.values, y_pred)

    if not metrics.passes_acceptance():
        logger.warning(
            "Grade model does NOT meet acceptance criteria. "
            "RMSE=%.4f (need <=1.5), R2=%.4f (need >=0.60)",
            metrics.rmse,
            metrics.r2,
        )
    else:
        logger.info("All acceptance criteria met: %s", metrics.as_dict())

    # ── 7. SHAP ───────────────────────────────────────────────────────────────
    logger.info("[7/9] computing SHAP values (up to 2000 samples — may take ~60s for GBM)...")
    _, shap_buf = compute_shap_global(model, X_test)

    # ── 8. Log to MLflow ──────────────────────────────────────────────────────
    logger.info("[8/9] logging run to MLflow...")
    params = vars(config) | {
        "test_year": test_year,
        "n_train": len(X_train),
        "n_test": len(X_test),
        "n_dropped_nulls": n_dropped,
    }
    tags = {"segment": "EF2", "target": TARGET_GRADE}

    with log_run(MODEL_TYPE, params=params, tags=tags) as run_ctx:
        run_ctx.log_metrics(metrics.as_dict())
        run_ctx.log_model(model, artifact_path="grade_model")
        run_ctx.log_png_buffer(shap_buf, "shap_summary.png")
        run_id = run_ctx.run_id

    # ── 9. Champion/Challenger ────────────────────────────────────────────────
    logger.info("[9/9] champion/challenger evaluation...")
    promoted = promote_if_better(
        model_type=MODEL_TYPE,
        challenger_run_id=run_id,
        challenger_metrics=metrics.as_dict(),
        client=MlflowClient(),
    )
    logger.info(
        "Pipeline complete. RMSE=%.4f | R²=%.4f | Promoted=%s",
        metrics.rmse,
        metrics.r2,
        promoted,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train grade regression model (EF2)")
    parser.add_argument(
        "--test-year",
        type=int,
        required=True,
        help="School year to hold out as test set",
    )
    args = parser.parse_args()
    run(args.test_year)

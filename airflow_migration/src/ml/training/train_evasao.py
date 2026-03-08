import argparse
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_TYPE = "evasao"
MODEL_NAME = "dropout-evasao-ef1"


def run(test_year: int) -> None:
    """
    Execute the complete dropout training orchestrator dynamically handling features, splits, training, evaluation, and registry promotion atomically.

    Args:
        test_year (int): Specific temporal boundaries holding exact school calendar years cleanly aside exclusively for testing.

    Raises:
        ValueError: Explicitly bubbles any runtime validations failing over missing model thresholds or broken metrics.
        Exception: Wraps pipeline failure events securely across database, training, or tracking connections deeply.

    Returns:
        None
    """
    from pathlib import Path
    import pandas as pd
    from mlflow.tracking import MlflowClient
    from ..features.neo4j_extractor import Neo4jExtractor
    from ..features.feature_pipeline import (
        encode_categoricals,
        temporal_split,
        fill_grade_sentinel,
    )
    from ..features.schema import (
        FEATURES_EVASAO_EF1_ENRICHED,
        TARGET_DROPOUT,
        ID_COLS,
        GRADE_EF1_FEATURES,
    )
    from ..models.dropout_classifier import (
        DropoutConfig,
        train_dropout,
        predict_dropout,
    )
    from ..evaluation.metrics import eval_classifier
    from ..evaluation.explainability import compute_shap_global
    from ..mlops.experiment import log_run
    from ..mlops.champion_challenger import promote_if_better

    # ── 1. Extract ────────────────────────────────────────────────────────────
    logger.info("=== Dropout training pipeline: test_year=%d ===", test_year)
    from ..features._azure_storage import is_configured, get_fs, CONTAINER
    import glob

    fs = get_fs() if is_configured() else None

    storage_mode = f"Azure ({os.environ.get('AZURE_STORAGE_ACCOUNT_NAME')})" if fs else "local"
    logger.info("[1/9] storage=%-35s | test_year=%d", storage_mode, test_year)

    if fs:
        pattern = f"{CONTAINER}/raw/segment=EF1/year=*/EF1_*.parquet"
        files = sorted(fs.glob(pattern))
    else:
        raw_dir = Path(__file__).parent.parent / "data" / "raw"
        files = sorted(glob.glob(f"{raw_dir}/EF1_*.parquet"))

    # Exclude delta and temporary files, we only want the full base year parquets
    files = [f for f in files if "_delta_" not in str(f) and "_tmp" not in str(f)]

    if not files:
        raise RuntimeError("No EF1 raw base files found. Run feature engineering DAG first.")

    import pyarrow.parquet as pq
    import tempfile
    
    logger.info("[1/9] loading %d EF1 base parquet files (chunked streaming)...", len(files))
    
    data_dir = Path(__file__).parent.parent / "data"
    tmp_dir = data_dir / "tmp"
    os.makedirs(tmp_dir, exist_ok=True)
    
    sample_base = pq.read_schema(files[-1], filesystem=fs) if fs else pq.read_schema(files[-1])
    available_base = set(sample_base.names)
    needed_cols = [c for c in FEATURES_EVASAO_EF1_ENRICHED if c in available_base] + ["student_id"]
    if TARGET_DROPOUT in available_base and TARGET_DROPOUT not in needed_cols:
        needed_cols.append(TARGET_DROPOUT)
        
    cr_cols = [c for c in FEATURES_EVASAO_EF1_ENRICHED if c.startswith("cr_")]
    missing_cr = [c for c in cr_cols if c not in available_base]
    if missing_cr:
        logger.warning(
            "[enriched] %d classroom-context columns missing from EF1 data "
            "(will be treated as null by fill_grade_sentinel): %s",
            len(missing_cr),
            missing_cr,
        )

    merged_paths = []
    n_base = 0

    for i, f in enumerate(files, 1):
        year_str = f.split("_")[-1].replace(".parquet", "")
        logger.info("  [%d/%d] processing batches from %s...", i, len(files), f.split("/")[-1] if "/" in str(f) else f)
        
        pf = pq.ParquetFile(fs.open(f) if fs else f)
        batch_idx = 0
        for batch in pf.iter_batches(batch_size=300_000, columns=needed_cols):
            df_chunk = batch.to_pandas()
            n_base += len(df_chunk)
            
            # ── 2. Encode ─────────────────────────────────────────────────────────────
            df_chunk = encode_categoricals(df_chunk)
            df_chunk = fill_grade_sentinel(df_chunk, GRADE_EF1_FEATURES)  # null grades → -1
            
            for col in df_chunk.columns:
                if df_chunk[col].dtype == 'object':
                    df_chunk[col] = df_chunk[col].astype('category')
                elif df_chunk[col].dtype == 'float64':
                    df_chunk[col] = df_chunk[col].astype('float32')
            
            # Retain only instances valid for classification
            df_chunk.dropna(subset=[TARGET_DROPOUT], inplace=True)
            
            if len(df_chunk) > 0:
                out_path = os.path.join(tmp_dir, f"evasao_chunk_{year_str}_{batch_idx}.parquet")
                df_chunk.to_parquet(out_path, index=False)
                merged_paths.append(out_path)
            
            del df_chunk
            batch_idx += 1
            import gc; gc.collect()

    logger.info("  -> Loading %d aggregated categorical disk arrays...", len(merged_paths))
    if not merged_paths:
        raise ValueError(f"Feature split produced empty dataset across {len(files)} files.")
        
    df = pd.concat([pd.read_parquet(p) for p in merged_paths], ignore_index=True)
    logger.info("[2/9] formatting loaded → %d rows × %d cols", len(df), len(df.columns))

    # Prevent Docker OOM (Exit 137) during XGBoost mapping by downsampling majority negative class
    df_pos = df[df[TARGET_DROPOUT] == 1]
    df_neg = df[df[TARGET_DROPOUT] == 0]
    if len(df_neg) > 1000000:
        df_neg = df_neg.sample(n=1000000, random_state=42)
        df = pd.concat([df_pos, df_neg], ignore_index=True).sample(frac=1, random_state=42)
        logger.info("Downsampled negatives to prevent OOM → %d total rows", len(df))
    del df_pos, df_neg
    import gc; gc.collect()

    # ── 3. Temporal split ─────────────────────────────────────────────────────
    logger.info("[3/9] temporal split: train=<test_year, test=%d...", test_year)
    X_train, y_train, X_test, y_test = temporal_split(
        df,
        target_col=TARGET_DROPOUT,
        test_year=test_year,
        feature_cols=FEATURES_EVASAO_EF1_ENRICHED,
    )

    # ── 4. Validation split from train (last 15% of train rows) ───────────────
    split_idx = int(len(X_train) * 0.85)
    X_tr, X_val = X_train.iloc[:split_idx], X_train.iloc[split_idx:]
    y_tr, y_val = y_train.iloc[:split_idx], y_train.iloc[split_idx:]
    logger.info("[4/9] validation split: 85%% train / 15%% val")
    logger.info("       train=%d rows | val=%d rows | test=%d rows", len(X_tr), len(X_val), len(X_test))

    # ── 5. Train ──────────────────────────────────────────────────────────────
    config = DropoutConfig()
    logger.info("[5/9] training XGBoost (n_estimators=%d, max_depth=%d, early_stop=%d)...",
                config.n_estimators, config.max_depth, config.early_stopping_rounds)
    model = train_dropout(X_tr, y_tr, X_val, y_val, config)

    # ── 6. Evaluate ───────────────────────────────────────────────────────────
    logger.info("[6/9] evaluating on test set (%d rows)...", len(X_test))
    preds = predict_dropout(model, X_test)
    metrics = eval_classifier(y_test.values, preds["evasao_prob"])

    if not metrics.passes_acceptance():
        logger.warning(
            "Model does NOT meet acceptance criteria. "
            "AUROC=%.4f (need ≥0.82), Recall=%.4f (need ≥0.75), F1=%.4f (need ≥0.70)",
            metrics.auroc,
            metrics.recall,
            metrics.f1,
        )
    else:
        logger.info("All acceptance criteria met: %s", metrics.as_dict())

    # ── 7. SHAP ───────────────────────────────────────────────────────────────
    logger.info("[7/9] computing SHAP values (up to 2000 samples — may take ~30s)...")
    _, shap_buf = compute_shap_global(model, X_test)

    # ── 8. Log to MLflow ──────────────────────────────────────────────────────
    logger.info("[8/9] logging run to MLflow...")
    params = vars(config) | {
        "test_year": test_year,
        "n_train": len(X_train),
        "n_test": len(X_test),
    }
    tags = {"segment": "EF1", "target": TARGET_DROPOUT}

    with log_run(MODEL_TYPE, params=params, tags=tags) as run_ctx:
        run_ctx.log_metrics(metrics.as_dict())
        run_ctx.log_model(model, artifact_path="dropout_model")
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
    logger.info("Pipeline complete. AUROC=%.4f | Promoted=%s", metrics.auroc, promoted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train dropout prediction model")
    parser.add_argument(
        "--test-year",
        type=int,
        required=True,
        help="School year to hold out as test set",
    )
    args = parser.parse_args()
    run(args.test_year)

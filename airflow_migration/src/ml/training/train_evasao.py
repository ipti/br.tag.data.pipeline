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
    import pandas as pd
    from mlflow.tracking import MlflowClient
    from ..features.neo4j_extractor import Neo4jExtractor
    from ..features.feature_pipeline import (
        encode_categoricals,
        temporal_split,
        fill_grade_sentinel,
    )
    from ..features.schema import (
        FEATURES_EVASAO_EF1,
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
    extractor = Neo4jExtractor.from_env()
    df_raw = extractor.extract_ef1()  # all years
    extractor.close()

    # ── 2. Encode ─────────────────────────────────────────────────────────────
    df = encode_categoricals(df_raw)
    df = fill_grade_sentinel(df, GRADE_EF1_FEATURES)  # null grades → -1

    # ── 3. Temporal split ─────────────────────────────────────────────────────
    X_train, y_train, X_test, y_test = temporal_split(
        df,
        target_col=TARGET_DROPOUT,
        test_year=test_year,
        feature_cols=FEATURES_EVASAO_EF1,
    )

    # ── 4. Validation split from train (last 15% of train rows) ───────────────
    split_idx = int(len(X_train) * 0.85)
    X_tr, X_val = X_train.iloc[:split_idx], X_train.iloc[split_idx:]
    y_tr, y_val = y_train.iloc[:split_idx], y_train.iloc[split_idx:]

    # ── 5. Train ──────────────────────────────────────────────────────────────
    config = DropoutConfig()
    model = train_dropout(X_tr, y_tr, X_val, y_val, config)

    # ── 6. Evaluate ───────────────────────────────────────────────────────────
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
    _, shap_buf = compute_shap_global(model, X_test)

    # ── 8. Log to MLflow ──────────────────────────────────────────────────────
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

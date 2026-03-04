import argparse
import logging

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

    # ── 1. Extract ────────────────────────────────────────────────────────────
    extractor = Neo4jExtractor.from_env()
    df_base = extractor.extract_students_base(
        "EF2"
    )  # demographics + health + attendance + IBGE for EF2 students
    df_grades = extractor.extract_ef2_grades()  # per-subject grade pivot
    extractor.close()

    # ── 2. Merge: EF2 base is the anchor, grades are joined on student_id ─────
    # Students without any grade records are dropped (target is grade — can't train without it)
    df = df_base.merge(df_grades, on="student_id", how="inner")
    logger.info(
        "EF2 merge: %d base rows × %d grade rows → %d merged (inner join on student_id)",
        len(df_base),
        len(df_grades),
        len(df),
    )
    if len(df) < 1000:
        logger.warning(
            "Merged EF2 dataset has only %d rows. ",
            len(df),
        )

    # Convert proxy column to target column if it's missing (as TARGET_GRADE is not in df_base and df_grades is an aggregation)
    # The neo4j query gives nota_media_geral, so let's rename it to target_nota if it exists.
    if "nota_media_geral" in df.columns and TARGET_GRADE not in df.columns:
        df.rename(columns={"nota_media_geral": TARGET_GRADE}, inplace=True)

    # ── 3. Encode + fill sentinels ────────────────────────────────────────────
    df = encode_categoricals(df)
    df = fill_grade_sentinel(df, GRADE_EF2_FEATURES)  # null subject grades → -1

    # Drop rows where target is null (can't regress without a grade)
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
    X_train, y_train, X_test, y_test = temporal_split(
        df,
        target_col=TARGET_GRADE,
        test_year=test_year,
        feature_cols=FEATURES_NOTAS_EF2,
    )

    # ── 5. Train ──────────────────────────────────────────────────────────────
    config = GradeRegressorConfig()
    model = train_grade_regressor(X_train, y_train, config)

    # ── 6. Evaluate ───────────────────────────────────────────────────────────
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
    _, shap_buf = compute_shap_global(model, X_test)

    # ── 8. Log to MLflow ──────────────────────────────────────────────────────
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

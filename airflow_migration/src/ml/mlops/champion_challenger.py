# src/ml/mlops/champion_challenger.py
"""
Champion/Challenger pattern for automatic model promotion.

Supports both classification models (primary metric: auroc, higher is better)
and regression models (primary metric: r2, higher is better).

The model_type parameter drives which metric is used for comparison and which
artifact path is used for registration. Adding a new model type requires only
adding an entry to _MODEL_CONFIG.

Threshold prevents churn from small fluctuations between training runs.
All promotion decisions are logged with full metric context for audit.
"""
import logging
import mlflow
from mlflow.tracking import MlflowClient
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ModelConfig:
    """Internal config per model type."""
    registry_name:   str    # registered model name in MLflow
    artifact_path:   str    # artifact_path used in log_model()
    primary_metric:  str    # metric key to compare champion vs challenger
    higher_is_better: bool  # True = higher value wins; False = lower value wins
    threshold:       float  # minimum absolute improvement to justify promotion


# ── Per-model-type configuration ─────────────────────────────────────────────
# Add new model types here only — no changes needed elsewhere.
_MODEL_CONFIG: dict[str, _ModelConfig] = {
    "evasao": _ModelConfig(
        registry_name    = "dropout-evasao-ef1",
        artifact_path    = "dropout_model",
        primary_metric   = "auroc",
        higher_is_better = True,
        threshold        = 0.01,   # min AUROC improvement
    ),
    "notas": _ModelConfig(
        registry_name    = "grade-regression-ef2",
        artifact_path    = "grade_model",
        primary_metric   = "r2",
        higher_is_better = True,   # R² higher = better fit
        threshold        = 0.02,   # min R² improvement (regression runs are noisier)
    ),
    "clustering": _ModelConfig(
        registry_name    = "student-clustering",
        artifact_path    = "clustering_model",
        primary_metric   = "silhouette",
        higher_is_better = True,
        threshold        = 0.03,
    ),
}


def get_champion_metrics(model_name: str, client: MlflowClient) -> dict | None:
    """
    Retrieve metrics of the current Production model from MLflow Registry.

    Args:
        model_name: Registered model name (e.g., 'dropout-evasao-ef1').
        client: MlflowClient instance.

    Returns:
        Dict of metric_name → float from the Production model's MLflow run.
        None if no Production model exists yet (first training run).
    """
    try:
        versions = client.get_latest_versions(model_name, stages=["Production"])
        if not versions:
            logger.info("No Production model found for '%s' — first run.", model_name)
            return None
        run = client.get_run(versions[0].run_id)
        return dict(run.data.metrics)
    except Exception as exc:
        logger.warning("Could not retrieve champion metrics for '%s': %s", model_name, exc)
        return None


def _is_better(
    challenger_val: float,
    champion_val: float,
    higher_is_better: bool,
    threshold: float,
) -> bool:
    """
    Return True if challenger beats champion by more than threshold.

    Args:
        challenger_val: Challenger model's primary metric value.
        champion_val: Champion model's primary metric value.
        higher_is_better: If True, challenger must be higher; if False, lower.
        threshold: Minimum absolute difference required to promote.

    Returns:
        True if challenger should replace champion.
    """
    delta = challenger_val - champion_val
    if not higher_is_better:
        delta = -delta   # flip sign so positive delta always means improvement
    return delta > threshold


def promote_if_better(
    model_type: str,
    challenger_run_id: str,
    challenger_metrics: dict[str, float],
    client: MlflowClient | None = None,
) -> bool:
    """
    Promote challenger model to Production if primary metric improvement exceeds threshold.

    Works for both classification (auroc) and regression (r2) models.
    Uses _MODEL_CONFIG[model_type] to determine which metric to compare.

    Args:
        model_type: Key in _MODEL_CONFIG — 'evasao', 'notas', or 'clustering'.
        challenger_run_id: MLflow run ID of the challenger model.
        challenger_metrics: Metrics dict from the challenger run.
                            Must include the primary_metric defined in _MODEL_CONFIG.
        client: MlflowClient — if None, creates a new one.

    Returns:
        True if challenger was promoted to Production, False if champion retained.

    Raises:
        KeyError: if model_type is not in _MODEL_CONFIG.
        KeyError: if primary_metric is missing from challenger_metrics.
    """
    if model_type not in _MODEL_CONFIG:
        raise KeyError(
            f"Unknown model_type='{model_type}'. "
            f"Known types: {list(_MODEL_CONFIG.keys())}"
        )

    cfg    = _MODEL_CONFIG[model_type]
    client = client or MlflowClient()

    # Validate challenger has the expected metric
    if cfg.primary_metric not in challenger_metrics:
        raise KeyError(
            f"Challenger metrics missing '{cfg.primary_metric}' for model_type='{model_type}'. "
            f"Got: {list(challenger_metrics.keys())}"
        )

    challenger_val = challenger_metrics[cfg.primary_metric]
    champion_metrics = get_champion_metrics(cfg.registry_name, client)

    if champion_metrics is None:
        logger.info(
            "No champion found for '%s' — promoting first model. "
            "%s=%.4f",
            cfg.registry_name, cfg.primary_metric, challenger_val,
        )
    else:
        champion_val = champion_metrics.get(cfg.primary_metric, 0.0)
        delta = challenger_val - champion_val
        logger.info(
            "Champion %s=%.4f | Challenger %s=%.4f | Delta=%.4f | "
            "Threshold=%.4f | higher_is_better=%s",
            cfg.primary_metric, champion_val,
            cfg.primary_metric, challenger_val,
            delta, cfg.threshold, cfg.higher_is_better,
        )

        # Log secondary metrics for context (RMSE for notas, recall for evasao)
        for k, v in challenger_metrics.items():
            if k != cfg.primary_metric:
                logger.info("  Secondary metric: %s=%.4f", k, v)

        if not _is_better(challenger_val, champion_val, cfg.higher_is_better, cfg.threshold):
            logger.info(
                "Keeping champion — challenger improvement %.4f does not exceed threshold %.4f.",
                abs(delta), cfg.threshold,
            )
            return False

    # Register and promote to Production
    model_uri = f"runs:/{challenger_run_id}/{cfg.artifact_path}"
    mlflow.register_model(model_uri, cfg.registry_name)

    latest = client.get_latest_versions(cfg.registry_name, stages=["None"])
    client.transition_model_version_stage(
        name=cfg.registry_name,
        version=latest[0].version,
        stage="Production",
        archive_existing_versions=True,
    )
    logger.info(
        "Challenger promoted to Production: '%s' version=%s | %s=%.4f",
        cfg.registry_name, latest[0].version,
        cfg.primary_metric, challenger_val,
    )
    return True

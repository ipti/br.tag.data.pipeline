import logging
import mlflow
from mlflow.tracking import MlflowClient
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ModelConfig:
    """Internal config per model type."""

    registry_name: str  # registered model name in MLflow
    artifact_path: str  # artifact_path used in log_model()
    primary_metric: str  # metric key to compare champion vs challenger
    higher_is_better: bool  # True = higher value wins; False = lower value wins
    threshold: float  # minimum absolute improvement to justify promotion


# ── Per-model-type configuration ─────────────────────────────────────────────
# Add new model types here only — no changes needed elsewhere.
_MODEL_CONFIG: dict[str, _ModelConfig] = {
    "evasao": _ModelConfig(
        registry_name="dropout-evasao-ef1",
        artifact_path="dropout_model",
        primary_metric="auroc",
        higher_is_better=True,
        threshold=0.01,  # min AUROC improvement
    ),
    "notas": _ModelConfig(
        registry_name="grade-regression-ef2",
        artifact_path="grade_model",
        primary_metric="r2",
        higher_is_better=True,  # R² higher = better fit
        threshold=0.02,  # min R² improvement (regression runs are noisier)
    ),
    "clustering": _ModelConfig(
        registry_name="student-clustering",
        artifact_path="clustering_model",
        primary_metric="silhouette",
        higher_is_better=True,
        threshold=0.03,
    ),
}


def get_champion_metrics(model_name: str, client: MlflowClient) -> dict | None:
    """
    Retrieve metrics of the current Production model directly from the MLflow Registry.

    Args:
        model_name (str): Registered model naming identifier (e.g., 'dropout-evasao-ef1').
        client (MlflowClient): Active MLflow tracking client instance binding connection states.

    Raises:
        Exception: If fetching endpoints timeouts or unrecoverable MLflow parsing failures trigger.

    Returns:
        dict | None: Dictionary relating strings to metric float values, or None if the Production tier is explicitly empty.
    """
    try:
        try:
            champ_mv = client.get_model_version_by_alias(model_name, "champion")
        except mlflow.exceptions.RestException:
            logger.info(
                "No champion model alias found for '%s' — first run.", model_name
            )
            return None
        run = client.get_run(champ_mv.run_id)
        return dict(run.data.metrics)
    except Exception as exc:
        logger.warning(
            "Could not retrieve champion metrics for '%s': %s", model_name, exc
        )
        return None


def _is_better(
    challenger_val: float,
    champion_val: float,
    higher_is_better: bool,
    threshold: float,
) -> bool:
    """
    Evaluate structural bounds verifying if challenger explicitly outperforms current champion footprints beyond minimum thresholds.

    Args:
        challenger_val (float): Challenger model's recorded primary metric evaluation value.
        champion_val (float): Current champion model's primary metric validation value.
        higher_is_better (bool): Directional indicator flag dictating whether positive scaling signals improvement.
        threshold (float): Minimum positive baseline deviation establishing absolute promotion thresholds.

    Raises:
        Exception: Rare float math boundary violations implicitly triggered by external numpy types causing sign issues.

    Returns:
        bool: True flag precisely when challenger explicitly outpaces threshold improvements cleanly over champion.
    """
    delta = challenger_val - champion_val
    if not higher_is_better:
        delta = -delta  # flip sign so positive delta always means improvement
    return delta > threshold


def promote_if_better(
    model_type: str,
    challenger_run_id: str,
    challenger_metrics: dict[str, float],
    client: MlflowClient | None = None,
) -> bool:
    """
    Evaluate and seamlessly promote challenger model structures transitioning to Production assuming configured thresholds trigger appropriately.

    Abstract logic dynamically works across separate modeling methodologies simply utilizing _MODEL_CONFIG logic boundaries.

    Args:
        model_type (str): Key pointing towards predefined settings in _MODEL_CONFIG mappings (e.g. 'evasao').
        challenger_run_id (str): MLflow string ID linking precisely backwards toward challenger run locations.
        challenger_metrics (dict[str, float]): Validation metric dictionary containing tracked parameters matching specific _MODEL_CONFIG primary paths.
        client (MlflowClient | None, optional): Tracked MLflow Client endpoint parameter connection string. Defaults to creating fresh connections if None.

    Raises:
        KeyError: Execution breaks if model_type parameter is fundamentally unassociated with configured definitions.
        KeyError: Execution breaks precisely when targeted primary_metrics are fully absent across defined challenger metric dictionaries.
        Exception: Rare promotion state transitions failing during MLflow registry binding calls explicitly.

    Returns:
        bool: Boolean flag triggering True precisely when challenger safely inherits Production stage placement cleanly.
    """
    if model_type not in _MODEL_CONFIG:
        raise KeyError(
            f"Unknown model_type='{model_type}'. "
            f"Known types: {list(_MODEL_CONFIG.keys())}"
        )

    cfg = _MODEL_CONFIG[model_type]
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
            "No champion found for '%s' — promoting first model. " "%s=%.4f",
            cfg.registry_name,
            cfg.primary_metric,
            challenger_val,
        )
    else:
        champion_val = champion_metrics.get(cfg.primary_metric, 0.0)
        delta = challenger_val - champion_val
        logger.info(
            "Champion %s=%.4f | Challenger %s=%.4f | Delta=%.4f | "
            "Threshold=%.4f | higher_is_better=%s",
            cfg.primary_metric,
            champion_val,
            cfg.primary_metric,
            challenger_val,
            delta,
            cfg.threshold,
            cfg.higher_is_better,
        )

        # Log secondary metrics for context (RMSE for notas, recall for evasao)
        for k, v in challenger_metrics.items():
            if k != cfg.primary_metric:
                logger.info("  Secondary metric: %s=%.4f", k, v)

        if not _is_better(
            challenger_val, champion_val, cfg.higher_is_better, cfg.threshold
        ):
            logger.info(
                "Keeping champion — challenger improvement %.4f does not exceed threshold %.4f.",
                abs(delta),
                cfg.threshold,
            )
            return False

    # Register and promote to champion alias
    model_uri = f"runs:/{challenger_run_id}/{cfg.artifact_path}"
    mv = mlflow.register_model(model_uri, cfg.registry_name)

    client.set_registered_model_alias(
        name=cfg.registry_name,
        alias="champion",
        version=mv.version,
    )
    logger.info(
        "Challenger promoted to Production: '%s' version=%s | %s=%.4f",
        cfg.registry_name,
        mv.version,
        cfg.primary_metric,
        challenger_val,
    )
    return True

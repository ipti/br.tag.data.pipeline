# src/ml/mlops/experiment.py
"""
Thin MLflow context manager for experiment tracking.

The model training functions (dropout_classifier.py, grade_regressor.py) are
completely unaware of MLflow. This module wraps them in an mlflow.start_run()
context, providing a clean RunContext object to the entrypoints.

Experiment names map to model types. Changing the experiment name here changes
it everywhere — no scattered mlflow.set_experiment() calls in other files.

Usage in training entrypoint:
    with log_run("evasao", params=vars(config), tags={"segment": "EF1"}) as run:
        model = train_dropout(X_tr, y_tr, X_val, y_val, config)
        metrics = eval_classifier(y_test.values, predict_dropout(model, X_test)["evasao_prob"])
        run.log_metrics(metrics.as_dict())
        run.log_model(model, artifact_path="dropout_model")
        run_id = run.run_id
"""
import io
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
import mlflow
import mlflow.sklearn
import mlflow.xgboost

logger = logging.getLogger(__name__)

EXPERIMENT_NAMES = {
    "evasao":     "school-dropout-prediction",
    "notas":      "grade-regression-ef2",
    "clustering": "student-clustering",
}


@dataclass
class RunContext:
    """
    Handle to an active MLflow run.

    Wraps mlflow logging calls so that entrypoints don't import mlflow directly.
    All methods delegate to the active run context set by mlflow.start_run().
    """
    run_id: str

    def log_metrics(self, metrics: dict[str, float]) -> None:
        """Log a dict of metric name → float value to the active run."""
        mlflow.log_metrics(metrics)
        logger.info("Metrics logged: %s", {k: round(v, 4) for k, v in metrics.items()})

    def log_params(self, params: dict) -> None:
        """Log hyperparameters to the active run."""
        mlflow.log_params({k: str(v) for k, v in params.items()})

    def log_model(self, model, artifact_path: str) -> None:
        """
        Log a trained model to the active run.

        Detects XGBoost vs sklearn automatically by checking for get_booster().
        """
        if hasattr(model, "get_booster"):
            mlflow.xgboost.log_model(model, artifact_path)
        else:
            mlflow.sklearn.log_model(model, artifact_path)
        logger.info("Model logged to artifact_path='%s'", artifact_path)

    def log_png_buffer(self, buf: io.BytesIO, filename: str) -> None:
        """Log an in-memory PNG buffer as an MLflow artifact (e.g., SHAP plot)."""
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as f:
            f.write(buf.read())
            tmp_path = f.name
        mlflow.log_artifact(tmp_path, artifact_path="plots")
        os.unlink(tmp_path)

    def log_dataframe(self, df, filename: str) -> None:
        """Log a DataFrame as a CSV artifact (e.g., feature importance, drift report summary)."""
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False, mode="w") as f:
            df.to_csv(f, index=False)
            tmp_path = f.name
        mlflow.log_artifact(tmp_path, artifact_path="data")
        os.unlink(tmp_path)


@contextmanager
def log_run(
    model_type: str,
    params: dict,
    tags: dict | None = None,
):
    """
    Context manager for an MLflow run.

    Sets the experiment, starts a run, logs params, yields RunContext,
    then closes the run (including on exception).

    Args:
        model_type: Key in EXPERIMENT_NAMES dict ('evasao', 'notas', 'clustering').
        params: Hyperparameter dict — logged at run start.
        tags: Optional dict of string tags (e.g., {'segment': 'EF1'}).

    Yields:
        RunContext object with logging methods.
    """
    experiment_name = EXPERIMENT_NAMES.get(model_type, model_type)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_URI", "http://localhost:5001"))
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(tags=tags or {}) as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        run_id = run.info.run_id
        logger.info("MLflow run started: experiment='%s' run_id=%s", experiment_name, run_id)
        yield RunContext(run_id=run_id)

    logger.info("MLflow run completed: run_id=%s", run_id)

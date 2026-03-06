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
    "evasao": "school-dropout-prediction",
    "notas": "grade-regression-ef2",
    "clustering": "student-clustering",
}


@dataclass
class RunContext:
    """
    Handle holding contextual bounds to an active MLflow run block.

    Abstracts MLflow logging execution endpoints so explicit entrypoints cleanly lack direct tight coupling with explicit API dependencies natively.
    """

    run_id: str

    def log_metrics(self, metrics: dict[str, float]) -> None:
        """
        Log multiple evaluation metrics neatly pointing dictionary structures natively into MLflow spaces.

        Args:
            metrics (dict[str, float]): Dictionary explicitly containing exact key names bounding against generated floating validation scores.

        Raises:
            Exception: If generic API limits block sending tracked numbers.

        Returns:
            None
        """
        mlflow.log_metrics(metrics)
        logger.info("Metrics logged: %s", {k: round(v, 4) for k, v in metrics.items()})

    def log_params(self, params: dict) -> None:
        """
        Log designated execution hyperparameters dynamically into active tracking windows cleanly.

        Args:
            params (dict): Key-value pair objects indicating environment constraints bound by execution models.

        Raises:
            Exception: Thrown if generic tracking states are disrupted ungracefully.

        Returns:
            None
        """
        mlflow.log_params({k: str(v) for k, v in params.items()})

    def log_model(self, model, artifact_path: str) -> None:
        """
        Log a completed natively trained model entity securely directly onto tracking locations securely.

        Implicitly inspects objects searching for specific methods separating XGBoost wrappers directly from internal sklearn objects dynamically.

        Args:
            model (Any): Generic initialized variable capturing fitted structure boundaries explicitly targeting predictions.
            artifact_path (str): Sub-path file prefix strings explicitly identifying model registry binding endpoints correctly.

        Raises:
            Exception: Fails when serialization breaks structural bounds on models unsuited for explicit pickling wrappers.

        Returns:
            None
        """
        if hasattr(model, "get_booster"):
            mlflow.xgboost.log_model(model, artifact_path)
        else:
            mlflow.sklearn.log_model(model, artifact_path)
        logger.info("Model logged to artifact_path='%s'", artifact_path)

    def log_png_buffer(self, buf: io.BytesIO, filename: str) -> None:
        """
        Log loaded memory buffered PNG outputs cleanly tracking explicitly as MLflow mapped artifacts.

        Args:
            buf (io.BytesIO): Native standard IO buffer wrapping explicit PNG image bytes dynamically loaded purely in memory structures.
            filename (str): Final tracked name mapping the artifact appropriately.

        Raises:
            Exception: Triggered explicitly when temporary file access patterns break out from standard IO limit windows natively.

        Returns:
            None
        """
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as f:
            f.write(buf.read())
            tmp_path = f.name
        mlflow.log_artifact(tmp_path, artifact_path="plots")
        os.unlink(tmp_path)

    def log_dataframe(self, df, filename: str) -> None:
        """
        Log pandas dataframe payloads strictly serializing internal structure directly towards MLflow storage layers accurately.

        Args:
            df (pd.DataFrame): Data structure encapsulating reporting information dynamically (ex. drift report summaries).
            filename (str): Name suffixing mapped endpoints correctly linking outputs appropriately.

        Raises:
            Exception: If generic CSV serialization logic boundaries fail interpreting unknown memory chunks properly.

        Returns:
            None
        """
        with tempfile.NamedTemporaryFile(
            suffix=f"_{filename}", delete=False, mode="w"
        ) as f:
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
    Provide robust execution contexts bridging raw training logic perfectly onto tracking run sequences properly.

    Args:
        model_type (str): Dictates explicit target bounds looking against defined logic dictionaries.
        params (dict): Setup bounds carrying logic dynamically logging early on run hooks actively.
        tags (dict | None, optional): Map defining internal tagging structures attaching correctly to execution instances. Defaults to None.

    Raises:
        Exception: Bubbles anything generating out of nested scopes up fully into global failure routines seamlessly.

    Yields:
        RunContext: Constructed connection object holding specific log_* function blocks directly.
    """
    experiment_name = EXPERIMENT_NAMES.get(model_type, model_type)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_URI", "http://localhost:5001"))
    # Redirect artifacts to Azure Blob when configured — MLflow detects az:// prefix
    # and uses adlfs automatically (requires adlfs installed + Azure env vars set).
    artifact_uri = os.environ.get("MLFLOW_ARTIFACT_URI")
    if artifact_uri:
        os.environ["MLFLOW_ARTIFACT_URI"] = artifact_uri
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(tags=tags or {}) as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        run_id = run.info.run_id
        logger.info(
            "MLflow run started: experiment='%s' run_id=%s", experiment_name, run_id
        )
        yield RunContext(run_id=run_id)

    logger.info("MLflow run completed: run_id=%s", run_id)

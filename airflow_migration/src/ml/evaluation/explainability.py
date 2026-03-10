import io
import json
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import shap

logger = logging.getLogger(__name__)

_TOP5_SHARE_THRESHOLD = 0.65  # acceptance criterion


def _patch_shap_xgboost_loader():
    """
    Monkey-patch SHAP to handle XGBoost 2.x UBJSON base_score array formatting natively.

    XGBoost 2.x serialization stores base_score in UBJSON arrays like `[5E-1]`.
    SHAP explicitly decodes the UBJSON buffers during TreeExplainer initialization and
    immediately calls `float(learner_model_param['base_score'])`, triggering a ValueError.
    Patching the decoder ensures we flatten the array before SHAP accesses the dictionary.
    """
    try:
        import shap
        import shap.explainers._tree

        # Prevent double patching
        if hasattr(shap.explainers._tree, "_patched_decode"):
            return

        _orig_decode = shap.explainers._tree.decode_ubjson_buffer

        def _patched_decode(*args, **kwargs):
            res = _orig_decode(*args, **kwargs)
            try:
                import json

                bs = res["learner"]["learner_model_param"]["base_score"]
                if isinstance(bs, str) and bs.startswith("["):
                    res["learner"]["learner_model_param"]["base_score"] = str(
                        float(json.loads(bs)[0])
                    )
            except Exception:
                pass
            return res

        shap.explainers._tree.decode_ubjson_buffer = _patched_decode
        shap.explainers._tree._patched_decode = True
    except ImportError:
        pass


def compute_shap_global(
    model,
    X_test: pd.DataFrame,
    max_samples: int = 2_000,
) -> tuple[np.ndarray, io.BytesIO]:
    """
    Compute global SHAP values and generate a summary plot.

    Uses a random sample of the test set for speed (TreeExplainer is O(N × depth)).
    Saves the plot to a BytesIO buffer for MLflow artifact logging. This validates
    that the model relies on semantically meaningful features.

    Args:
        model (Any): Fitted XGBoost or GBM model with TreeExplainer support.
        X_test (pd.DataFrame): Test feature DataFrame containing the model inputs.
        max_samples (int, optional): Max rows to use for SHAP computation to ensure fast runtime. Defaults to 2000.

    Raises:
        ValueError: If the model is not supported by TreeExplainer or SHAP fails during computation.
        Exception: If SHAP value generation or plotting encounters a runtime issue.

    Returns:
        tuple[np.ndarray, io.BytesIO]: A tuple containing the shap_values_array of shape (n_samples, n_features) and a png_buffer In-memory PNG for logging as an MLflow artifact.
    """
    sample = X_test.sample(min(max_samples, len(X_test)), random_state=42)
    _patch_shap_xgboost_loader()

    # SHAP TreeExplainer cannot natively parse sklearn Pipelines. Unwrap if necessary.
    import sklearn.pipeline

    estimator = (
        model.steps[-1][1] if isinstance(model, sklearn.pipeline.Pipeline) else model
    )

    explainer = shap.TreeExplainer(estimator)
    shap_values = explainer.shap_values(sample)
    # For binary XGBoost, TreeExplainer returns a list [class0_array, class1_array].
    if isinstance(shap_values, list):
        shap_values = shap_values[1]

    # Validate global explanation concentration
    mean_abs = np.abs(shap_values).mean(axis=0)
    top5_idx = mean_abs.argsort()[-5:][::-1]
    top5_share = mean_abs[top5_idx].sum() / mean_abs.sum()

    if top5_share < _TOP5_SHARE_THRESHOLD:
        logger.warning(
            "SHAP: top-5 features explain only %.0f%% of global impact (threshold: %.0f%%). "
            "Model may be relying on many weak signals — consider feature selection.",
            top5_share * 100,
            _TOP5_SHARE_THRESHOLD * 100,
        )
    else:
        logger.info(
            "SHAP: top-5 features explain %.0f%% of global impact (OK)",
            top5_share * 100,
        )

    top5_features = [sample.columns[i] for i in top5_idx]
    logger.info("SHAP: top features = %s", top5_features)

    # Save summary plot to buffer
    buf = io.BytesIO()
    fig, ax = plt.subplots(figsize=(10, 6))
    shap.summary_plot(shap_values, sample, show=False)
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close("all")
    buf.seek(0)

    return shap_values, buf


def compute_shap_local(
    model,
    X_student: pd.DataFrame,
) -> dict:
    """
    Compute SHAP values for a single student and return top-5 factors.

    Called by the prediction API to explain individual predictions to school managers.
    The output format strictly adheres to the 'top_factors' field defined in the DropoutResponse schema.

    Args:
        model (Any): Fitted tree model supported by SHAP TreeExplainer.
        X_student (pd.DataFrame): Single-row DataFrame containing the specific student's feature values.

    Raises:
        ValueError: If the provided `X_student` DataFrame does not contain exactly a single row.
        Exception: If the TreeExplainer fails to compute SHAP values.

    Returns:
        dict: A dictionary containing 'base_value' (the mean prediction output), 'top_factors' (list of top 5 impact dictionaries sorted by absolute impact), and 'all_shap_values' (detailed feature to impact mapping).
    """
    if len(X_student) != 1:
        raise ValueError(f"Expected single-row DataFrame, got {len(X_student)} rows.")

    _patch_shap_xgboost_loader()
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_student)
    # For binary XGBoost, TreeExplainer returns a list [class0_array, class1_array].
    if isinstance(shap_values, list):
        values = shap_values[1][0]  # class-1, single row
    else:
        values = shap_values[0]  # regression, single row
    base_value = float(
        explainer.expected_value[1]
        if isinstance(explainer.expected_value, (list, np.ndarray))
        else explainer.expected_value
    )

    feature_impact = [
        {
            "feature": feat,
            "impact": round(float(val), 4),
            "direction": "increases_risk" if val > 0 else "decreases_risk",
        }
        for feat, val in zip(X_student.columns, values)
    ]
    feature_impact.sort(key=lambda x: abs(x["impact"]), reverse=True)

    return {
        "base_value": base_value,
        "top_factors": feature_impact[:5],
        "all_shap_values": {f["feature"]: f["impact"] for f in feature_impact},
    }

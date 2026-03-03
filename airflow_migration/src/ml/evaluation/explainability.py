# src/ml/evaluation/explainability.py
"""
SHAP explainability for tree models.

Two entry points:
1. compute_shap_global(): Summary plot across the test set. Saved as PNG artifact in MLflow.
   Used to validate that the model learns from the right features (attendance, grades)
   rather than spurious correlates. Top-5 features must explain ≥ 65% of global impact.

2. compute_shap_local(): Per-student SHAP decomposition. Called by the API's
   /predict/dropout/{student_id} endpoint to return top-5 factors to the user.

The 'factors' format matches the DropoutResponse schema in PLAN-ML-03-API-SERVING.md §2.

References:
- Global validation criterion: acceptance criteria table §12
- Local output used by: PLAN-ML-03-API-SERVING.md routes/predict.py
- SHAP interpretation for RAG: PLAN-ML-02-RAG-LLM.md §8 (context builder)
"""
import io
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import shap

logger = logging.getLogger(__name__)

_TOP5_SHARE_THRESHOLD = 0.65   # acceptance criterion


def compute_shap_global(
    model,
    X_test: pd.DataFrame,
    max_samples: int = 2_000,
) -> tuple[np.ndarray, io.BytesIO]:
    """
    Compute global SHAP values and generate a summary plot.

    Uses a random sample of the test set for speed (TreeExplainer is O(N × depth)).
    Saves the plot to a BytesIO buffer for MLflow artifact logging.

    Args:
        model: Fitted XGBoost or GBM model with TreeExplainer support.
        X_test: Test feature DataFrame.
        max_samples: Max rows to use for SHAP computation.

    Returns:
        Tuple of (shap_values_array, png_buffer).
        shap_values_array shape: (n_samples, n_features).
        png_buffer: In-memory PNG for logging as MLflow artifact.

    Raises:
        Warning if top-5 features explain < 65% of global SHAP impact.
    """
    sample = X_test.sample(min(max_samples, len(X_test)), random_state=42)
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)

    # Validate global explanation concentration
    mean_abs      = np.abs(shap_values).mean(axis=0)
    top5_idx      = mean_abs.argsort()[-5:][::-1]
    top5_share    = mean_abs[top5_idx].sum() / mean_abs.sum()

    if top5_share < _TOP5_SHARE_THRESHOLD:
        logger.warning(
            "SHAP: top-5 features explain only %.0f%% of global impact (threshold: %.0f%%). "
            "Model may be relying on many weak signals — consider feature selection.",
            top5_share * 100, _TOP5_SHARE_THRESHOLD * 100,
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
    The output format matches the 'top_factors' field in DropoutResponse
    (PLAN-ML-03-API-SERVING.md §2).

    Args:
        model: Fitted tree model.
        X_student: Single-row DataFrame with the student's feature values.

    Returns:
        Dict with:
        - 'base_value': float — model's expected output (mean prediction)
        - 'top_factors': list of 5 dicts [{feature, impact, direction}]
                         sorted by abs(impact) descending
        - 'all_shap_values': dict of {feature: shap_value} for all features
    """
    if len(X_student) != 1:
        raise ValueError(f"Expected single-row DataFrame, got {len(X_student)} rows.")

    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_student)
    values      = shap_values[0] if isinstance(shap_values, list) else shap_values[0]

    feature_impact = [
        {
            "feature":   feat,
            "impact":    round(float(val), 4),
            "direction": "increases_risk" if val > 0 else "decreases_risk",
        }
        for feat, val in zip(X_student.columns, values)
    ]
    feature_impact.sort(key=lambda x: abs(x["impact"]), reverse=True)

    return {
        "base_value":       float(explainer.expected_value),
        "top_factors":      feature_impact[:5],
        "all_shap_values":  {f["feature"]: f["impact"] for f in feature_impact},
    }

# src/ml/evaluation/metrics.py
"""
Metric computation functions — pure, no side effects, no logging dependencies.

All functions accept numpy arrays and return dataclasses. The training entrypoints
log these via MLflow (mlops/experiment.py). Metrics themselves don't know about
MLflow, logging, or file systems.

Acceptance criteria (see full table in this document §12):
- Dropout classifier: AUROC ≥ 0.82, Recall ≥ 0.75, F1 ≥ 0.70
- Grade regressor: RMSE ≤ 1.5, R² ≥ 0.60
- Clustering: Silhouette ≥ 0.35
"""
from dataclasses import dataclass
import numpy as np
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score, recall_score,
    mean_squared_error, r2_score, average_precision_score,
)


@dataclass(frozen=True)
class ClassificationMetrics:
    """
    Evaluation metrics for binary classification.

    Attributes:
        auroc: Area Under ROC Curve. Threshold-independent overall performance.
        auprc: Area Under Precision-Recall Curve. Better for imbalanced classes.
        f1: F1 score at 0.5 threshold. Harmonic mean of precision and recall.
        precision: True positive rate among predicted positives.
        recall: True positive rate among actual positives. Critical for dropout detection.
    """
    auroc:     float
    auprc:     float
    f1:        float
    precision: float
    recall:    float

    def as_dict(self) -> dict[str, float]:
        """Return all metrics as a flat dict (ready for MLflow log_metrics)."""
        return {
            "auroc": self.auroc, "auprc": self.auprc,
            "f1": self.f1, "precision": self.precision, "recall": self.recall,
        }

    def passes_acceptance(self) -> bool:
        """Return True if all metrics meet the acceptance criteria."""
        return self.auroc >= 0.82 and self.recall >= 0.75 and self.f1 >= 0.70


@dataclass(frozen=True)
class RegressionMetrics:
    """
    Evaluation metrics for regression (grade prediction).

    Attributes:
        rmse: Root Mean Square Error. In grade units (0–10 scale).
        r2: Coefficient of determination. 1.0 = perfect, 0 = predicts mean.
        mae: Mean Absolute Error. More interpretable than RMSE for grades.
    """
    rmse: float
    r2:   float
    mae:  float

    def as_dict(self) -> dict[str, float]:
        return {"rmse": self.rmse, "r2": self.r2, "mae": self.mae}

    def passes_acceptance(self) -> bool:
        return self.rmse <= 1.5 and self.r2 >= 0.60


def eval_classifier(y_true: np.ndarray, y_prob: np.ndarray) -> ClassificationMetrics:
    """
    Compute all classification metrics from probabilities.

    Args:
        y_true: Ground truth binary labels (0/1).
        y_prob: Predicted probabilities for the positive class.

    Returns:
        ClassificationMetrics dataclass.
    """
    y_pred = (y_prob >= 0.5).astype(int)
    return ClassificationMetrics(
        auroc     = roc_auc_score(y_true, y_prob),
        auprc     = average_precision_score(y_true, y_prob),
        f1        = f1_score(y_true, y_pred, zero_division=0),
        precision = precision_score(y_true, y_pred, zero_division=0),
        recall    = recall_score(y_true, y_pred, zero_division=0),
    )


def eval_regressor(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionMetrics:
    """
    Compute regression metrics for grade prediction.

    Args:
        y_true: Ground truth normalized grades (0.0–10.0).
        y_pred: Predicted grades (0.0–10.0).

    Returns:
        RegressionMetrics dataclass.
    """
    return RegressionMetrics(
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred))),
        r2   = float(r2_score(y_true, y_pred)),
        mae  = float(np.mean(np.abs(y_true - y_pred))),
    )

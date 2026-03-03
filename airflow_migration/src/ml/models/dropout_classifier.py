# src/ml/models/dropout_classifier.py
"""
XGBoost binary classifier for student dropout prediction.

Target: target_evasao (0/1) — student missed > 25% of scheduled school days.

Design notes:
- scale_pos_weight is computed automatically from class ratio when not provided.
  This is critical: our dataset has very few actual dropouts (class imbalance).
  Without this, the model predicts 0 for almost all students and gets high accuracy
  but zero recall on the minority (dropout) class.
- eval_metric = 'aucpr' (Area Under Precision-Recall Curve) is chosen over 'auc'
  (ROC AUC) because with high class imbalance, ROC AUC can be misleadingly high
  even when the model fails to catch actual dropouts.
- early_stopping_rounds prevents overfitting without a fixed n_estimators.
  The model stops when eval set performance stops improving.
- This class knows nothing about MLflow. The training entrypoint (train_evasao.py)
  wraps it in log_run().

References:
- Feature set: schema.py FEATURES_EVASAO_EF1
- Target derivation: taxa_ausencia > 25% — see PLAN-ML-NEO4J-SCHOOL.md §2.1
- Score comparison: Q_RISCO_EVASAO_EF2.md (40% absence component maps to this target)
"""
import logging
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from xgboost import XGBClassifier

logger = logging.getLogger(__name__)


@dataclass
class DropoutConfig:
    """
    Hyperparameter configuration for the dropout XGBoost model.

    These are the base values. The training entrypoint may override any field
    based on Optuna search or sweep results logged to MLflow.

    Attributes:
        n_estimators: Maximum number of trees. Actual count determined by early stopping.
        max_depth: Maximum depth per tree. 6 is a good balance for tabular data.
        learning_rate: Step size shrinkage — lower = more conservative.
        subsample: Fraction of training samples per tree.
        colsample_bytree: Fraction of features per tree.
        early_stopping_rounds: Stop if eval set metric doesn't improve for N rounds.
        eval_metric: 'aucpr' for imbalanced classification. Prefer over 'auc'.
        random_state: Seed for reproducibility.
        scale_pos_weight: Ratio of negative to positive class.
                          None = auto-compute from training labels.
    """
    n_estimators:          int   = 500
    max_depth:             int   = 6
    learning_rate:         float = 0.05
    subsample:             float = 0.8
    colsample_bytree:      float = 0.8
    early_stopping_rounds: int   = 50
    eval_metric:           str   = "aucpr"
    random_state:          int   = 42
    scale_pos_weight:      float | None = None


def build_dropout_model(config: DropoutConfig) -> XGBClassifier:
    """
    Instantiate an XGBClassifier from a DropoutConfig.

    Args:
        config: Hyperparameter configuration (from DropoutConfig or mlflow params).

    Returns:
        Unfitted XGBClassifier.
    """
    return XGBClassifier(
        n_estimators           = config.n_estimators,
        max_depth              = config.max_depth,
        learning_rate          = config.learning_rate,
        subsample              = config.subsample,
        colsample_bytree       = config.colsample_bytree,
        early_stopping_rounds  = config.early_stopping_rounds,
        eval_metric            = config.eval_metric,
        scale_pos_weight       = config.scale_pos_weight,
        random_state           = config.random_state,
        n_jobs                 = -1,
        tree_method            = "hist",   # faster for large datasets
    )


def compute_scale_pos_weight(y_train: pd.Series) -> float:
    """
    Compute scale_pos_weight from training labels.

    XGBoost documentation recommends count(negative) / count(positive).
    Applied only to training labels to avoid any validation leakage.

    Args:
        y_train: Training target Series (binary 0/1).

    Returns:
        Float ratio: n_negative / n_positive.
    """
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    if n_pos == 0:
        logger.error("Training set has zero positive examples (no dropouts). Check target derivation.")
        raise ValueError("No positive examples in training set.")
    ratio = n_neg / n_pos
    logger.info("Class ratio: %d negative / %d positive = scale_pos_weight=%.2f", n_neg, n_pos, ratio)
    return ratio


def train_dropout(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val:   pd.DataFrame,
    y_val:   pd.Series,
    config:  DropoutConfig | None = None,
) -> XGBClassifier:
    """
    Train the dropout classifier with early stopping on a validation set.

    The validation set should be the last 15% of the TRAINING years (not the
    test year). This gives early stopping a holdout without contaminating the
    temporal test set.

    Args:
        X_train: Training features (from temporal_split, excluding validation rows).
        y_train: Training labels.
        X_val: Validation features (last 15% of train rows, same years as X_train).
        y_val: Validation labels.
        config: Hyperparameter config. If None, uses DropoutConfig defaults.

    Returns:
        Fitted XGBClassifier. Check model.best_iteration for actual tree count.
    """
    cfg = config or DropoutConfig()

    if cfg.scale_pos_weight is None:
        cfg.scale_pos_weight = compute_scale_pos_weight(y_train)

    model = build_dropout_model(cfg)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    logger.info(
        "Dropout model trained: best_iteration=%d / n_estimators=%d",
        model.best_iteration, cfg.n_estimators,
    )
    return model


def predict_dropout(model: XGBClassifier, X: pd.DataFrame) -> dict[str, np.ndarray]:
    """
    Generate dropout predictions for a batch of students.

    Args:
        model: Fitted XGBClassifier.
        X: Feature DataFrame with same columns as training (from FEATURES_EVASAO_EF1).

    Returns:
        Dict with keys:
        - 'evasao_prob': float array [0, 1] — probability of dropout
        - 'evasao_label': int array {0, 1} — binary prediction at 0.5 threshold
    """
    proba = model.predict_proba(X)[:, 1]
    label = (proba >= 0.5).astype(int)
    return {"evasao_prob": proba, "evasao_label": label}

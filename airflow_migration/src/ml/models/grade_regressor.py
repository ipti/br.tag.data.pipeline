# src/ml/models/grade_regressor.py
"""
GradientBoostingRegressor for EF2 normalized final grade prediction.

Target: target_nota (float 0.0–10.0) — normalized final_mean per student.
Scope: EF2 only (Fundamental II, grades 6–9). EF1 has a single global grade,
which is already part of the dropout feature set but doesn't benefit from
per-subject regression.

The Q_RISCO_EVASAO_EF2.md risk score includes a 35% weight on grades below 5.0
and a 25% weight on inverted mean. This model complements that analytic by
predicting the grade BEFORE end of year (using grade_1, grade_2 as input),
enabling earlier intervention.

References:
- Feature set: schema.py FEATURES_NOTAS_EF2
- Risk score that uses grade output: Q_RISCO_EVASAO_EF2.md §Score de Risco
- EF2 grade extraction query: PLAN-ML-NEO4J-SCHOOL.md §3.2
"""
import logging
from dataclasses import dataclass
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

logger = logging.getLogger(__name__)


@dataclass
class GradeRegressorConfig:
    """
    Hyperparameter configuration for the grade GBM regressor.

    Attributes:
        n_estimators: Number of boosting stages.
        max_depth: Maximum depth per tree (shallower than XGBoost to reduce overfitting).
        learning_rate: Shrinkage applied to each tree contribution.
        subsample: Fraction of samples for stochastic gradient boosting.
        random_state: Seed for reproducibility.
    """
    n_estimators: int   = 300
    max_depth:    int   = 5
    learning_rate: float = 0.05
    subsample:    float = 0.8
    random_state: int   = 42


def train_grade_regressor(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: GradeRegressorConfig | None = None,
) -> GradientBoostingRegressor:
    """
    Fit the grade regression model on EF2 student features.

    Args:
        X_train: Training features from FEATURES_NOTAS_EF2.
        y_train: Training target — normalized final_mean (0.0–10.0).
        config: Hyperparameter config. If None, uses defaults.

    Returns:
        Fitted GradientBoostingRegressor.
    """
    cfg = config or GradeRegressorConfig()
    model = GradientBoostingRegressor(
        n_estimators=cfg.n_estimators,
        max_depth=cfg.max_depth,
        learning_rate=cfg.learning_rate,
        subsample=cfg.subsample,
        random_state=cfg.random_state,
    )
    model.fit(X_train, y_train)
    logger.info("Grade regressor trained on %d samples", len(X_train))
    return model

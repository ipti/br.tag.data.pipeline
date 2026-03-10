import logging
from dataclasses import dataclass
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)


@dataclass
class GradeRegressorConfig:
    """
    Hyperparameter tracking settings explicit towards gradient boosting regressor models precisely.

    Attributes:
        n_estimators (int): Boundary constraints targeting total distinct stage counts safely.
        max_depth (int): Internal dimension structures aggressively mapping local tree bounds statically.
        learning_rate (float): Incremental step shrinkage explicitly handling boosting layers mathematically cleanly.
        subsample (float): Explicit fractions mapping sub-samples safely without over-indexing natively.
        random_state (int): Anchor point defining internal replication exactly deterministically.
    """

    n_estimators: int = 300
    max_depth: int = 5
    learning_rate: float = 0.05
    subsample: float = 0.8
    random_state: int = 42


def train_grade_regressor(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: GradeRegressorConfig | None = None,
) -> Pipeline:
    """
    Fit absolute grade predictive regression targets explicitly matching EF2 segment profiles cleanly natively.

    Args:
        X_train (pd.DataFrame): Full mapped structures explicitly defining input columns flawlessly.
        y_train (pd.Series): Bounded labels (float 0.0-10.0) correctly mapping student targets fully natively.
        config (GradeRegressorConfig | None, optional): Custom mapping overrides passing parameter settings manually safely. Defaults to None.

    Raises:
        Exception: Fails when missing column data breaks underlying validation constraints directly internally.

    Returns:
        Pipeline: Completely evaluated predictive endpoint accurately mapping final outcomes securely.
    """
    cfg = config or GradeRegressorConfig()
    model = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "regressor",
                GradientBoostingRegressor(
                    n_estimators=cfg.n_estimators,
                    max_depth=cfg.max_depth,
                    learning_rate=cfg.learning_rate,
                    subsample=cfg.subsample,
                    random_state=cfg.random_state,
                ),
            ),
        ]
    )
    model.fit(X_train, y_train)
    logger.info("Grade regressor trained on %d samples", len(X_train))
    return model

import logging
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from xgboost import XGBClassifier

logger = logging.getLogger(__name__)


@dataclass
class DropoutConfig:
    """
    Hyperparameter configuration container pointing toward explicit dropout XGBoost models statically.

    Attributes:
        n_estimators (int): Boundary limits restricting total boosted tree counts actively.
        max_depth (int): Peak node limits mapping individual tree spans contextually.
        learning_rate (float): Shrinkage values defining conservative vs rapid loss optimization bounds logically.
        subsample (float): Data slice fraction bounds establishing row samplings natively.
        colsample_bytree (float): Column fractional slices reducing tree dimensions dynamically.
        early_stopping_rounds (int): Epoch threshold halts monitoring metric plateaus securely.
        eval_metric (str): Explicit name denoting specific target loss paths guiding metrics cleanly.
        random_state (int): Native mapping constants stabilizing repeatable executions accurately.
        scale_pos_weight (float | None): Positive weight multiplier explicitly assisting minor classes forcefully. Defaults to None.
    """

    n_estimators: int = 500
    max_depth: int = 6
    learning_rate: float = 0.05
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    early_stopping_rounds: int = 50
    eval_metric: str = "aucpr"
    random_state: int = 42
    scale_pos_weight: float | None = None


def build_dropout_model(config: DropoutConfig) -> XGBClassifier:
    """
    Instantiate pure, unfitted XGBClassifier structures mapping explicit configuration profiles deterministically.

    Args:
        config (DropoutConfig): Strongly-typed dataclass object containing mapped tuning bounds securely.

    Raises:
        Exception: If initialized parameter structures break underlying XGBoost native binding requirements.

    Returns:
        XGBClassifier: Untrained model artifact mapped heavily targeting standard dropout behavior cleanly.
    """
    return XGBClassifier(
        n_estimators=config.n_estimators,
        max_depth=config.max_depth,
        learning_rate=config.learning_rate,
        subsample=config.subsample,
        colsample_bytree=config.colsample_bytree,
        early_stopping_rounds=config.early_stopping_rounds,
        eval_metric=config.eval_metric,
        scale_pos_weight=config.scale_pos_weight,
        random_state=config.random_state,
        n_jobs=-1,
        tree_method="hist",  # faster for large datasets
    )


def compute_scale_pos_weight(y_train: pd.Series) -> float:
    """
    Compute balancing properties mapping negative samples reliably across existing structural classes.

    Args:
        y_train (pd.Series): Labeled pandas column structurally indexing target outcome dimensions securely.

    Raises:
        ValueError: Triggers aggressively protecting models when explicit positive dropout records total absolutely zero boundaries locally.
        Exception: Rare index structural alignment issues natively throwing against pandas API frames.

    Returns:
        float: Precisely calculated float ratios indicating positive target re-weights.
    """
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    if n_pos == 0:
        logger.error(
            "Training set has zero positive examples (no dropouts). Check target derivation."
        )
        raise ValueError("No positive examples in training set.")
    ratio = n_neg / n_pos
    logger.info(
        "Class ratio: %d negative / %d positive = scale_pos_weight=%.2f",
        n_neg,
        n_pos,
        ratio,
    )
    return ratio


def train_dropout(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    config: DropoutConfig | None = None,
) -> XGBClassifier:
    """
    Train designated dropout classifiers actively tracking early stopping mechanisms strictly over valid temporal folds natively.

    Args:
        X_train (pd.DataFrame): Pure numerical target features exclusively covering core temporal training blocks natively.
        y_train (pd.Series): Expected numerical targets explicitly covering exact identical alignment constraints.
        X_val (pd.DataFrame): Separate validation holding dimensions preventing direct leakage across training blocks explicitly.
        y_val (pd.Series): Purely validation targets mirroring X_val natively.
        config (DropoutConfig | None, optional): Tracked hyperparameter profiles mapping explicit parameter bounds directly. Defaults to None.

    Raises:
        Exception: Broad breaks mapping against XGBoost execution states directly due to corrupted column structures iteratively.

    Returns:
        XGBClassifier: Extensively trained model mapping explicit prediction boundaries successfully over current records effectively.
    """
    cfg = config or DropoutConfig()

    if cfg.scale_pos_weight is None:
        cfg.scale_pos_weight = compute_scale_pos_weight(y_train)

    model = build_dropout_model(cfg)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    logger.info(
        "Dropout model trained: best_iteration=%d / n_estimators=%d",
        model.best_iteration,
        cfg.n_estimators,
    )
    return model


def predict_dropout(model: XGBClassifier, X: pd.DataFrame) -> dict[str, np.ndarray]:
    """
    Generate robust dropout mapping arrays combining raw probability dimensions explicitly pointing towards binary threshold labels properly.

    Args:
        model (XGBClassifier): Core fitted classifier structurally mapped containing tree components deeply.
        X (pd.DataFrame): Incoming un-flagged inputs explicitly tracking pre-defined column limits evenly.

    Raises:
        Exception: If structurally missing column names fall cleanly outside native expectations aggressively.

    Returns:
        dict[str, np.ndarray]: Dictionary linking mapped output probabilities precisely to absolute threshold logic securely.
    """
    proba = model.predict_proba(X)[:, 1]
    label = (proba >= 0.5).astype(int)
    return {"evasao_prob": proba, "evasao_label": label}

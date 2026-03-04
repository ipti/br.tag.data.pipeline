# MLOps Directory

This directory contains logic associated with tracking model training behavior, storing output metrics securely, and managing explicit lifecycle promotions dynamically using MLOps methodologies.

## champion_challenger.py
Champion/Challenger pattern for automatic model promotion.

Supports both classification models (primary metric: auroc, higher is better) and regression models (primary metric: r2, higher is better).

The `model_type` parameter drives which metric is used for comparison and which artifact path is used for registration. Adding a new model type requires only adding an entry to `_MODEL_CONFIG`.

Threshold prevents churn from small fluctuations between training runs.
All promotion decisions are logged with full metric context for audit.

## experiment.py
Thin MLflow context manager for experiment tracking.

The model training functions (e.g., dropout_classifier.py, grade_regressor.py) are completely unaware of MLflow. This module wraps them in an `mlflow.start_run()` context, providing a clean `RunContext` object to the entrypoints.

Experiment names map to model types. Changing the experiment name here changes it everywhere — no scattered `mlflow.set_experiment()` calls in other files.

Usage in training entrypoint:
```python
with log_run("evasao", params=vars(config), tags={"segment": "EF1"}) as run:
    model = train_dropout(X_tr, y_tr, X_val, y_val, config)
    metrics = eval_classifier(y_test.values, predict_dropout(model, X_test)["evasao_prob"])
    run.log_metrics(metrics.as_dict())
    run.log_model(model, artifact_path="dropout_model")
    run_id = run.run_id
```

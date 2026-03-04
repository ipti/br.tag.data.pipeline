# Evaluation Documentation

This directory contains pure, side-effect-free evaluation modules for assessing machine learning model performance. It forms the core assessment layer prior to deploying models to production stages.

## Structure
- `explainability.py`: Modules dealing with interpreting model predictions.
- `metrics.py`: Strict performance calculation methods for tracking offline evaluation metrics.

## Explainability
`explainability.py` provides SHAP (SHapley Additive exPlanations) explainability specifically for tree models. 

It contains two entry points:
1. **Global Explainability (`compute_shap_global`)**: Summary plot across the test set. Saved as PNG artifact in MLflow. Used to validate that the model learns from the right features (e.g., attendance and grades) rather than spurious correlates. **Top-5 features must explain ≥ 65% of global impact**.
2. **Local Explainability (`compute_shap_local`)**: Per-student SHAP decomposition. Called by the prediction API's `/predict/dropout/{student_id}` endpoint to directly return top-5 contributing factors to the user (managers or principals).

*References*:
- Global validation criterion: acceptance criteria table §12
- Local output used by: PLAN-ML-03-API-SERVING.md routes/predict.py
- SHAP interpretation for RAG: PLAN-ML-02-RAG-LLM.md §8 (context builder)

## Metrics
`metrics.py` contains metric computation functions. All functions accept numpy arrays as standard inputs and return strictly typed dataclasses. 

The training entrypoints log these directly via MLflow (`mlops/experiment.py`). However, the metrics definitions themselves are decoupled; they don't know about MLflow, logging, or file systems, keeping the assessment logic pure.

*Acceptance Criteria* (see full table in this document §12):
- **Dropout classifier**: AUROC ≥ 0.82, Recall ≥ 0.75, F1 ≥ 0.70
- **Grade regressor**: RMSE ≤ 1.5, R² ≥ 0.60
- **Clustering**: Silhouette ≥ 0.35

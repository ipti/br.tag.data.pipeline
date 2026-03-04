# Training Directory

This directory contains the entrypoint scripts orchestrating the full end-to-end model training pipelines for the ML workflows.

## train_evasao.py
Dropout model training entrypoint.

Orchestrates the full training pipeline:
1. Extract EF1 features from Neo4j (`neo4j_extractor.py`)
2. Encode categoricals and derive features (`feature_pipeline.py`)
3. Fill grade sentinel values for students without registered grades
4. Temporal split: train on years < `test_year`, hold out `test_year` as test set
5. Further split train set 85/15 for early stopping validation
6. Train XGBoost with auto-computed `scale_pos_weight`
7. Evaluate on held-out test set (temporal)
8. Compute global SHAP for feature validation
9. Log everything to MLflow (`experiment.py`)
10. Champion/Challenger: promote if AUROC improves by > 0.01
11. Write `risk_score` and `risk_cluster` back to Neo4j (`risk_clusterer.py`)

## train_notas.py
Grade regression model training entrypoint (EF2).

Orchestrates the full grade regression pipeline:
1. Extract EF2 base features (demographics, health, attendance, IBGE) from Neo4j
2. Extract EF2 grade pivot (per-subject normalized grades) from Neo4j
3. Merge both DataFrames on `student_id` — EF2 base is the join anchor
4. Encode categoricals and fill grade sentinels
5. Temporal split: train on years < `test_year`, hold out `test_year`
6. Train GradientBoostingRegressor on features
7. Evaluate on held-out test set (RMSE, R², MAE)
8. Compute SHAP global for feature validation
9. Log to MLflow via `log_run()` context manager
10. Champion/Challenger: promote if R² improves > threshold

Why EF2 base features? The grade regression model needs demographic + health + attendance context from EF2 students specifically (grades 6-9). `extract_ef2_grades()` gives per-subject grades, but not demographics or IBGE. `extract_ef1()` gives those but filters EF1 students only. The EF2 base query provides the full context.

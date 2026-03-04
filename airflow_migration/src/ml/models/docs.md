# Models Directory

This directory contains the implementations of various machine learning models used for prediction and clustering.

## dropout_classifier.py
XGBoost binary classifier for student dropout prediction.

Target: `target_evasao` (0/1) — student missed > 25% of scheduled school days.

Design notes:
- `scale_pos_weight` is computed automatically from class ratio when not provided. This is critical: our dataset has very few actual dropouts (class imbalance). Without this, the model predicts 0 for almost all students and gets high accuracy but zero recall on the minority (dropout) class.
- `eval_metric = 'aucpr'` (Area Under Precision-Recall Curve) is chosen over 'auc' (ROC AUC) because with high class imbalance, ROC AUC can be misleadingly high even when the model fails to catch actual dropouts.
- `early_stopping_rounds` prevents overfitting without a fixed `n_estimators`. The model stops when eval set performance stops improving.
- This class knows nothing about MLflow. The training entrypoint (`train_evasao.py`) wraps it in `log_run()`.

## grade_regressor.py
GradientBoostingRegressor for EF2 normalized final grade prediction.

Target: `target_nota` (float 0.0–10.0) — normalized final_mean per student.
Scope: EF2 only (Fundamental II, grades 6–9). EF1 has a single global grade, which is already part of the dropout feature set but doesn't benefit from per-subject regression.

The risk score includes a 35% weight on grades below 5.0 and a 25% weight on inverted mean. This model complements that analytic by predicting the grade BEFORE end of year (using grade_1, grade_2 as input), enabling earlier intervention.

## risk_clusterer.py
KMeans clustering over normalized student features.

Clusters represent distinct risk profiles (e.g., high absence + low grade + rural, vs low absence + health conditions + high social vulnerability).

After fitting:
- Cluster labels are written back to Neo4j as `stu.risk_cluster` (int)
- The dropout probability from model A is written as `stu.risk_score` (float)
- These are used by the RAG retriever to find similar students via vector index and interpret cluster membership

The Silhouette Score drives cluster count selection. We search `k` in [3, 8] to find the `k` that maximizes separation without over-segmentation.

PCA before KMeans:
- High-dimensional feature space (50+ features) causes distance metrics to degrade (curse of dimensionality)
- PCA with 95% variance retention typically reduces to 10–15 components
- This improves both clustering quality and speed

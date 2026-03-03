# src/ml/models/risk_clusterer.py
"""
KMeans clustering over normalized student features.

Clusters represent distinct risk profiles (e.g., high absence + low grade + rural,
vs low absence + health conditions + high social vulnerability).

After fitting:
- Cluster labels are written back to Neo4j as stu.risk_cluster (int)
- The dropout probability from model A is written as stu.risk_score (float)
- These are used by the RAG retriever (PLAN-ML-02-RAG-LLM.md §4) to find
  similar students via vector index and interpret cluster membership

The Silhouette Score drives cluster count selection. We search k ∈ [3, 8]
to find the k that maximizes separation without over-segmentation.

PCA before KMeans:
- High-dimensional feature space (50+ features) causes distance metrics to
  degrade (curse of dimensionality)
- PCA with 95% variance retention typically reduces to 10–15 components
- This improves both clustering quality and speed

References:
- risk_cluster writeback used by: PLAN-ML-02-RAG-LLM.md §4 (RAG retriever)
- risk_cluster used by: PLAN-ML-03-API-SERVING.md §11 (/predict/dropout)
- Silhouette target: ≥ 0.35 (acceptance criteria table below)
"""
import logging
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import silhouette_score
from neo4j import Driver

logger = logging.getLogger(__name__)

_WRITEBACK_QUERY = """
UNWIND $rows AS row
MATCH (stu:Student {id: row.student_id})
SET stu.risk_cluster = row.cluster,
    stu.risk_score    = row.risk_score
"""


def fit_risk_clusters(
    X: pd.DataFrame,
    k_range: tuple[int, int] = (3, 8),
    pca_variance: float = 0.95,
    random_state: int = 42,
) -> tuple[KMeans, np.ndarray, float, int]:
    """
    Fit KMeans clusters over PCA-reduced features.

    Searches for the optimal k by Silhouette Score within k_range.
    Logs the score for each k for transparency in MLflow.

    Args:
        X: Feature DataFrame (all numeric, no nulls). Run fill_grade_sentinel()
           and encode_categoricals() before calling.
        k_range: Tuple (min_k, max_k) to search.
        pca_variance: Fraction of variance to retain in PCA reduction.
        random_state: Seed for reproducibility.

    Returns:
        Tuple of (best_kmeans_model, labels_array, best_silhouette_score, best_k).

    Raises:
        ValueError: if X is empty or contains nulls.
    """
    if X.isnull().any().any():
        raise ValueError("Input DataFrame contains nulls. Impute before clustering.")

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    pca = PCA(n_components=pca_variance, random_state=random_state)
    X_pca = pca.fit_transform(X_scaled)
    logger.info(
        "PCA: %d features → %d components (%.0f%% variance retained)",
        X.shape[1], X_pca.shape[1], pca_variance * 100,
    )

    best_k, best_score, best_model, best_labels = None, -1.0, None, None

    for k in range(k_range[0], k_range[1] + 1):
        km = KMeans(n_clusters=k, random_state=random_state, n_init=10)
        labels = km.fit_predict(X_pca)
        score  = silhouette_score(
            X_pca, labels,
            sample_size=min(5_000, len(X_pca)),
            random_state=random_state,
        )
        logger.info("  k=%d → silhouette=%.4f", k, score)

        if score > best_score:
            best_k, best_score, best_model, best_labels = k, score, km, labels

    logger.info("Best clustering: k=%d (silhouette=%.4f)", best_k, best_score)

    if best_score < 0.35:
        logger.warning(
            "Silhouette score %.4f is below acceptance threshold 0.35. "
            "Consider feature selection or different k_range.", best_score,
        )

    return best_model, best_labels, best_score, best_k


def write_clusters_to_neo4j(
    driver: Driver,
    student_ids: list[str],
    cluster_labels: np.ndarray,
    risk_scores: np.ndarray,
    batch_size: int = 500,
) -> None:
    """
    Write cluster labels and risk scores back to Neo4j Student nodes.

    Sets stu.risk_cluster (int) and stu.risk_score (float) for each student.
    These properties are read by:
    - RAG retriever: find_similar_students() filters by risk_cluster
    - API: /predict/dropout returns risk_cluster alongside probability

    Args:
        driver: Neo4j driver instance.
        student_ids: List of student IDs (must match Student.id in Neo4j).
        cluster_labels: Array of int cluster labels, same length as student_ids.
        risk_scores: Array of float dropout probabilities from Model A.
        batch_size: Number of rows per transaction (avoids large single commits).
    """
    rows = [
        {
            "student_id": sid,
            "cluster":    int(lbl),
            "risk_score": float(score),
        }
        for sid, lbl, score in zip(student_ids, cluster_labels, risk_scores)
    ]

    total = len(rows)
    with driver.session() as session:
        for start in range(0, total, batch_size):
            batch = rows[start: start + batch_size]
            session.run(_WRITEBACK_QUERY, rows=batch)
            logger.info("Writeback: %d / %d student cluster records updated", start + len(batch), total)

    logger.info("Neo4j writeback complete: %d students updated with risk_cluster + risk_score", total)

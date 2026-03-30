import glob
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from dotenv import load_dotenv
from neo4j import GraphDatabase

from src.ml.models.risk_clusterer import fit_risk_clusters, write_clusters_to_neo4j

"""
DAG: dag__ml_risk_clustering
================================
Runs the student risk clustering pipeline on Neo4j data.

Steps:
  1. Loads all EF1/EF2 annual Parquet files (no deltas), deduplicates by `student_id`
  2. Fits KMeans via `fit_risk_clusters()` (k=3..8 with PCA at 95% variance)
  3. Computes `risk_score` (0-100) based on average dropout rate per cluster
  4. Writes `risk_cluster` and `risk_score` back to `:Student` nodes in Neo4j

Schedule: None (manual trigger only — run from the Airflow UI when needed)
"""

logger = logging.getLogger(__name__)

_ENV_PATH = Path(__file__).parents[1] / ".env"
if _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# Numeric features used for clustering.
# Excludes targets, IDs, and grade columns (often entirely null across all years).
CLUSTER_FEATURES = [
    "gender_bin",
    "has_deficiency",
    "bolsa_familia",
    "has_health_record",
    "has_malnutrition",
    "has_diabetes",
    "has_hypertension",
    "has_obesity",
    "has_celiac",
    "has_anemia",
    "tem_diario",
    "taxa_ausencia",
    "falta_critica",
    "aluno_reprovado_flag",
    "em_recuperacao",
    "muni_freq_liq_fund",
    "muni_atraso_2anos",
    "muni_analf_adulto",
    "est_ideb_af",
    "est_taxa_abandono",
    "est_taxa_reprovacao",
    "est_distorcao_serie",
]


def _load_students(data_dir: Path) -> pd.DataFrame:
    """Load all annual EF1/EF2 Parquet files and deduplicate by student_id."""
    parquet_pattern_ef1 = str(data_dir / "EF1_2*.parquet")
    parquet_pattern_ef2 = str(data_dir / "EF2_2*.parquet")

    all_files = sorted(
        filepath
        for filepath in glob.glob(parquet_pattern_ef1) + glob.glob(parquet_pattern_ef2)
        if "delta" not in filepath
    )

    if not all_files:
        raise FileNotFoundError(f"No Parquet files found in {data_dir}")

    logger.info("Loading %d Parquet files...", len(all_files))
    df = pd.concat(
        [pd.read_parquet(filepath) for filepath in all_files], ignore_index=True
    )
    df = df.drop_duplicates(subset="student_id", keep="last")
    logger.info("Unique students after deduplication: %d", len(df))
    return df


def _build_feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    """
    Select CLUSTER_FEATURES from the DataFrame, cast types, and impute nulls.

    Columns present in CLUSTER_FEATURES but entirely null (median = NaN) are
    dropped rather than imputed, since filling with zero would introduce noise.
    A final fillna(0) serves as a safety net for any remaining isolated nulls.
    """
    available_columns = [col for col in CLUSTER_FEATURES if col in df.columns]
    feature_matrix = df[available_columns].copy()

    # Cast boolean columns to integer so they are treated as numeric
    bool_columns = feature_matrix.select_dtypes(include="bool").columns
    feature_matrix[bool_columns] = feature_matrix[bool_columns].astype(int)

    # Coerce all remaining columns to float, turning non-numeric values into NaN
    feature_matrix = feature_matrix.apply(pd.to_numeric, errors="coerce")

    # Impute with column median; drop columns that are 100% null (median is NaN)
    columns_to_drop = []
    for column_name in feature_matrix.columns:
        column_median = feature_matrix[column_name].median()

        if np.isnan(column_median):
            logger.warning(
                "Column '%s' is entirely null — dropping from feature set", column_name
            )
            columns_to_drop.append(column_name)
        else:
            feature_matrix[column_name] = feature_matrix[column_name].fillna(
                column_median
            )

    if columns_to_drop:
        feature_matrix = feature_matrix.drop(columns=columns_to_drop)

    # Safety net: fill any remaining isolated nulls with zero
    remaining_nulls = feature_matrix.isnull().sum().sum()
    if remaining_nulls:
        logger.warning(
            "Filling %d remaining null values with 0 (safety net)", remaining_nulls
        )
        feature_matrix = feature_matrix.fillna(0)

    logger.info("Feature matrix shape: %s", feature_matrix.shape)
    return feature_matrix


def _compute_risk_scores(
    df: pd.DataFrame,
    cluster_labels: np.ndarray,
) -> np.ndarray:
    """
    Compute a risk score (0–100) for each student based on the historical dropout
    rate of their assigned cluster.

    If `target_evasao` is available in the DataFrame, the score equals the mean
    dropout rate of the cluster multiplied by 100 (e.g. cluster with 21% evasion
    → risk_score 21.0). Otherwise, a normalized cluster index is used as fallback.
    """
    if "target_evasao" in df.columns:
        unique_cluster_ids = np.unique(cluster_labels)
        dropout_rate_by_cluster = {
            cluster_id: df["target_evasao"][cluster_labels == cluster_id].mean()
            for cluster_id in unique_cluster_ids
        }
        logger.info("Average dropout rate by cluster: %s", dropout_rate_by_cluster)
        risk_scores = (
            np.array(
                [dropout_rate_by_cluster.get(label, 0.0) for label in cluster_labels]
            )
            * 100
        )
    else:
        logger.warning(
            "Column 'target_evasao' not found — using normalized cluster index as fallback"
        )
        max_label = max(cluster_labels.max(), 1)
        risk_scores = (cluster_labels / max_label) * 100

    return risk_scores.round(1)


def _log_cluster_summary(cluster_labels: np.ndarray, risk_scores: np.ndarray) -> None:
    """Log a per-cluster summary of student count and average risk score."""
    for cluster_id in np.unique(cluster_labels):
        cluster_mask = cluster_labels == cluster_id
        student_count = cluster_mask.sum()
        avg_risk = risk_scores[cluster_mask].mean()
        logger.info(
            "  Cluster %d: %d students, avg risk_score=%.1f",
            cluster_id,
            student_count,
            avg_risk,
        )


def _run_risk_clustering() -> None:
    """Airflow task entry point — orchestrates load → cluster → writeback."""

    data_dir = Path(__file__).parents[1] / "src/ml/data/raw"

    # Step 1: load raw student data
    df = _load_students(data_dir)

    # Step 2: build feature matrix (select, cast, impute)
    feature_matrix = _build_feature_matrix(df)

    # Step 3: fit KMeans with automatic k selection (k=3..8, PCA 95% variance)
    model, cluster_labels, silhouette, best_k = fit_risk_clusters(
        feature_matrix, k_range=(3, 8), pca_variance=0.95
    )
    logger.info("Best k=%d (silhouette=%.4f)", best_k, silhouette)

    # Step 4: compute per-student risk scores from cluster dropout rates
    risk_scores = _compute_risk_scores(df, cluster_labels)
    _log_cluster_summary(cluster_labels, risk_scores)

    # Step 5: write risk_cluster + risk_score back to Neo4j Student nodes
    neo4j_uri = os.getenv("NEO4J_URI", "bolt://host.docker.internal:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "neo4jtia")

    driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))
    student_ids = df["student_id"].astype(str).tolist()

    logger.info("Writing %d cluster records to Neo4j...", len(student_ids))
    write_clusters_to_neo4j(
        driver, student_ids, cluster_labels, risk_scores, batch_size=500
    )
    driver.close()

    logger.info(
        "Done — risk_cluster and risk_score written for %d students.",
        len(student_ids),
    )


with DAG(
    dag_id="dag__ml_risk_clustering",
    default_args=default_args,
    description="Student risk clustering (KMeans) — writes risk_cluster + risk_score to Neo4j Student nodes",
    schedule=None,  # Manual trigger only — use Airflow UI
    catchup=False,
    tags=["ml", "clustering", "neo4j", "rag"],
) as dag:

    run_clustering = PythonOperator(
        task_id="run_risk_clustering",
        python_callable=_run_risk_clustering,
    )

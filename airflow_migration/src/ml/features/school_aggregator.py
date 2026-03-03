# src/ml/features/school_aggregator.py
"""
School-level feature aggregation from student-level DataFrames.

Receives the output of Neo4jExtractor.extract_school_features() and computes
derived school-level metrics: health score, risk level, BF concentration,
attendance coverage flag, grade quality flag.

This module is used by:
- PLAN-ML-02-RAG-LLM.md: school text serialization for embedding
- PLAN-ML-03-API-SERVING.md: /report/school/{id} endpoint
- risk_clusterer.py: school context for cluster interpretation

Design:
- No I/O — pure DataFrame transformation.
- No Cypher — calls nothing, writes nothing.
- Health score formula mirrors Q_SAUDE_ESCOLA_E_PROXIMIDADE.md (simplified
  2-component version; full 4-component version is in the RAG retriever).
- All derived columns use explicit formulas in docstrings for reproducibility.
"""
import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Thresholds for flag and level derivation
_AUSENCIA_CRITICA_PCT = 15.0      # % absence above which school is flagged
_NOTA_CRITICA_PCT     = 40.0      # % failing grades above which school is flagged
_MIN_ALUNOS           = 10        # minimum students to compute school metrics


def compute_school_metrics(df_school: pd.DataFrame) -> pd.DataFrame:
    """
    Compute derived metrics for each school from the raw aggregated DataFrame.

    Input columns expected (from Neo4jExtractor.extract_school_features()):
        school_id, school_name, municipio, uf, n_alunos,
        n_com_diario, taxa_ausencia_pct, n_notas, media_nota_escola,
        pct_abaixo5, n_com_saude, n_desnutridos, n_bolsa_familia, n_pcd,
        muni_freq_liq_fund, muni_analf_adulto, est_ideb_af, est_taxa_abandono,
        est_taxa_reprovacao.

    Derived columns added:
        score_saude (float 0–100): simplified health score (attendance 50% + grade 50%)
        nivel_saude (str): 'critico' | 'alerta' | 'moderado' | 'adequado'
        pct_bolsa_familia (float): % BF students
        pct_pcd (float): % PCD students
        pct_desnutridos (float): % malnourished students (among those with health record)
        flag_sem_diario (bool): school has no electronic attendance journal
        flag_sem_notas (bool): school has no registered grades
        flag_alta_ausencia (bool): taxa_ausencia_pct > 15%
        flag_nota_critica (bool): pct_abaixo5 > 40%
        data_quality (str): 'completo' | 'sem_diario' | 'sem_notas' | 'parcial'

    Args:
        df_school: Raw school features DataFrame from extract_school_features().

    Returns:
        DataFrame with all derived columns added. Schools with < _MIN_ALUNOS
        students are retained but flagged implicitly by low n_alunos.
    """
    df = df_school.copy()

    # ── Social concentration ratios ───────────────────────────────────────────
    df["pct_bolsa_familia"] = np.where(
        df["n_alunos"] > 0,
        (df["n_bolsa_familia"] / df["n_alunos"] * 100).round(1),
        np.nan,
    )
    df["pct_pcd"] = np.where(
        df["n_alunos"] > 0,
        (df["n_pcd"] / df["n_alunos"] * 100).round(1),
        np.nan,
    )
    df["pct_desnutridos"] = np.where(
        df["n_com_saude"] > 0,
        (df["n_desnutridos"] / df["n_com_saude"] * 100).round(1),
        np.nan,
    )

    # ── Flags ─────────────────────────────────────────────────────────────────
    df["flag_sem_diario"]    = df["n_com_diario"] == 0
    df["flag_sem_notas"]     = df["n_notas"] == 0
    df["flag_alta_ausencia"] = df["taxa_ausencia_pct"].fillna(0) > _AUSENCIA_CRITICA_PCT
    df["flag_nota_critica"]  = df["pct_abaixo5"].fillna(0)      > _NOTA_CRITICA_PCT

    # ── Data quality label ────────────────────────────────────────────────────
    df["data_quality"] = np.select(
        [
            (~df["flag_sem_diario"]) & (~df["flag_sem_notas"]),
            df["flag_sem_diario"]   & (~df["flag_sem_notas"]),
            (~df["flag_sem_diario"]) & df["flag_sem_notas"],
        ],
        ["completo", "sem_diario", "sem_notas"],
        default="parcial",
    )

    # ── Simplified health score (2-component) ────────────────────────────────
    # Full 4-component version: Q_SAUDE_ESCOLA_E_PROXIMIDADE.md
    # This version is used for quick school embedding text and API reports.
    # Component 1 (50%): attendance — 0% absence = 50pts, ≥25% = 0pts
    # Component 2 (50%): grade quality — avg 10 = 50pts, avg 0 = 0pts
    ausencia     = df["taxa_ausencia_pct"].fillna(0.0)
    media_nota   = df["media_nota_escola"].fillna(5.0)
    score_ausencia = (np.maximum(0, 25.0 - ausencia) / 25.0 * 50).round(1)
    score_nota     = (media_nota / 10.0 * 50).round(1)
    df["score_saude"] = (score_ausencia + score_nota).round(1)

    # ── Health level label ────────────────────────────────────────────────────
    df["nivel_saude"] = pd.cut(
        df["score_saude"],
        bins=[-1, 25, 45, 70, 101],
        labels=["critico", "alerta", "moderado", "adequado"],
        right=True,
    ).astype(str)

    logger.info(
        "School metrics computed: %d schools | %d sem_diario | %d sem_notas | "
        "%d critico | %d adequado",
        len(df),
        df["flag_sem_diario"].sum(),
        df["flag_sem_notas"].sum(),
        (df["nivel_saude"] == "critico").sum(),
        (df["nivel_saude"] == "adequado").sum(),
    )
    return df


def serialize_for_embedding(row: pd.Series) -> str:
    """
    Serialize a school's metrics as a text string for sentence-transformer embedding.

    The format mirrors the school embedding described in PLAN-ML-01 §5.1 and
    consumed by PLAN-ML-02-RAG-LLM.md (school_embedder.py).

    Args:
        row: A single row from compute_school_metrics() output.

    Returns:
        Text string ready for sentence-transformers encode().
    """
    ausencia  = f"{row.get('taxa_ausencia_pct', 'N/A')}%"
    nota      = f"{row.get('media_nota_escola', 'N/A')}"
    bf_pct    = f"{row.get('pct_bolsa_familia', 'N/A')}%"
    score     = row.get("score_saude", "N/A")
    nivel     = row.get("nivel_saude", "N/A")
    ibge_freq = row.get("muni_freq_liq_fund", "N/A")
    ideb      = row.get("est_ideb_af", "N/A")
    abandono  = row.get("est_taxa_abandono", "N/A")

    return (
        f"Escola: UF {row.get('uf', 'N/A')}, "
        f"município {row.get('municipio', 'N/A')}, "
        f"saúde {nivel} (score {score}), "
        f"ausência {ausencia}, nota média {nota}, "
        f"Bolsa Família {bf_pct}, "
        f"IBGE freq_liq {ibge_freq}, "
        f"IDEB EF-AF {ideb}, abandono {abandono}%"
    )

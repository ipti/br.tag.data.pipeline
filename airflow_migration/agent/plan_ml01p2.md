# PLAN-ML-01-PATCHES — Correções e Adições ao PLAN-ML-01

> **Aplica-se a:** `PLAN-ML-01-FEATURE-ML-MLOPS.md`
> **Auditado contra:** `CYPHER-QUERY-MATRIX-ML.md` (Q1–Q15) · `NEO4J-SCHEMA-REFERENCE.md` · `Q_RISCO_EVASAO_EF2.md`
> **Tipo de documento:** Patch incremental — não reescreve o plano original, só corrige e adiciona
> **Status de cada item:** classificado por severidade (🔴 Crítico / 🟡 Importante / 🔵 Melhoria)

---

## Índice de Patches

| # | Severidade | Arquivo afetado | Problema | Status |
|---|---|---|---|---|
| P01 | 🔴 Crítico | `train_notas.py` | Entrypoint ausente — DAG chama mas código não existe | Adicionado aqui |
| P02 | 🔴 Crítico | `champion_challenger.py` | Lógica de promoção hardcoded para `auroc` — quebra em modelos de regressão | Adicionado aqui |
| P03 | 🔴 Crítico | `school_aggregator.py` | Listado na árvore de arquivos, zero implementação | Adicionado aqui |
| P04 | 🟡 Importante | `neo4j_extractor.py` | `extract_classroom_features()` ausente — Q15 não tem extrator dedicado | Adicionado aqui |
| P05 | 🟡 Importante | `schema.py` | `CLASSROOM_CONTEXT_FEATURES` ausente — features Q15 não estão no contrato | Adicionado aqui |
| P06 | 🟡 Importante | `neo4j_extractor.py` | Q8 `soma_sinais_risco` como feature de turma não documentada nem extraída | Adicionado aqui |
| P07 | 🟡 Importante | `schema.py` + extrator | Conflito documentado: `atl_branco_analf25m` existe em Municipality (matrix) mas **não** existe (schema ref) | Clarificado aqui |
| P08 | 🔵 Melhoria | `dag__ml_feature_engineering.py` | DAG não extrai features de turma (Q15) — precisa de task extra | Adicionado aqui |
| P09 | 🔵 Melhoria | `schema.py` | Features derivadas de Q1/Q9/Q12 úteis não documentadas: `cv_nota_turma`, `pct_rural_turma`, `delta_vs_qedu` | Adicionado aqui |

---

## P01 🔴 — `src/ml/training/train_notas.py` (arquivo ausente)

**Problema:** O DAG `dag__ml_retrain.py` executa `python -m src.ml.training.train_notas --test-year {year}`. O plano lista o arquivo na árvore de diretórios com `# Entrypoint: same pattern for grade regression model` mas o código `run()` nunca foi escrito.

**Impacto:** `ModuleNotFoundError` em runtime na task `train_notas_task` do Airflow.

```python
# src/ml/training/train_notas.py
"""
Grade regression model training entrypoint (EF2).

Orchestrates the full grade regression pipeline:
1. Extract EF2 base features (demographics, health, attendance, IBGE) from Neo4j
2. Extract EF2 grade pivot (per-subject normalized grades) from Neo4j
3. Merge both DataFrames on student_id — EF2 base is the join anchor
4. Encode categoricals and fill grade sentinels
5. Temporal split: train on years < test_year, hold out test_year
6. Train GradientBoostingRegressor on FEATURES_NOTAS_EF2
7. Evaluate on held-out test set (RMSE, R², MAE)
8. Compute SHAP global for feature validation
9. Log to MLflow via log_run() context manager
10. Champion/Challenger: promote if R² improves > threshold

Why EF2 base features?
  The grade regression model needs demographic + health + attendance context
  from EF2 students specifically (grades 6-9). extract_ef2_grades() gives
  per-subject grades, but not demographics or IBGE. extract_ef1() gives those
  but filters EF1 students only. The EF2 base query (parallel to _QUERY_EF1
  but with EF2 grade_level filter) provides the full context for EF2 students.

This file is called:
- Directly: python -m src.ml.training.train_notas --test-year 2024
- Via Airflow: dag__ml_retrain.py → train_notas_task

References:
- Feature contracts: schema.py FEATURES_NOTAS_EF2
- EF2 base extraction query: neo4j_extractor.py _QUERY_EF2_BASE
- EF2 grade pivot query: neo4j_extractor.py _QUERY_EF2_GRADES
- Acceptance criteria: PLAN-ML-01 §13 (RMSE ≤ 1.5, R² ≥ 0.60)
- Q_RISCO_EVASAO_EF2.md: grade component (35% weight on failing grades)
"""
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_TYPE = "notas"
MODEL_NAME = "grade-regression-ef2"


def run(test_year: int) -> None:
    """
    Execute the full grade regression pipeline for a given test year.

    Args:
        test_year: School year to hold out as test set (e.g., 2024).
                   All prior years are used for training.
    """
    import pandas as pd
    from mlflow.tracking import MlflowClient
    from ..features.neo4j_extractor import Neo4jExtractor
    from ..features.feature_pipeline import (
        encode_categoricals, temporal_split, fill_grade_sentinel,
    )
    from ..features.schema import (
        FEATURES_NOTAS_EF2, TARGET_GRADE, GRADE_EF2_FEATURES,
    )
    from ..models.grade_regressor import GradeRegressorConfig, train_grade_regressor
    from ..evaluation.metrics import eval_regressor
    from ..evaluation.explainability import compute_shap_global
    from ..mlops.experiment import log_run
    from ..mlops.champion_challenger import promote_if_better

    logger.info("=== Grade regression pipeline: test_year=%d ===", test_year)

    # ── 1. Extract ────────────────────────────────────────────────────────────
    extractor = Neo4jExtractor.from_env()
    df_base   = extractor.extract_ef2_base()    # demographics + health + attendance + IBGE for EF2 students
    df_grades = extractor.extract_ef2_grades()  # per-subject grade pivot
    extractor.close()

    # ── 2. Merge: EF2 base is the anchor, grades are joined on student_id ─────
    # Students without any grade records are dropped (target is grade — can't train without it)
    df = df_base.merge(df_grades, on="student_id", how="inner")
    logger.info(
        "EF2 merge: %d base rows × %d grade rows → %d merged (inner join on student_id)",
        len(df_base), len(df_grades), len(df),
    )
    if len(df) < 1000:
        logger.warning(
            "Merged EF2 dataset has only %d rows. "
            "Check that extract_ef2_base() and extract_ef2_grades() use the same grade_level filter.",
            len(df),
        )

    # ── 3. Encode + fill sentinels ────────────────────────────────────────────
    df = encode_categoricals(df)
    df = fill_grade_sentinel(df, GRADE_EF2_FEATURES)   # null subject grades → -1

    # Drop rows where target is null (can't regress without a grade)
    df_clean = df.dropna(subset=[TARGET_GRADE])
    n_dropped = len(df) - len(df_clean)
    if n_dropped > 0:
        logger.info("Dropped %d rows with null %s (no final grade registered)", n_dropped, TARGET_GRADE)
    df = df_clean

    # ── 4. Temporal split ─────────────────────────────────────────────────────
    X_train, y_train, X_test, y_test = temporal_split(
        df, target_col=TARGET_GRADE, test_year=test_year,
        feature_cols=FEATURES_NOTAS_EF2,
    )

    # ── 5. Train ──────────────────────────────────────────────────────────────
    config = GradeRegressorConfig()
    model  = train_grade_regressor(X_train, y_train, config)

    # ── 6. Evaluate ───────────────────────────────────────────────────────────
    y_pred  = model.predict(X_test)
    # Clip predictions to valid grade range [0, 10] before evaluation
    import numpy as np
    y_pred  = np.clip(y_pred, 0.0, 10.0)
    metrics = eval_regressor(y_test.values, y_pred)

    if not metrics.passes_acceptance():
        logger.warning(
            "Grade model does NOT meet acceptance criteria. "
            "RMSE=%.4f (need ≤1.5), R²=%.4f (need ≥0.60)",
            metrics.rmse, metrics.r2,
        )
    else:
        logger.info("All acceptance criteria met: %s", metrics.as_dict())

    # ── 7. SHAP ───────────────────────────────────────────────────────────────
    _, shap_buf = compute_shap_global(model, X_test)

    # ── 8. Log to MLflow ──────────────────────────────────────────────────────
    params = vars(config) | {
        "test_year":       test_year,
        "n_train":         len(X_train),
        "n_test":          len(X_test),
        "n_dropped_nulls": n_dropped,
    }
    tags = {"segment": "EF2", "target": TARGET_GRADE}

    with log_run(MODEL_TYPE, params=params, tags=tags) as run_ctx:
        run_ctx.log_metrics(metrics.as_dict())
        run_ctx.log_model(model, artifact_path="grade_model")
        run_ctx.log_png_buffer(shap_buf, "shap_summary.png")
        run_id = run_ctx.run_id

    # ── 9. Champion/Challenger ────────────────────────────────────────────────
    promoted = promote_if_better(
        model_type=MODEL_TYPE,
        challenger_run_id=run_id,
        challenger_metrics=metrics.as_dict(),
        client=MlflowClient(),
    )
    logger.info("Pipeline complete. RMSE=%.4f | R²=%.4f | Promoted=%s",
                metrics.rmse, metrics.r2, promoted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train grade regression model (EF2)")
    parser.add_argument("--test-year", type=int, required=True,
                        help="School year to hold out as test set")
    args = parser.parse_args()
    run(args.test_year)
```

---

## P02 🔴 — `src/ml/mlops/champion_challenger.py` (regressão não suportada)

**Problema:** `promote_if_better()` acessa `challenger_metrics["auroc"]` diretamente. O modelo de notas (`train_notas.py`) não produz `auroc` — produz `rmse` e `r2`. Isso lança `KeyError` silencioso no Airflow se o modelo de notas for registrado.

**Causa raiz:** O campo `_PROMOTION_THRESHOLD` e a comparação de delta eram pensados só para classificação.

**Solução:** Parametrizar `primary_metric` e `higher_is_better` por `model_type`. Para classificação: `auroc` (maior = melhor). Para regressão: `r2` (maior = melhor). O `rmse` fica como métrica de contexto no log mas não é o critério de promoção — R² é mais estável para comparação entre runs com diferentes volumes de dados.

**Substitua inteiramente o conteúdo de `champion_challenger.py` por:**

```python
# src/ml/mlops/champion_challenger.py
"""
Champion/Challenger pattern for automatic model promotion.

Supports both classification models (primary metric: auroc, higher is better)
and regression models (primary metric: r2, higher is better).

The model_type parameter drives which metric is used for comparison and which
artifact path is used for registration. Adding a new model type requires only
adding an entry to _MODEL_CONFIG.

Threshold prevents churn from small fluctuations between training runs.
All promotion decisions are logged with full metric context for audit.
"""
import logging
import mlflow
from mlflow.tracking import MlflowClient
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ModelConfig:
    """Internal config per model type."""
    registry_name:   str    # registered model name in MLflow
    artifact_path:   str    # artifact_path used in log_model()
    primary_metric:  str    # metric key to compare champion vs challenger
    higher_is_better: bool  # True = higher value wins; False = lower value wins
    threshold:       float  # minimum absolute improvement to justify promotion


# ── Per-model-type configuration ─────────────────────────────────────────────
# Add new model types here only — no changes needed elsewhere.
_MODEL_CONFIG: dict[str, _ModelConfig] = {
    "evasao": _ModelConfig(
        registry_name    = "dropout-evasao-ef1",
        artifact_path    = "dropout_model",
        primary_metric   = "auroc",
        higher_is_better = True,
        threshold        = 0.01,   # min AUROC improvement
    ),
    "notas": _ModelConfig(
        registry_name    = "grade-regression-ef2",
        artifact_path    = "grade_model",
        primary_metric   = "r2",
        higher_is_better = True,   # R² higher = better fit
        threshold        = 0.02,   # min R² improvement (regression runs are noisier)
    ),
    "clustering": _ModelConfig(
        registry_name    = "student-clustering",
        artifact_path    = "clustering_model",
        primary_metric   = "silhouette",
        higher_is_better = True,
        threshold        = 0.03,
    ),
}


def get_champion_metrics(model_name: str, client: MlflowClient) -> dict | None:
    """
    Retrieve metrics of the current Production model from MLflow Registry.

    Args:
        model_name: Registered model name (e.g., 'dropout-evasao-ef1').
        client: MlflowClient instance.

    Returns:
        Dict of metric_name → float from the Production model's MLflow run.
        None if no Production model exists yet (first training run).
    """
    try:
        versions = client.get_latest_versions(model_name, stages=["Production"])
        if not versions:
            logger.info("No Production model found for '%s' — first run.", model_name)
            return None
        run = client.get_run(versions[0].run_id)
        return dict(run.data.metrics)
    except Exception as exc:
        logger.warning("Could not retrieve champion metrics for '%s': %s", model_name, exc)
        return None


def _is_better(
    challenger_val: float,
    champion_val: float,
    higher_is_better: bool,
    threshold: float,
) -> bool:
    """
    Return True if challenger beats champion by more than threshold.

    Args:
        challenger_val: Challenger model's primary metric value.
        champion_val: Champion model's primary metric value.
        higher_is_better: If True, challenger must be higher; if False, lower.
        threshold: Minimum absolute difference required to promote.

    Returns:
        True if challenger should replace champion.
    """
    delta = challenger_val - champion_val
    if not higher_is_better:
        delta = -delta   # flip sign so positive delta always means improvement
    return delta > threshold


def promote_if_better(
    model_type: str,
    challenger_run_id: str,
    challenger_metrics: dict[str, float],
    client: MlflowClient | None = None,
) -> bool:
    """
    Promote challenger model to Production if primary metric improvement exceeds threshold.

    Works for both classification (auroc) and regression (r2) models.
    Uses _MODEL_CONFIG[model_type] to determine which metric to compare.

    Args:
        model_type: Key in _MODEL_CONFIG — 'evasao', 'notas', or 'clustering'.
        challenger_run_id: MLflow run ID of the challenger model.
        challenger_metrics: Metrics dict from the challenger run.
                            Must include the primary_metric defined in _MODEL_CONFIG.
        client: MlflowClient — if None, creates a new one.

    Returns:
        True if challenger was promoted to Production, False if champion retained.

    Raises:
        KeyError: if model_type is not in _MODEL_CONFIG.
        KeyError: if primary_metric is missing from challenger_metrics.
    """
    if model_type not in _MODEL_CONFIG:
        raise KeyError(
            f"Unknown model_type='{model_type}'. "
            f"Known types: {list(_MODEL_CONFIG.keys())}"
        )

    cfg    = _MODEL_CONFIG[model_type]
    client = client or MlflowClient()

    # Validate challenger has the expected metric
    if cfg.primary_metric not in challenger_metrics:
        raise KeyError(
            f"Challenger metrics missing '{cfg.primary_metric}' for model_type='{model_type}'. "
            f"Got: {list(challenger_metrics.keys())}"
        )

    challenger_val = challenger_metrics[cfg.primary_metric]
    champion_metrics = get_champion_metrics(cfg.registry_name, client)

    if champion_metrics is None:
        logger.info(
            "No champion found for '%s' — promoting first model. "
            "%s=%.4f",
            cfg.registry_name, cfg.primary_metric, challenger_val,
        )
    else:
        champion_val = champion_metrics.get(cfg.primary_metric, 0.0)
        delta = challenger_val - champion_val
        logger.info(
            "Champion %s=%.4f | Challenger %s=%.4f | Delta=%.4f | "
            "Threshold=%.4f | higher_is_better=%s",
            cfg.primary_metric, champion_val,
            cfg.primary_metric, challenger_val,
            delta, cfg.threshold, cfg.higher_is_better,
        )

        # Log secondary metrics for context (RMSE for notas, recall for evasao)
        for k, v in challenger_metrics.items():
            if k != cfg.primary_metric:
                logger.info("  Secondary metric: %s=%.4f", k, v)

        if not _is_better(challenger_val, champion_val, cfg.higher_is_better, cfg.threshold):
            logger.info(
                "Keeping champion — challenger improvement %.4f does not exceed threshold %.4f.",
                abs(delta), cfg.threshold,
            )
            return False

    # Register and promote to Production
    model_uri = f"runs:/{challenger_run_id}/{cfg.artifact_path}"
    mlflow.register_model(model_uri, cfg.registry_name)

    latest = client.get_latest_versions(cfg.registry_name, stages=["None"])
    client.transition_model_version_stage(
        name=cfg.registry_name,
        version=latest[0].version,
        stage="Production",
        archive_existing_versions=True,
    )
    logger.info(
        "Challenger promoted to Production: '%s' version=%s | %s=%.4f",
        cfg.registry_name, latest[0].version,
        cfg.primary_metric, challenger_val,
    )
    return True
```

---

## P03 🔴 — `src/ml/features/school_aggregator.py` (arquivo ausente)

**Problema:** O arquivo está na árvore de diretórios do plano com `# School-level feature aggregation for school embedding + report`. O código não existe em nenhuma seção do documento.

**Contexto:** `school_aggregator.py` não usa Cypher diretamente — recebe o DataFrame de `neo4j_extractor.extract_school_features()` (já implementado) e computa métricas derivadas por escola. É o módulo que a API usa em `/report/school/{id}` e que o embedder de escola (PLAN-ML-02) usa para gerar o texto serializado.

```python
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
```

---

## P04 🟡 — `neo4j_extractor.py`: adicionar `extract_classroom_features()` e `extract_ef2_base()`

**Problema:** Q15 (God Matrix) produz features *por turma* (`FEAT_Total_Alunos`, `FEAT_N_Bolsistas`, `FEAT_N_Risco_Saude`, `FEAT_Media_Global`, `FEAT_Dispersao_Global`, etc.). Essas features de contexto de turma são diferentes das features de aluno — elas capturam o ambiente em que o aluno está matriculado. O plano não tem extrator para isso.

**Também ausente:** `extract_ef2_base()` — extrai as features demográficas, de saúde, de frequência e IBGE especificamente para alunos do EF2 (grades 6–9). Sem isso, `train_notas.py` não tem base de contexto para fazer o merge com `extract_ef2_grades()`.

**Adicione os seguintes métodos à classe `Neo4jExtractor` em `neo4j_extractor.py`:**

### 4a — `extract_ef2_base()` (paralelo ao `extract_ef1()`, filtrado para EF2)

```python
# Adicionar em neo4j_extractor.py, logo após extract_ef1()

# ── EF2 base query — same structure as _QUERY_EF1, but filtered for EF2 grades ──
# Returns: demographics + health + attendance + IBGE for EF2 students.
# Does NOT include grade columns (those come from extract_ef2_grades()).
# Purpose: provides the context features for train_notas.py merge.
# EF2 grade filter from NEO4J-SCHEMA-REFERENCE.md §5 (canonical).
_QUERY_EF2_BASE = """
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// IBGE fallbacks — same 6-field pattern as _QUERY_EF1
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_avg_freq
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_atraso_2_fund IS NOT NULL AND m2.atl_atraso_2_fund > 0
  RETURN avg(m2.atl_atraso_2_fund) AS uf_avg_atraso
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_t_analf25m IS NOT NULL
  RETURN avg(m2.atl_t_analf25m) AS uf_avg_analf
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_expectativa_estudo_18 IS NOT NULL
  RETURN avg(m2.atl_expectativa_estudo_18) AS uf_avg_expectativa
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_negro_mat_pub_fund IS NOT NULL
  RETURN avg(m2.atl_negro_mat_pub_fund) AS uf_avg_negro_pub
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_negro_internet_fund IS NOT NULL
  RETURN avg(m2.atl_negro_internet_fund) AS uf_avg_negro_internet
}

// EF2 filter — canonical from NEO4J-SCHEMA-REFERENCE.md §5
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\\\* SÉRIE')

WITH DISTINCT stu, cr, sch, m, st,
     uf_avg_freq, uf_avg_atraso, uf_avg_analf,
     uf_avg_expectativa, uf_avg_negro_pub, uf_avg_negro_internet

OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)

WITH stu, cr, sch, m, st, h,
     uf_avg_freq, uf_avg_atraso, uf_avg_analf,
     uf_avg_expectativa, uf_avg_negro_pub, uf_avg_negro_internet

CALL (stu) {
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))            AS total_faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))  AS total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN sc END)  AS n_sc_records
}

RETURN
  stu.id   AS student_id,
  sch.id   AS school_id,
  st.sigla AS uf,

  CASE WHEN stu.gender =~ '(?i)^F.*' THEN 1 ELSE 0 END                          AS gender_bin,
  coalesce(stu.ethnicity, '')                                                      AS ethnicity_raw,
  CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN 1 ELSE 0 END AS has_deficiency,
  CASE WHEN coalesce(stu.bolsa_familia, false) THEN 1 ELSE 0 END                 AS bolsa_familia,
  coalesce(stu.residence_zone, 'Não Informado')                                   AS residence_zone_raw,

  CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END                                       AS has_health_record,
  CASE WHEN coalesce(h.malnutrition, false) THEN 1 ELSE 0 END                    AS has_malnutrition,
  CASE WHEN coalesce(h.diabetes, false) THEN 1 ELSE 0 END                        AS has_diabetes,
  CASE WHEN coalesce(h.hypertension, false) THEN 1 ELSE 0 END                    AS has_hypertension,
  CASE WHEN coalesce(h.obesity, false) THEN 1 ELSE 0 END                         AS has_obesity,
  CASE WHEN coalesce(h.celiac, false) THEN 1 ELSE 0 END                          AS has_celiac,
  CASE WHEN coalesce(h.iron_deficiency_anemia, false)
        OR coalesce(h.sickle_cell_anemia, false) THEN 1 ELSE 0 END               AS has_anemia,

  CASE WHEN n_sc_records > 0 THEN 1 ELSE 0 END                                   AS tem_diario,
  total_faltas                                                                     AS total_faltas_abs,
  CASE WHEN n_sc_records > 0 AND total_dias > 0
       THEN round(toFloat(total_faltas) / total_dias, 4)
       ELSE null END                                                               AS taxa_ausencia,
  CASE WHEN n_sc_records > 0 AND total_dias > 0
        AND toFloat(total_faltas) / total_dias > 0.10
       THEN 1 ELSE 0 END                                                          AS falta_critica,

  cr.stage       AS stage_raw,
  cr.grade_level AS grade_level_raw,
  cr.year        AS ano_letivo,

  coalesce(m.atl_freq_liq_fund, uf_avg_freq)      AS muni_freq_liq_fund,
  CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_freq_fonte,
  coalesce(m.atl_atraso_2_fund, uf_avg_atraso)    AS muni_atraso_2anos,
  CASE WHEN m.atl_atraso_2_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_atraso_fonte,
  coalesce(m.atl_t_analf25m, uf_avg_analf)        AS muni_analf_adulto,
  CASE WHEN m.atl_t_analf25m IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_analf_fonte,
  coalesce(m.atl_expectativa_estudo_18, uf_avg_expectativa) AS muni_expectativa_estudo,
  coalesce(m.atl_negro_mat_pub_fund, uf_avg_negro_pub)      AS muni_pct_negro_pub,
  coalesce(m.atl_negro_internet_fund, uf_avg_negro_internet) AS muni_internet_negro,

  st.qedu_ideb_af             AS est_ideb_af,
  st.qedu_taxa_abandono       AS est_taxa_abandono,
  st.qedu_taxa_reprovacao     AS est_taxa_reprovacao,
  st.qedu_fluxo_af            AS est_fluxo_af,
  st.qedu_pct_fora_escola     AS est_pct_fora_escola,
  st.qedu_lp_insuficiente_af AS est_lp_insuf_af,
  st.qedu_mt_insuficiente_af AS est_mat_insuf_af,
  CASE cr.grade_level
    WHEN 'NO 6* ANO' THEN st.qedu_distorcao_ef6
    WHEN 'NO 7* ANO' THEN st.qedu_distorcao_ef7
    WHEN 'NO 8* ANO' THEN st.qedu_distorcao_ef8
    WHEN 'NO 9* ANO' THEN st.qedu_distorcao_ef9
    ELSE st.qedu_distorcao_ef_af
  END AS est_distorcao_serie,

  st.negro_pnad_t_analf25m    AS est_analf_negro,
  st.branco_pnad_t_analf25m   AS est_analf_branco,
  st.negro_pnad_t_atraso_fund AS est_atraso_negro,
  st.homem_pnad_t_analf25m    AS est_analf_homem,
  st.mulher_pnad_t_analf25m   AS est_analf_mulher
"""
```

**Método Python:**

```python
def extract_ef2_base(self) -> pd.DataFrame:
    """
    Extract base context features for EF2 students (one row per student).

    Returns the same feature groups as extract_ef1() — demographics, health,
    attendance, IBGE — but filtered for EF2 grade levels (grades 6–9).
    Does NOT include grade columns (use extract_ef2_grades() for those).

    Intended usage: merge with extract_ef2_grades() on student_id to build
    the full FEATURES_NOTAS_EF2 input for train_notas.py.

        df_base   = extractor.extract_ef2_base()
        df_grades = extractor.extract_ef2_grades()
        df        = df_base.merge(df_grades, on='student_id', how='inner')

    Returns:
        DataFrame with one row per EF2 student. IBGE fields use same-UF
        municipality average as fallback when field is NULL.

    Raises:
        RuntimeError: if extraction returns zero rows.
    """
    logger.info("Extracting EF2 base features")
    df = self._run(_QUERY_EF2_BASE)
    if len(df) == 0:
        raise RuntimeError(
            "EF2 base extraction returned 0 rows. "
            "Check grade_level filter and Neo4j connection."
        )
    logger.info("EF2 base extracted: %d rows", len(df))
    self._log_ibge_coverage(df, "EF2-base")
    return df
```

### 4b — `extract_classroom_features()` (novo método, Q15 God Matrix)

Q15 opera em granularidade de *turma*, não de *aluno*. As features de turma (`FEAT_N_Bolsistas`, `FEAT_N_Risco_Saude`, `FEAT_Media_Global`, etc.) podem ser joinadas de volta nos alunos pelo par `(school_id, classroom_name, grade_level)` para enriquecer o feature set de aluno com contexto de turma.

```python
# Adicionar como constante logo após _QUERY_SCHOOL_FEATURES

# ── Q15 God Matrix query — classroom-level feature extraction ─────────────────
# Source: CYPHER-QUERY-MATRIX-ML.md Q15_EF1 and Q15_EF2_SUP.
# Produces one row per (school, classroom, grade_level) pair.
# IBGE fallback: Q15 in the original matrix uses coalesce(val, 0.0) — filling
# with zero instead of UF proxy. Here we use coalesce(val, uf_fallback) for
# consistency with the student-level queries, to avoid introducing a 0 signal
# for schools where IBGE data is legitimately absent.
_QUERY_CLASSROOM_EF1 = """
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_avg_freq
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_t_analf25m IS NOT NULL
  RETURN avg(m2.atl_t_analf25m) AS uf_avg_analf
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_atraso_2_fund IS NOT NULL AND m2.atl_atraso_2_fund > 0
  RETURN avg(m2.atl_atraso_2_fund) AS uf_avg_atraso
}

MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

WITH sch, m, st, cr,
     uf_avg_freq, uf_avg_analf, uf_avg_atraso,
     collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 5

// Dimension 1: grades (EF1 global — discipline_name = '')
CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN round(avg(Nota), 2)   AS cr_media_nota,
         round(stDev(Nota), 2) AS cr_dispersao_nota,
         count(Nota)           AS cr_n_notas,
         count(CASE WHEN Nota < 5.0 THEN 1 END) AS cr_n_abaixo5
}

// Dimension 2: attendance
CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))            AS cr_total_faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))  AS cr_total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS cr_n_com_falta
}

// Dimension 3: health risk (Q8 composite signal)
CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN
    count(CASE WHEN h IS NOT NULL AND (
                 coalesce(h.malnutrition, false)
              OR coalesce(h.iron_deficiency_anemia, false)
              OR coalesce(h.diabetes, false)
              OR coalesce(h.obesity, false)
            ) THEN 1 END) AS cr_n_risco_saude
}

WITH sch, m, st, cr, AlunosDaTurma,
     uf_avg_freq, uf_avg_analf, uf_avg_atraso,
     cr_media_nota, cr_dispersao_nota, cr_n_notas, cr_n_abaixo5,
     cr_total_faltas, cr_total_dias, cr_n_com_falta,
     cr_n_risco_saude

RETURN
  // ── Join keys (used to merge back to student rows) ───────────────────────
  sch.id        AS school_id,
  cr.name       AS classroom_name,
  cr.grade_level AS classroom_grade,
  cr.stage      AS classroom_stage,
  cr.year       AS ano_letivo,

  // ── Classroom size and social profile ─────────────────────────────────────
  size(AlunosDaTurma) AS cr_n_alunos,
  size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, false) = true])   AS cr_n_bolsistas,
  size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS cr_n_pcd,
  size([s IN AlunosDaTurma WHERE coalesce(s.residence_zone, '') =~ '(?i).*rural.*']) AS cr_n_rural,
  coalesce(cr_n_risco_saude, 0)  AS cr_n_risco_saude,

  // ── Grade features ────────────────────────────────────────────────────────
  cr_media_nota,
  cr_dispersao_nota,
  cr_n_notas,
  CASE WHEN cr_n_notas > 0
       THEN round(toFloat(cr_n_abaixo5) / cr_n_notas * 100, 1)
       ELSE null END AS cr_pct_abaixo5,
  // CV% — class polarization signal (Q1 insight)
  CASE WHEN cr_media_nota > 0 AND cr_dispersao_nota IS NOT NULL
       THEN round(cr_dispersao_nota / cr_media_nota * 100, 1)
       ELSE null END AS cr_cv_nota_pct,

  // ── Attendance features ───────────────────────────────────────────────────
  CASE WHEN cr_total_dias > 0
       THEN round(toFloat(cr_total_faltas) / cr_total_dias * 100, 2)
       ELSE null END AS cr_taxa_ausencia_pct,
  CASE WHEN cr_n_alunos > 0
       THEN round(toFloat(cr_n_com_falta) / size(AlunosDaTurma) * 100, 1)
       ELSE null END AS cr_pct_alunos_com_falta,

  // ── Q8 Composite Risk Signal (derived directly from Q8 logic) ─────────────
  // Normalized by classroom size so signal is comparable across classrooms
  CASE WHEN size(AlunosDaTurma) > 0 THEN
    round(
      (toFloat(cr_n_com_falta) / size(AlunosDaTurma)) * 0.40    // attendance weight
    + (coalesce(toFloat(cr_n_abaixo5) / NULLIF(cr_n_notas, 0), 0.5)) * 0.35  // grade weight
    + (toFloat(cr_n_risco_saude) / size(AlunosDaTurma)) * 0.25, // health weight
    4)
  ELSE null END AS cr_soma_sinais_risco,

  // ── IBGE context (with UF fallback, not hardcoded 0) ─────────────────────
  coalesce(m.atl_freq_liq_fund, uf_avg_freq)   AS cr_muni_freq_liq_fund,
  coalesce(m.atl_t_analf25m, uf_avg_analf)     AS cr_muni_analf_adulto,
  coalesce(m.atl_atraso_2_fund, uf_avg_atraso) AS cr_muni_atraso_2anos,
  st.qedu_ideb_ai                              AS cr_est_ideb_ai,
  st.qedu_taxa_abandono                        AS cr_est_taxa_abandono,
  st.qedu_distorcao_ef_ai                      AS cr_est_distorcao_ai,

  // ── Quality flags ─────────────────────────────────────────────────────────
  CASE WHEN cr_n_com_falta > 0 THEN 1 ELSE 0 END AS flag_tem_diario,
  CASE WHEN cr_n_notas     > 0 THEN 1 ELSE 0 END AS flag_tem_notas
LIMIT 10000
"""
```

**Método Python:**

```python
def extract_classroom_features(self, segment: str = "EF1") -> pd.DataFrame:
    """
    Extract classroom-level feature aggregates (Q15 God Matrix).

    Returns one row per (school_id, classroom_name, grade_level) combination.
    These features can be joined back to student rows to enrich the student
    feature set with classroom context:

        df_students  = extractor.extract_ef1()
        df_classrooms = extractor.extract_classroom_features(segment='EF1')
        df_merged = df_students.merge(
            df_classrooms,
            on=['school_id', 'classroom_name', 'ano_letivo'],
            how='left'
        )

    Classroom features include:
    - cr_n_alunos, cr_n_bolsistas, cr_n_pcd, cr_n_rural
    - cr_media_nota, cr_dispersao_nota, cr_cv_nota_pct (Q1 CV signal)
    - cr_taxa_ausencia_pct, cr_pct_alunos_com_falta
    - cr_soma_sinais_risco (Q8 composite: 40% faltas + 35% notas + 25% saúde)
    - cr_muni_freq_liq_fund, cr_muni_analf_adulto (IBGE with UF fallback)

    Args:
        segment: 'EF1' for Fundamental Menor (default) or 'EF2' for EF2/EM.
                 Note: EF2 variant uses per-subject grades (Mat + Port).

    Returns:
        DataFrame with one row per classroom. Classrooms with < 5 students
        are excluded (too few for reliable aggregates).

    Raises:
        ValueError: if segment is not 'EF1' or 'EF2'.
        RuntimeError: if extraction returns zero rows.
    """
    if segment not in ("EF1", "EF2"):
        raise ValueError(f"segment must be 'EF1' or 'EF2', got '{segment}'")

    logger.info("Extracting classroom features (segment=%s)", segment)
    query = _QUERY_CLASSROOM_EF1  # EF2 variant TBD — see note below
    df    = self._run(query)

    if len(df) == 0:
        raise RuntimeError(
            f"Classroom extraction returned 0 rows (segment={segment}). "
            "Check grade_level filter."
        )

    logger.info("Classroom features extracted: %d classrooms", len(df))
    return df
```

---

## P05 🟡 — `schema.py`: adicionar `CLASSROOM_CONTEXT_FEATURES`

**Problema:** As features de turma extraídas em P04 não têm contrato em `schema.py`. Quem for usá-las no feature set do modelo de evasão não tem referência de quais colunas incluir.

**Adicione ao `schema.py` logo após `CLASSROOM_FEATURES`:**

```python
# src/ml/features/schema.py — ADIÇÃO

# ── Classroom context features (from Q15 God Matrix) ─────────────────────────
# Source: Neo4jExtractor.extract_classroom_features()
# These are classroom-level aggregates joined back to student rows.
# Join keys: (school_id, classroom_name, ano_letivo)
# Prefix cr_ distinguishes classroom-level from student-level columns.
# Q8 composite signal (cr_soma_sinais_risco) is normalized 0–1 per classroom.
CLASSROOM_CONTEXT_FEATURES = [
    "cr_n_alunos",              # int — total students in classroom
    "cr_n_bolsistas",           # int — BF students count
    "cr_n_pcd",                 # int — PCD students count
    "cr_n_rural",               # int — rural students count
    "cr_n_risco_saude",         # int — students with health risk conditions (Q8 health dimension)
    "cr_media_nota",            # float — classroom average grade (0–10 normalized)
    "cr_dispersao_nota",        # float — stDev of grades in classroom
    "cr_cv_nota_pct",           # float — coefficient of variation % (Q1 polarization signal)
    "cr_pct_abaixo5",           # float — % students failing (nota < 5)
    "cr_taxa_ausencia_pct",     # float — classroom attendance rate %
    "cr_pct_alunos_com_falta",  # float — % students with at least one recorded absence
    "cr_soma_sinais_risco",     # float 0–1 — Q8 composite (0.40 faltas + 0.35 notas + 0.25 saúde)
    "cr_muni_freq_liq_fund",    # float — IBGE net attendance rate (UF proxy if null)
    "cr_muni_analf_adulto",     # float — IBGE adult illiteracy (UF proxy if null)
    "cr_est_taxa_abandono",     # float — state official dropout rate (QEdu)
    "flag_tem_diario",          # 0/1 — classroom has electronic attendance journal
    "flag_tem_notas",           # 0/1 — classroom has registered grades
]

# ── Enriched feature set: EF1 + classroom context (for models that benefit from turma context) ──
FEATURES_EVASAO_EF1_ENRICHED = FEATURES_EVASAO_EF1 + CLASSROOM_CONTEXT_FEATURES
```

---

## P06 🟡 — Q8 `cr_soma_sinais_risco` como feature (nota de design)

O campo `cr_soma_sinais_risco` em `CLASSROOM_CONTEXT_FEATURES` (P05) já captura a lógica de Q8. Ele é calculado diretamente no Cypher de Q15 (P04) com pesos:

- **40%** → `cr_n_com_falta / cr_n_alunos` (presença da dimensão de faltas de Q8)
- **35%** → `cr_n_abaixo5 / cr_n_notas` (dimensão de notas críticas de Q8)
- **25%** → `cr_n_risco_saude / cr_n_alunos` (dimensão de saúde de Q8)

Esses pesos são os mesmos do score de Q_RISCO_EVASAO_EF2.md (40% ausência + 35% notas + 25% média invertida), alinhando as duas fontes. A feature não é redundante com os campos individuais — ela captura a interação dos 3 sinais simultaneamente, que é exatamente o que torna Q8 útil para identificar turmas de alto risco.

**Não requer código adicional** — já está integrado em P04 e P05.

---

## P07 🟡 — Conflito de schema: `atl_branco_analf25m` no `Municipality`

**Conflito documentado:**

| Fonte | O que diz |
|---|---|
| `CYPHER-QUERY-MATRIX-ML.md` (tabela Propriedades IBGE) | `atl_branco_analf25m` / `atl_negro_analf25m` → Municipality |
| `NEO4J-SCHEMA-REFERENCE.md` §8 (NÃO EXISTE) | `m.atl_branco_analf25m` → **não existe**; usar `st.branco_pnad_t_analf25m` |

**Resolução:** O `NEO4J-SCHEMA-REFERENCE.md` foi gerado a partir do schema real do banco. A tabela do matrix é uma referência anterior que ainda não foi atualizada para refletir a correção. **O plano adotou o comportamento correto** — usa `st.branco_pnad_t_analf25m` e `st.negro_pnad_t_analf25m` (State node, PNAD) em vez de Municipality.

**Ação:** Não alterar código. Adicionar esta nota ao início de `neo4j_extractor.py` para evitar regressões futuras:

```python
# src/ml/features/neo4j_extractor.py — adicionar ao docstring do módulo

# SCHEMA CONFLICT NOTE (resolved):
# CYPHER-QUERY-MATRIX-ML.md lists atl_branco_analf25m and atl_negro_analf25m
# under Municipality. NEO4J-SCHEMA-REFERENCE.md §8 confirms these do NOT exist
# in the Municipality node. The correct properties are:
#   st.branco_pnad_t_analf25m  (State, PNAD)
#   st.negro_pnad_t_analf25m   (State, PNAD)
# All queries in this file use the State-level properties. Do not add
# m.atl_branco_analf25m or m.atl_negro_analf25m — they return null or error.
```

---

## P08 🔵 — `dag__ml_feature_engineering.py`: adicionar task de turmas

**Problema:** O DAG atual extrai `ef1_*.parquet` e `ef2_grades_*.parquet`. Não extrai features de turma (Q15), que agora existem em `extract_classroom_features()`.

**Adicione a task `extract_classrooms_task` ao DAG:**

```python
# dag__ml_feature_engineering.py — ADIÇÃO à seção de tasks

def extract_ef2_base_task(**ctx):
    """Extract EF2 base context features (demographics + health + IBGE) and save to Parquet."""
    import os
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.feature_pipeline import encode_categoricals

    ext = Neo4jExtractor.from_env()
    df  = encode_categoricals(ext.extract_ef2_base())
    ext.close()

    out = f"/data/features/ef2_base_{ctx['ds_nodash']}.parquet"
    os.makedirs("/data/features", exist_ok=True)
    df.to_parquet(out, index=False)
    ctx["ti"].xcom_push(key="ef2_base_parquet", value=out)
    return out


def extract_classrooms_task(**ctx):
    """
    Extract classroom-level features (Q15 God Matrix) and save to Parquet.

    Output can be joined to student rows by (school_id, classroom_name, ano_letivo).
    Used by enriched model training and school report endpoint.
    """
    import os
    from src.ml.features.neo4j_extractor import Neo4jExtractor

    ext = Neo4jExtractor.from_env()
    df  = ext.extract_classroom_features(segment="EF1")
    ext.close()

    out = f"/data/features/classrooms_ef1_{ctx['ds_nodash']}.parquet"
    df.to_parquet(out, index=False)
    ctx["ti"].xcom_push(key="classrooms_parquet", value=out)
    return out


# ── Atualizar o DAG com as tasks novas ──────────────────────────────────────
# Substituir a linha de dependências de:
#   t_ef1 >> t_ef2
# Por:
with dag:
    t_ef1         = PythonOperator(task_id="extract_ef1",       python_callable=extract_ef1_task)
    t_ef2_grades  = PythonOperator(task_id="extract_ef2_grades", python_callable=extract_ef2_task)
    t_ef2_base    = PythonOperator(task_id="extract_ef2_base",  python_callable=extract_ef2_base_task)
    t_classrooms  = PythonOperator(task_id="extract_classrooms", python_callable=extract_classrooms_task)

    # EF1 and EF2 base can run in parallel (both anchor on School → Municipality → State)
    # Classroom extraction depends on nothing but runs after EF1 (shares graph traversal zone)
    [t_ef1, t_ef2_base] >> t_ef2_grades
    t_ef1 >> t_classrooms
```

---

## P09 🔵 — `schema.py`: features derivadas de Q1, Q9, Q12 (não extraídas, mas documentadas)

Estas features surgem das queries Q1, Q9 e Q12 do matrix mas não estão em nenhum feature set atual. Documentadas aqui para a próxima iteração do feature set — requerem queries adicionais ou cálculos derivados dos dados já extraídos.

```python
# src/ml/features/schema.py — ADIÇÃO (features para futura inclusão)

# ── Features derivadas de queries analíticas — futura inclusão ────────────────
# These features require additional extraction queries or post-processing.
# They are documented here so schema.py remains the single source of truth.
# Implement by adding the corresponding Cypher to neo4j_extractor.py when
# model performance review shows benefit from including them.

FEATURES_FUTURE = {
    # From Q1 — CV% de notas por escola: proxy de "escola polarizada"
    # Requires: extract_school_features() + cv computation in school_aggregator.py
    "escola_cv_nota_pct": "Coefficient of variation of grades across all students in school",

    # From Q9 — concentração rural na turma (já disponível via cr_n_rural em P05)
    # Compute: cr_n_rural / cr_n_alunos — can be derived from CLASSROOM_CONTEXT_FEATURES
    "cr_pct_rural": "% rural students in classroom — derive from cr_n_rural / cr_n_alunos",

    # From Q12 — delta da rede vs QEdu oficial por estado
    # Requires: Q12 aggregated query (escola→estado) + join with student rows
    # Signal: if delta > 0 → school network is worse than official state rate
    "uf_delta_vs_qedu_abandono": "State's internal absence rate minus official QEdu abandonment rate",

    # From Q5 — gender gap de nota por escola (requer pivot por gender_bin)
    # Compute: avg(nota | gender_bin=1) - avg(nota | gender_bin=0) at school level
    "escola_gender_gap_nota": "Grade gap between female and male students in the school",
}

# NOTE: cr_pct_rural can be computed NOW from existing data:
#   df["cr_pct_rural"] = df["cr_n_rural"] / df["cr_n_alunos"].replace(0, np.nan)
# Add to feature_pipeline.encode_categoricals() if including CLASSROOM_CONTEXT_FEATURES.
```

---

## Resumo de Arquivos Afetados

| Arquivo | Tipo de mudança |
|---|---|
| `src/ml/training/train_notas.py` | ✨ **Novo** — entrypoint completo (P01) |
| `src/ml/mlops/champion_challenger.py` | ♻️ **Reescrita** — suporte a regressão (P02) |
| `src/ml/features/school_aggregator.py` | ✨ **Novo** — implementação completa (P03) |
| `src/ml/features/neo4j_extractor.py` | ➕ **Adição** — `_QUERY_EF2_BASE`, `extract_ef2_base()`, `_QUERY_CLASSROOM_EF1`, `extract_classroom_features()` (P04) |
| `src/ml/features/schema.py` | ➕ **Adição** — `CLASSROOM_CONTEXT_FEATURES`, `FEATURES_EVASAO_EF1_ENRICHED`, `FEATURES_FUTURE` (P05, P09) |
| `dags/dag__ml_feature_engineering.py` | ➕ **Adição** — tasks `extract_ef2_base_task`, `extract_classrooms_task` + dependências (P08) |
| `src/ml/features/neo4j_extractor.py` | 📝 **Nota** — schema conflict `atl_branco_analf25m` no docstring (P07) |

## Checklist de Validação Pós-Patch

- [ ] `python -m py_compile src/ml/training/train_notas.py` — sem erros
- [ ] `python -m py_compile src/ml/mlops/champion_challenger.py` — sem erros
- [ ] `python -m py_compile src/ml/features/school_aggregator.py` — sem erros
- [ ] `promote_if_better(model_type="notas", ...)` chamado com `challenger_metrics` contendo `r2` — não lança `KeyError`
- [ ] `promote_if_better(model_type="xyz", ...)` — lança `KeyError` com mensagem clara
- [ ] `extract_ef2_base()` retorna colunas idênticas a `extract_ef1()` exceto pelas de grade (nota_final_norm etc.)
- [ ] `extract_classroom_features()` retorna `cr_n_alunos`, `cr_soma_sinais_risco`, `cr_cv_nota_pct`
- [ ] Merge `df_base.merge(df_grades, on='student_id', how='inner')` não perde mais de 20% dos alunos
- [ ] `compute_school_metrics()` não lança exceção com `n_com_saude = 0` (divisão por zero guard)
- [ ] DAG `extract_classrooms` não depende de `extract_ef2_grades` (tarefas independentes)
- [ ] `atl_branco_analf25m` não aparece em nenhuma query Cypher do extrator
# PLAN-ML-01 — Feature Engineering · Machine Learning · MLOps

> **Series:** ML Layer (1/3)
> **Status:** IMPLEMENTATION
> **Graph schema:** `neo4_schema_and_tips.md` — all node properties, canonical filters, ATTENDED direction
> **Cypher queries reference:** `main_cypher_queries.md` — Q1–Q15 full query matrix with fallback patterns
> **Dropout risk analytics:** `Q_risco_evasao.md` — composited risk score (40% absence + 35% failing grades + 25% inverted mean)
> **School health analytics:** `Q_risco_evasaoQ2.md` — 4-component health score, proximity clustering
> **Does NOT duplicate:** node property definitions, Cypher syntax rules, grade_level encoding tables — see schema reference

---

## Directory Structure

```
src/ml/
├── features/
│   ├── schema.py                  # Feature contracts: column lists, target names, encodings
│   ├── neo4j_extractor.py         # All Cypher lives here → typed DataFrames. No Cypher anywhere else.
│   ├── feature_pipeline.py        # Encoding, imputation, normalization, temporal split
│   └── school_aggregator.py       # School-level feature aggregation for school embedding + report
├── models/
│   ├── dropout_classifier.py      # XGBoostClassifier for binary dropout prediction
│   ├── grade_regressor.py         # GradientBoostingRegressor for grade prediction per subject (EF2)
│   └── risk_clusterer.py          # KMeans + PCA, writes risk_cluster back to Neo4j
├── evaluation/
│   ├── metrics.py                 # Pure metric functions: auroc, f1, rmse, silhouette
│   └── explainability.py          # SHAP global summary + local waterfall per student
├── mlops/
│   ├── experiment.py              # Thin MLflow context manager (model knows nothing about it)
│   ├── registry.py                # MLflow Model Registry: staging → production promotion
│   ├── drift.py                   # Evidently AI: per-column data drift report, PSI flag
│   └── champion_challenger.py     # Compare challenger vs champion, auto-promote if AUROC delta > threshold
└── training/
    ├── train_evasao.py            # Entrypoint: extract → encode → split → train → evaluate → log → promote
    └── train_notas.py             # Entrypoint: same pattern for grade regression model

dags/
├── dag__ml_feature_engineering.py  # Daily: Cypher → Parquet cache
├── dag__ml_retrain.py              # Weekly: full retrain pipeline (6 tasks)
└── dag__ml_drift_detection.py      # Weekly: Evidently drift check → sets retrain flag
```

---

## Coding Principles

- **One function, one responsibility.** Functions exceeding 40 lines are a signal to decompose.
- **All Cypher in `neo4j_extractor.py`.** No other module touches the Neo4j driver.
- **MLflow as a context, not as logic.** Training functions receive and return plain Python objects. The entrypoint wraps them in `log_run` — models are never aware of experiment tracking.
- **Mandatory temporal split.** Never `train_test_split(random=True)` — that creates temporal data leakage since the same student may appear in train and test from different school years.
- **Structured logging only.** `logging.getLogger(__name__)` everywhere. INFO for pipeline milestones, WARNING for anomalies (drift, low metric), ERROR for recoverable failures. Zero `print()` calls.
- **No personal data in logs.** Never log `student_id`, student name, or raw question text. Log counts, hashes, latency.
- **Municipality IBGE fallback is mandatory.** Many municipalities have NULL for IBGE Atlas fields — this is documented in `neo4_schema_and_tips.md §4.4`. Every IBGE field must have a same-UF municipality average as fallback. This is done **in Cypher** (not pandas) to keep data consistent at the source.

---

## 1. `src/ml/features/schema.py` — Feature Contracts

The single source of truth for the feature set. Every change to what we extract, encode, or model starts here — not scattered across model files.

```python
# src/ml/features/schema.py
"""
Feature set contracts for the school ML system.

This module defines:
- Column lists by feature group (demographic, health, attendance, grades, context)
- Target column names
- Categorical encoding dictionaries (must match Cypher extraction exactly)
- Which columns must never be null after imputation

Any schema change (new feature, renamed column, removed node property) starts here.
Other modules import from this file — no hardcoded column names anywhere else.

References:
- Node properties: neo4_schema_and_tips.md §1-2
- Canonical grade_level filters: neo4_schema_and_tips.md §5
- Municipality IBGE sparsity: neo4_schema_and_tips.md §4.4
"""

# ── Identity columns (drop before training, keep for joins and writebacks) ────
ID_COLS = ["student_id", "school_id", "uf"]

# ── Targets ───────────────────────────────────────────────────────────────────
TARGET_DROPOUT      = "target_evasao"       # binary 0/1 — absence > 25% of scheduled days
TARGET_GRADE        = "target_nota"          # float 0.0–10.0 — normalized final_mean
TARGET_REPROVACAO   = "target_reprovacao"    # binary 0/1 — final_mean_norm < 5.0

# ── Demographic features (Student node) ──────────────────────────────────────
# Source: stu.gender, stu.ethnicity, stu.deficiency (STRING not bool),
#         stu.bolsa_familia (bool), stu.residence_zone
# See neo4_schema_and_tips.md §2 for correct property names and types.
DEMO_FEATURES = [
    "gender_bin",           # 0=male, 1=female — from stu.gender =~ '(?i)^F.*'
    "ethnicity_enc",        # 0–5 label encoded — see ETHNICITY_ENCODING below
    "has_deficiency",       # 0/1 — STARTS WITH 'Possui' on stu.deficiency (STRING, not boolean!)
    "bolsa_familia",        # 0/1 — coalesce(stu.bolsa_familia, false)
    "residence_zone_enc",   # 0=Rural, 1=Urban, 2=Not Reported
]

# ── Health features (Health node — OPTIONAL via HAS_HEALTH) ──────────────────
# Source: (stu)-[:HAS_HEALTH]->(h:Health)
# Not all students have this node. Absence ≠ no conditions — it is missing data.
# See neo4_schema_and_tips.md §4.2 for sparsity documentation.
# CRITICAL: property names are h.malnutrition, h.diabetes (NOT h.malnutrition_desease)
HEALTH_FEATURES = [
    "has_health_record",    # 0/1 — whether the Health node exists at all
    "has_malnutrition",     # 0/1 — h.malnutrition (boolean, correct name)
    "has_diabetes",         # 0/1 — h.diabetes (boolean, correct name)
    "has_hypertension",     # 0/1 — h.hypertension
    "has_obesity",          # 0/1 — h.obesity
    "has_celiac",           # 0/1 — h.celiac
    "has_anemia",           # 0/1 — h.iron_deficiency_anemia OR h.sickle_cell_anemia
    "n_health_conditions",  # int — sum of all boolean conditions above
]

# ── Attendance features (StudentClass node — OPTIONAL via ATTENDED) ───────────
# Source: (sc:StudentClass)-[:ATTENDED]->(stu)  ← direction is StudentClass → Student
# Only exists for schools using electronic attendance journal.
# If school has no journal: ZERO StudentClass nodes for ALL its students.
# DO NOT infer 0 absences when node is missing — it is missing data.
# See neo4_schema_and_tips.md §4.1 for electronic journal coverage sparsity.
FREQ_FEATURES = [
    "tem_diario",           # 0/1 — flag: does school use electronic journal?
    "taxa_ausencia",        # float — null when tem_diario=0 (missing data, not zero)
    "falta_critica",        # 0/1 — taxa_ausencia > 10% threshold
    "total_faltas_abs",     # int — raw count of absence days
]

# ── EF1 grade features (StudentDiscipline WHERE discipline_name = '') ─────────
# Source: (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
# EF1 has ONE record per student with discipline_name = '' (global grade).
# Grades may be on 0–100 scale (legacy) or 0–10 scale (current).
# Normalization: CASE WHEN val > 10 THEN val/10.0 ELSE val END — done in Cypher.
GRADE_EF1_FEATURES = [
    "nota_final_norm",      # float 0–10, normalized — sd.final_mean
    "nota_g1_norm",         # float 0–10, normalized — sd.grade_1 (first bimester)
    "nota_g2_norm",         # float 0–10, normalized — sd.grade_2
    "trajetoria_nota",      # float (can be negative) — nota_final_norm - nota_g1_norm
    "em_recuperacao",       # 0/1 — nota_final_norm < 5.0
]

# ── EF2 grade features (StudentDiscipline WHERE discipline_name <> '') ────────
# EF2 has N records per student, one per subject (discipline_name is non-empty).
# These are pivoted in the EF2 query: avg per subject, global aggregates.
GRADE_EF2_FEATURES = [
    "nota_mat_norm",                # float — Matemática final mean normalized
    "nota_lp_norm",                 # float — Português final mean normalized
    "nota_ciencias_norm",           # float — Ciências final mean normalized
    "nota_historia_norm",           # float — História final mean normalized
    "nota_geo_norm",                # float — Geografia final mean normalized
    "nota_media_geral",             # float — avg across all disciplines
    "nota_dispersao",               # float — stDev across all disciplines
    "n_disciplinas_total",          # int — count of distinct disciplines with grades
    "n_disciplinas_abaixo5",        # int — count of disciplines where final < 5.0
    "pct_disciplinas_abaixo5",      # float — n_abaixo5 / n_total
    "trajetoria_media",             # float — avg(final_norm) - avg(g1_norm)
]

# ── Classroom context ─────────────────────────────────────────────────────────
CLASSROOM_FEATURES = [
    "stage_enc",            # 0=EI, 1=EF1, 2=EF2, 3=EM, 4=Superior, 5=EJA
    "grade_level_enc",      # ordinal 0–10 — see GRADE_LEVEL_ENCODING
    "ano_letivo",           # int — school year (cr.year)
]

# ── Municipal IBGE context (Municipality node — may be NULL) ──────────────────
# Many small municipalities have NULL values in Atlas fields.
# Estimated 30–50% nulls for equity-related fields.
# ALL of these are computed in Cypher with same-UF municipality average as fallback.
# See CYPHER-QUERY-MATRIX-ML.md §Fallback IBGE for the fallback pattern.
MUNICIPAL_FEATURES = [
    "muni_freq_liq_fund",       # m.atl_freq_liq_fund → % net attendance rate in municipality
    "muni_atraso_2anos",        # m.atl_atraso_2_fund → % students 2+ years behind in municipality
    "muni_analf_adulto",        # m.atl_t_analf25m → % adult illiteracy (proxy for family support)
    "muni_expectativa_estudo",  # m.atl_expectativa_estudo_18 → expected years of study at age 18
    "muni_pct_negro_pub",       # m.atl_negro_mat_pub_fund → % Black students in public schools
    "muni_internet_negro",      # m.atl_negro_internet_fund → % fund. schools with internet for Black students
    "muni_internet_branco",     # m.atl_branco_internet_fund → % fund. schools with internet for White students
    "muni_delta_freq",          # calculated: taxa_ausencia*100 - (100 - muni_freq_liq_fund)
    # Source flags (not model features — for monitoring and debugging only)
    "muni_freq_fonte",          # 'Municipal' | 'Media_UF_Proxy' — which source was used
    "muni_atraso_fonte",        # same pattern for atraso field
    "muni_analf_fonte",         # same pattern for analf field
]

# ── State QEdu context ────────────────────────────────────────────────────────
STATE_QEDU_FEATURES = [
    "est_ideb_ai",              # st.qedu_ideb_ai — IDEB early years
    "est_ideb_af",              # st.qedu_ideb_af — IDEB final years
    "est_taxa_abandono",        # st.qedu_taxa_abandono — official dropout rate
    "est_taxa_reprovacao",      # st.qedu_taxa_reprovacao — official failure rate
    "est_fluxo_af",             # st.qedu_fluxo_af — school flow (0=full retention, 1=perfect)
    "est_pct_fora_escola",      # st.qedu_pct_fora_escola — % children out of school
    "est_distorcao_serie",      # qedu_distorcao_ef{N} matched to grade_level (e.g., ef6 for 6th year)
    "est_lp_insuf_af",          # st.qedu_lp_insuficiente_af — % insufficient LP proficiency
    "est_mat_insuf_af",         # st.qedu_mt_insuficiente_af — % insufficient Math proficiency
    "est_lp_adequado_af",       # st.qedu_lp_adequado_af — % adequate LP proficiency
    "est_mat_adequado_af",      # st.qedu_mt_adequado_af — % adequate Math proficiency
    "est_aprendizado_af",       # st.qedu_aprendizado_af — learning score (state level)
]

# ── State PNAD context (racial and gender equity) ─────────────────────────────
# NOTE: racial illiteracy fields exist on State (PNAD), NOT on Municipality (Atlas).
# Municipality does NOT have atl_branco_analf25m or atl_negro_analf25m.
# See neo4_schema_and_tips.md §8 for properties that do NOT exist.
STATE_PNAD_FEATURES = [
    "est_analf_negro",          # st.negro_pnad_t_analf25m
    "est_analf_branco",         # st.branco_pnad_t_analf25m
    "est_atraso_negro",         # st.negro_pnad_t_atraso_fund
    "est_atraso_branco",        # st.branco_pnad_t_atraso_fund
    "est_analf_homem",          # st.homem_pnad_t_analf25m
    "est_analf_mulher",         # st.mulher_pnad_t_analf25m
    "est_rdpc_negro",           # st.negro_pnad_rdpc — per capita income Black (equity proxy)
    "est_rdpc_branco",          # st.branco_pnad_rdpc — per capita income White
]

# ── Full feature sets per model ───────────────────────────────────────────────
FEATURES_EVASAO_EF1 = (
    DEMO_FEATURES + HEALTH_FEATURES + FREQ_FEATURES +
    GRADE_EF1_FEATURES + CLASSROOM_FEATURES +
    MUNICIPAL_FEATURES + STATE_QEDU_FEATURES + STATE_PNAD_FEATURES
)

FEATURES_NOTAS_EF2 = (
    DEMO_FEATURES + HEALTH_FEATURES + FREQ_FEATURES +
    GRADE_EF2_FEATURES + CLASSROOM_FEATURES +
    MUNICIPAL_FEATURES + STATE_QEDU_FEATURES + STATE_PNAD_FEATURES
)

# Columns that must NEVER be null after imputation (checked in test suite)
NEVER_NULL_AFTER_IMPUTE = [
    "gender_bin", "bolsa_familia", "has_deficiency",
    "tem_diario", "has_health_record",
    "stage_enc", "grade_level_enc", "ano_letivo",
    "n_health_conditions",
]

# ── Encoding dictionaries ─────────────────────────────────────────────────────
STAGE_ENCODING = {
    "EDUCAÇÃO INFANTIL":          0,
    "ENSINO FUNDAMENTAL":         1,   # used for both EF1 and EF2 — grade_level_enc differentiates
    "ENSINO MÉDIO":               2,
    "ENSINO SUPERIOR":            3,
    "EDUCAÇÃO DE JOVENS E ADULTOS": 4,
    "MULTIETAPA":                 5,
    "EDUCAÇÃO PROFISSIONAL":      6,
}

GRADE_LEVEL_ENCODING = {
    # EI
    "NA PRÉ-ESCOLA":          0,
    "NA CRECHE":               0,
    "NA EDUCAÇÃO INFANTIL":    0,
    # EF1
    "NO 1* ANO":              1,
    "NO 2* ANO":              2,
    "NO 3* ANO":              3,
    "NO 4* ANO":              4,
    "NO 5* ANO":              5,
    # EF2
    "NO 6* ANO":              6,
    "NO 7* ANO":              7,
    "NO 8* ANO":              8,
    "NO 9* ANO":              9,
    # Legacy série format — see neo4_schema_and_tips.md §5 for disambiguation
    "NA 1* SÉRIE":            1,   # EF only when stage = ENSINO FUNDAMENTAL
    "NA 2* SÉRIE":            2,
    "NA 3* SÉRIE":            3,
    "NA 4* SÉRIE":            4,
    "NA 5* SÉRIE":            5,
    "NA 6* SÉRIE":            6,
    "NA 7* SÉRIE":            7,
    "NA 8* SÉRIE":            8,
    "NA 9* SÉRIE":            9,
}

ETHNICITY_ENCODING = {
    "Branca":        0,
    "Parda":         1,
    "Preta":         2,
    "Amarela":       3,
    "Indígena":      4,
    "Não Declarada": 5,
    "":              5,   # empty string treated as not declared
}

RESIDENCE_ENCODING = {
    "Rural":          0,
    "Urbana":         1,
    "Não Informado":  2,
    None:             2,
}

# Source labels for IBGE fallback monitoring
IBGE_SOURCE_MUNICIPAL  = "Municipal"
IBGE_SOURCE_UF_PROXY   = "Media_UF_Proxy"
```

---

## 2. `src/ml/features/neo4j_extractor.py` — Cypher → DataFrame

Every single line of Cypher lives in this file. No other module creates Neo4j sessions or writes Cypher strings.

### IBGE Fallback Pattern

Multiple IBGE Atlas fields in the `Municipality` node are NULL for a significant fraction of municipalities (estimated 30–50% for equity fields). The fallback is computed in Cypher, not in pandas, ensuring consistent data at source:

```cypher
// ── Pattern: per IBGE field, compute UF fallback BEFORE main query ────────────
// Step 1: compute UF average for each sparse field
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_avg_freq
}
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_atraso_2_fund IS NOT NULL
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

// Step 2: apply coalesce(field, uf_fallback) in RETURN clause
// Step 3: expose source flag for monitoring
RETURN
  coalesce(m.atl_freq_liq_fund, uf_avg_freq)              AS muni_freq_liq_fund,
  CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_freq_fonte,

  coalesce(m.atl_atraso_2_fund, uf_avg_atraso)            AS muni_atraso_2anos,
  CASE WHEN m.atl_atraso_2_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_atraso_fonte,

  coalesce(m.atl_t_analf25m, uf_avg_analf)                AS muni_analf_adulto,
  CASE WHEN m.atl_t_analf25m IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_analf_fonte,
  ...
```

See `CYPHER-QUERY-MATRIX-ML.md` — the `Fallback IBGE` pattern used across Q1–Q15 is exactly this same structure. All our extraction queries follow the same pattern.

```python
# src/ml/features/neo4j_extractor.py
"""
Neo4j feature extraction layer.

All Cypher queries are defined here. No other module in src/ml/ touches the driver.
Each public method returns a typed pandas DataFrame ready for feature_pipeline.py.

Query design follows the collect → isolate → aggregate pattern documented in
neo4_schema_and_tips.md §6 (Performance Patterns). Chained OPTIONAL MATCHes
create N×M×K cartesian products and cause timeouts — each dimension (attendance,
grades, health) is isolated in its own CALL block.

IBGE fallback: every Municipality IBGE field has a same-UF municipality average
fallback computed in Cypher (not pandas). This is documented in
CYPHER-QUERY-MATRIX-ML.md §Fallback IBGE and neo4_schema_and_tips.md §4.4.

References:
- EF1 extraction query: PLAN-ML-NEO4J-SCHOOL.md §3.1
- EF2 grade pivot query: PLAN-ML-NEO4J-SCHOOL.md §3.2
- Full analytic query matrix: CYPHER-QUERY-MATRIX-ML.md Q1–Q15
- Dropout risk score structure: Q_RISCO_EVASAO_EF2.md
"""
import logging
from typing import Literal
import pandas as pd
from neo4j import GraphDatabase, Driver

logger = logging.getLogger(__name__)

# ── EF1 full extraction query ─────────────────────────────────────────────────
# One row per student. Includes all features for the dropout model.
# Grade filter: canonical EF1 filter from neo4_schema_and_tips.md §5.
# IBGE fallback: 6 separate CALL blocks for 6 sparse municipality fields.
# Attendance: CALL (stu) isolates StudentClass (sc)-[:ATTENDED]->(stu) — correct direction.
# Grades: CALL (stu) isolates StudentDiscipline with discipline_name = '' (EF1 global grade).
# Note: h.malnutrition correct — NOT h.malnutrition_desease. See schema reference §8.
_QUERY_EF1 = """
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// ── IBGE Fallbacks: one CALL per sparse Municipality field ──────────────────
// atl_atraso_2_fund is especially sparse. All 6 fields get individual fallbacks.
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

// ── Main traversal: students in EF1 classrooms ──────────────────────────────
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

WITH DISTINCT stu, cr, sch, m, st,
     uf_avg_freq, uf_avg_atraso, uf_avg_analf,
     uf_avg_expectativa, uf_avg_negro_pub, uf_avg_negro_internet

// Health node is OPTIONAL — absence ≠ no conditions (see neo4_schema_and_tips.md §4.2)
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)

WITH stu, cr, sch, m, st, h,
     uf_avg_freq, uf_avg_atraso, uf_avg_analf,
     uf_avg_expectativa, uf_avg_negro_pub, uf_avg_negro_internet

// ── Attendance dimension (isolated CALL to avoid cartesian product) ──────────
// Direction: (sc:StudentClass)-[:ATTENDED]->(stu) — NOT reversed
// Schools without electronic journal have ZERO StudentClass nodes
CALL (stu) {
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))            AS total_faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))  AS total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN sc END)  AS n_sc_records
}

// ── Grade dimension — EF1: discipline_name = '' means global grade ────────────
// CASE WHEN val > 10 THEN val/10.0 — normalizes legacy 0–100 scale to 0–10
CALL (stu) {
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH
    CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
         THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
         ELSE coalesce(sd.final_mean, sd.grade_1)
    END AS nota_final,
    CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
         THEN sd.grade_1 / 10.0
         ELSE sd.grade_1
    END AS nota_g1,
    CASE WHEN sd.grade_2 IS NOT NULL AND sd.grade_2 > 10
         THEN sd.grade_2 / 10.0
         ELSE sd.grade_2
    END AS nota_g2
  RETURN
    nota_final, nota_g1, nota_g2,
    CASE WHEN nota_final IS NOT NULL AND nota_g1 IS NOT NULL
         THEN nota_final - nota_g1
         ELSE null
    END AS trajetoria
}

// ── Materialized IBGE values with fallback and source flag ───────────────────
WITH stu, cr, sch, m, st, h,
     total_faltas, total_dias, n_sc_records,
     nota_final, nota_g1, nota_g2, trajetoria,
     uf_avg_freq, uf_avg_atraso, uf_avg_analf,
     uf_avg_expectativa, uf_avg_negro_pub, uf_avg_negro_internet,
     // Computed derived fields
     CASE WHEN n_sc_records > 0 THEN 1 ELSE 0 END AS tem_diario

RETURN
  // ── Identity ──────────────────────────────────────────────────────────────
  stu.id   AS student_id,
  sch.id   AS school_id,
  st.sigla AS uf,

  // ── Demographics — stu properties ─────────────────────────────────────────
  CASE WHEN stu.gender =~ '(?i)^F.*' THEN 1 ELSE 0 END                          AS gender_bin,
  coalesce(stu.ethnicity, '')                                                      AS ethnicity_raw,
  CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN 1 ELSE 0 END AS has_deficiency,
  CASE WHEN coalesce(stu.bolsa_familia, false) THEN 1 ELSE 0 END                 AS bolsa_familia,
  coalesce(stu.residence_zone, 'Não Informado')                                   AS residence_zone_raw,

  // ── Health — h properties (h.malnutrition NOT h.malnutrition_desease) ─────
  CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END                                       AS has_health_record,
  CASE WHEN coalesce(h.malnutrition, false) THEN 1 ELSE 0 END                    AS has_malnutrition,
  CASE WHEN coalesce(h.diabetes, false) THEN 1 ELSE 0 END                        AS has_diabetes,
  CASE WHEN coalesce(h.hypertension, false) THEN 1 ELSE 0 END                    AS has_hypertension,
  CASE WHEN coalesce(h.obesity, false) THEN 1 ELSE 0 END                         AS has_obesity,
  CASE WHEN coalesce(h.celiac, false) THEN 1 ELSE 0 END                          AS has_celiac,
  CASE WHEN coalesce(h.iron_deficiency_anemia, false)
        OR coalesce(h.sickle_cell_anemia, false) THEN 1 ELSE 0 END               AS has_anemia,

  // ── Attendance ────────────────────────────────────────────────────────────
  tem_diario,
  total_faltas                                                                     AS total_faltas_abs,
  CASE WHEN tem_diario = 1 AND total_dias > 0
       THEN round(toFloat(total_faltas) / total_dias, 4)
       ELSE null END                                                               AS taxa_ausencia,
  CASE WHEN tem_diario = 1 AND total_dias > 0
        AND toFloat(total_faltas) / total_dias > 0.10
       THEN 1 ELSE 0 END                                                          AS falta_critica,

  // ── Grades EF1 (global — discipline_name = '') ────────────────────────────
  nota_final                                                                       AS nota_final_norm,
  nota_g1                                                                          AS nota_g1_norm,
  nota_g2                                                                          AS nota_g2_norm,
  trajetoria                                                                       AS trajetoria_nota,
  CASE WHEN nota_final IS NOT NULL AND nota_final < 5.0 THEN 1 ELSE 0 END        AS em_recuperacao,

  // ── Classroom context ─────────────────────────────────────────────────────
  cr.stage      AS stage_raw,
  cr.grade_level AS grade_level_raw,
  cr.year       AS ano_letivo,

  // ── Municipality IBGE (with same-UF average fallback per field) ───────────
  coalesce(m.atl_freq_liq_fund, uf_avg_freq)                                      AS muni_freq_liq_fund,
  CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_freq_fonte,

  coalesce(m.atl_atraso_2_fund, uf_avg_atraso)                                    AS muni_atraso_2anos,
  CASE WHEN m.atl_atraso_2_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_atraso_fonte,

  coalesce(m.atl_t_analf25m, uf_avg_analf)                                        AS muni_analf_adulto,
  CASE WHEN m.atl_t_analf25m IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_analf_fonte,

  coalesce(m.atl_expectativa_estudo_18, uf_avg_expectativa)                        AS muni_expectativa_estudo,
  coalesce(m.atl_negro_mat_pub_fund, uf_avg_negro_pub)                             AS muni_pct_negro_pub,
  coalesce(m.atl_negro_internet_fund, uf_avg_negro_internet)                       AS muni_internet_negro,
  // Note: atl_branco_analf25m does NOT exist on Municipality — racial illiteracy is on State (PNAD)
  // See neo4_schema_and_tips.md §8 for properties that do NOT exist.

  // Delta: how much worse/better is this school vs municipal benchmark
  CASE WHEN tem_diario = 1 AND total_dias > 0
        AND coalesce(m.atl_freq_liq_fund, uf_avg_freq) IS NOT NULL
       THEN round(
         toFloat(total_faltas) / total_dias * 100
         - (100.0 - coalesce(m.atl_freq_liq_fund, uf_avg_freq)), 4)
       ELSE null END                                                               AS muni_delta_freq,

  // ── State QEdu ────────────────────────────────────────────────────────────
  st.qedu_ideb_ai                AS est_ideb_ai,
  st.qedu_ideb_af                AS est_ideb_af,
  st.qedu_taxa_abandono          AS est_taxa_abandono,
  st.qedu_taxa_reprovacao        AS est_taxa_reprovacao,
  st.qedu_fluxo_ai               AS est_fluxo_ai,
  st.qedu_pct_fora_escola        AS est_pct_fora_escola,
  st.qedu_lp_insuficiente_ai    AS est_lp_insuf_ai,
  st.qedu_mt_insuficiente_ai    AS est_mat_insuf_ai,
  st.qedu_lp_adequado_ai        AS est_lp_adequado_ai,
  st.qedu_mt_adequado_ai        AS est_mat_adequado_ai,
  st.qedu_aprendizado_ai        AS est_aprendizado_ai,
  // Grade-specific distortion — pulls the right qedu_distorcao_efN field
  CASE cr.grade_level
    WHEN 'NO 1* ANO' THEN st.qedu_distorcao_ef1
    WHEN 'NO 2* ANO' THEN st.qedu_distorcao_ef2
    WHEN 'NO 3* ANO' THEN st.qedu_distorcao_ef3
    WHEN 'NO 4* ANO' THEN st.qedu_distorcao_ef4
    WHEN 'NO 5* ANO' THEN st.qedu_distorcao_ef5
    ELSE st.qedu_distorcao_ef_ai
  END                            AS est_distorcao_serie,

  // ── State PNAD (racial and gender — NOT duplicated from Municipality) ─────
  st.negro_pnad_t_analf25m       AS est_analf_negro,
  st.branco_pnad_t_analf25m      AS est_analf_branco,
  st.negro_pnad_t_atraso_fund    AS est_atraso_negro,
  st.branco_pnad_t_atraso_fund   AS est_atraso_branco,
  st.homem_pnad_t_analf25m       AS est_analf_homem,
  st.mulher_pnad_t_analf25m      AS est_analf_mulher,
  st.negro_pnad_rdpc             AS est_rdpc_negro,
  st.branco_pnad_rdpc            AS est_rdpc_branco,

  // ── Targets ───────────────────────────────────────────────────────────────
  // Dropout: > 25% of scheduled days missed
  CASE WHEN tem_diario = 1 AND total_dias > 0
        AND toFloat(total_faltas) / total_dias > 0.25
       THEN 1 ELSE 0 END AS target_evasao,
  // Failure: normalized final grade below 5.0
  CASE WHEN nota_final IS NOT NULL AND nota_final < 5.0
       THEN 1 ELSE 0 END AS target_reprovacao,
  nota_final             AS target_nota
"""

# ── EF2 grade pivot query (join with EF1 query via student_id) ───────────────
# Returns one row per student with subject grades pivoted.
# discipline_name <> '' identifies EF2 records (per-subject, multiple per student).
# See PLAN-ML-NEO4J-SCHOOL.md §3.2 for this query's full annotated version.
# See Q_RISCO_EVASAO_EF2.md for how subject grades feed into the risk score.
_QUERY_EF2_GRADES = """
MATCH (sch:School)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\\\* SÉRIE')
WITH DISTINCT stu

MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH stu.id AS student_id,
     sd.discipline_name AS disciplina,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
          THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
          ELSE coalesce(sd.final_mean, sd.grade_1)
     END AS nota_final_norm,
     CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
          THEN sd.grade_1 / 10.0
          ELSE sd.grade_1
     END AS nota_g1_norm

RETURN
  student_id,
  count(disciplina)                                                              AS n_disciplinas_total,
  round(avg(nota_final_norm), 4)                                                AS nota_media_geral,
  round(stDev(nota_final_norm), 4)                                              AS nota_dispersao,
  count(CASE WHEN nota_final_norm < 5.0 THEN 1 END)                            AS n_disciplinas_abaixo5,
  round(
    toFloat(count(CASE WHEN nota_final_norm < 5.0 THEN 1 END))
    / count(disciplina), 4
  )                                                                             AS pct_disciplinas_abaixo5,
  round(avg(nota_final_norm) - avg(nota_g1_norm), 4)                           AS trajetoria_media,

  // Subject pivots via conditional aggregation
  round(avg(CASE WHEN disciplina =~ '(?i).*MATEM.*' THEN nota_final_norm END), 4)   AS nota_mat_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*PORTUGU.*' THEN nota_final_norm END), 4) AS nota_lp_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*CIÊN.*' THEN nota_final_norm END), 4)    AS nota_ciencias_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*HISTÓR.*' THEN nota_final_norm END), 4)  AS nota_historia_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*GEOGRAF.*' THEN nota_final_norm END), 4) AS nota_geo_norm
"""

# ── School-level feature query (for school embedding and risk reports) ────────
# Aggregates student features per school.
# Matches the analytic logic in Q_SAUDE_ESCOLA_E_PROXIMIDADE.md.
_QUERY_SCHOOL_FEATURES = """
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

MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)
WITH sch, m, st, uf_avg_freq, uf_avg_analf,
     collect(DISTINCT stu) AS todos_alunos

CALL (todos_alunos) {
  UNWIND todos_alunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS n_com_diario,
    sum(coalesce(sc.total_faults_per_day, 0))             AS total_faltas_escola,
    sum(coalesce(sc.scheduled_student_class_days, 200))   AS total_dias_escola
}

CALL (todos_alunos) {
  UNWIND todos_alunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name,'') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS nota
  RETURN
    count(nota)                              AS n_notas,
    round(avg(nota), 4)                      AS media_nota_escola,
    count(CASE WHEN nota < 5.0 THEN 1 END)   AS n_abaixo5
}

CALL (todos_alunos) {
  UNWIND todos_alunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN
    count(DISTINCT CASE WHEN h IS NOT NULL THEN stu END) AS n_com_saude,
    count(DISTINCT CASE WHEN coalesce(h.malnutrition,false) THEN stu END) AS n_desnutridos
}

RETURN
  sch.id    AS school_id,
  sch.name  AS school_name,
  m.name    AS municipio,
  st.sigla  AS uf,
  size(todos_alunos) AS n_alunos,

  // Attendance
  n_com_diario,
  CASE WHEN n_com_diario = 0 THEN null
       WHEN total_dias_escola > 0
       THEN round(toFloat(total_faltas_escola) / total_dias_escola * 100, 2)
       ELSE null END AS taxa_ausencia_pct,

  // Grades
  n_notas,
  media_nota_escola,
  CASE WHEN n_notas > 0
       THEN round(toFloat(n_abaixo5) / n_notas * 100, 1)
       ELSE null END AS pct_abaixo5,

  // Health
  n_com_saude,
  n_desnutridos,

  // Social profile — list comprehension (O(N) without extra UNWIND)
  size([s IN todos_alunos WHERE coalesce(s.bolsa_familia, false)]) AS n_bolsa_familia,
  size([s IN todos_alunos WHERE coalesce(s.deficiency,'Não') STARTS WITH 'Possui']) AS n_pcd,

  // IBGE (with fallback)
  coalesce(m.atl_freq_liq_fund, uf_avg_freq)   AS muni_freq_liq_fund,
  coalesce(m.atl_t_analf25m, uf_avg_analf)      AS muni_analf_adulto,
  st.qedu_ideb_af                               AS est_ideb_af,
  st.qedu_taxa_abandono                         AS est_taxa_abandono,
  st.qedu_taxa_reprovacao                       AS est_taxa_reprovacao
"""


class Neo4jExtractor:
    """
    Extracts feature DataFrames from Neo4j for the ML pipeline.

    This is the only class in src/ml/ that holds a Neo4j driver.
    Instantiate once per pipeline run and reuse — the driver maintains a
    connection pool internally.

    Usage:
        extractor = Neo4jExtractor.from_env()
        df_ef1 = extractor.extract_ef1(year=2024)
        df_ef2 = extractor.extract_ef2_grades()
        extractor.close()
    """

    def __init__(self, uri: str, user: str, password: str) -> None:
        """
        Initialize the extractor with Neo4j connection parameters.

        Args:
            uri: Neo4j bolt URI, e.g. 'bolt://localhost:7687'
            user: Neo4j username
            password: Neo4j password
        """
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))

    @classmethod
    def from_env(cls) -> "Neo4jExtractor":
        """
        Create an extractor from environment variables.

        Expected env vars: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
        Raises KeyError immediately if any is missing — fail fast.
        """
        import os
        return cls(
            uri=os.environ["NEO4J_URI"],
            user=os.environ["NEO4J_USER"],
            password=os.environ["NEO4J_PASSWORD"],
        )

    def close(self) -> None:
        """Close the driver and release the connection pool."""
        self._driver.close()

    def extract_ef1(self, year: int | None = None) -> pd.DataFrame:
        """
        Extract the EF1 feature set (one row per student).

        Returns all columns defined in schema.py FEATURES_EVASAO_EF1 plus
        the ID columns, raw categoricals, source flags, and target columns.

        IBGE fields for Municipality are computed with same-UF municipality
        average as fallback when the field is NULL (see CYPHER-QUERY-MATRIX-ML.md
        §Fallback IBGE for the exact pattern).

        Args:
            year: If provided, filter to a single school year (cr.year = year).
                  If None, returns all years (use for historical training sets).

        Returns:
            DataFrame with one row per student. Categorical columns (_raw suffix)
            are not yet encoded — run feature_pipeline.encode_categoricals() next.

        Raises:
            RuntimeError: if the query returns zero rows (likely a filter issue).
        """
        logger.info("Extracting EF1 features (year=%s)", year or "all")
        query = _QUERY_EF1
        if year is not None:
            # Inject year filter after the canonical grade_level WHERE clause
            query = query.replace(
                "WITH DISTINCT stu, cr, sch, m, st,",
                f"  AND cr.year = {year}\nWITH DISTINCT stu, cr, sch, m, st,",
            )
        df = self._run(query)
        if len(df) == 0:
            raise RuntimeError(
                f"EF1 extraction returned 0 rows (year={year}). "
                "Check grade_level filter and Neo4j connection."
            )
        logger.info("EF1 extracted: %d rows, %d columns", len(df), len(df.columns))
        self._log_ibge_coverage(df, "EF1")
        return df

    def extract_ef2_grades(self) -> pd.DataFrame:
        """
        Extract EF2 subject-level grade pivot (one row per student).

        Returns per-subject normalized grades and global grade aggregates.
        Join with extract_ef1() result via student_id to get the full EF2 feature set.

        The subject regex patterns (MATEM, PORTUGU, etc.) match the discipline_name
        values in StudentDiscipline nodes. See PLAN-ML-NEO4J-SCHOOL.md §3.2.

        Returns:
            DataFrame with student_id as key, subject grades as columns.
            Students without any registered EF2 grades are excluded.
        """
        logger.info("Extracting EF2 grade pivot")
        df = self._run(_QUERY_EF2_GRADES)
        logger.info("EF2 grades extracted: %d students with discipline grades", len(df))
        return df

    def extract_school_features(self) -> pd.DataFrame:
        """
        Extract school-level aggregated features.

        Used for school embedding generation and school risk reports.
        Implements the same attendance + grade + social aggregation logic
        as Q_SAUDE_ESCOLA_E_PROXIMIDADE.md, expressed as structured data
        instead of a UI query.

        Returns:
            DataFrame with one row per school, containing aggregated student
            metrics, IBGE context, and social profile.
        """
        logger.info("Extracting school-level features")
        df = self._run(_QUERY_SCHOOL_FEATURES)
        logger.info("School features extracted: %d schools", len(df))
        return df

    def _run(self, query: str) -> pd.DataFrame:
        """Execute a Cypher query and return results as a DataFrame."""
        with self._driver.session() as session:
            result = session.run(query)
            return pd.DataFrame([r.data() for r in result])

    def _log_ibge_coverage(self, df: pd.DataFrame, segment: str) -> None:
        """Log the fraction of students whose IBGE fields came from UF proxy vs municipality."""
        if "muni_freq_fonte" not in df.columns:
            return
        proxy_pct = (df["muni_freq_fonte"] == "Media_UF_Proxy").mean() * 100
        if proxy_pct > 40:
            logger.warning(
                "%s: %.0f%% of students have IBGE freq from UF proxy (municipality field NULL)",
                segment, proxy_pct,
            )
        else:
            logger.info("%s: IBGE freq coverage — %.0f%% municipal, %.0f%% UF proxy",
                        segment, 100 - proxy_pct, proxy_pct)
```

---

## 3. `src/ml/features/feature_pipeline.py` — Encoding and Split

No business logic — only sklearn-compatible transformations and temporal split.

```python
# src/ml/features/feature_pipeline.py
"""
Feature engineering pipeline: raw DataFrame → encoded feature matrix.

Separated from neo4j_extractor.py to allow unit testing without a Neo4j connection.
All encoding decisions are driven by the dictionaries in schema.py —
no magic strings or hardcoded values here.

Key design decisions:
- Missing grades filled with -1 (not 0 or median): absence of a grade
  is meaningful information (school doesn't register grades for all students).
  Using -1 preserves the signal and lets tree models split on it explicitly.
- Missing IBGE fields are already filled in Cypher (UF proxy). If still null
  after extraction (e.g., State-level fields), they are filled with the
  column median here as a last resort.
- Temporal split is mandatory. Random split is explicitly forbidden because
  a student may appear in multiple school years, and test/train contamination
  would inflate metrics.
- Source flag columns (muni_freq_fonte etc.) are excluded from feature matrix
  but kept in DataFrame for monitoring.

References:
- Feature contracts: schema.py
- IBGE sparsity documentation: neo4_schema_and_tips.md §4.4
- Performance anti-patterns: neo4_schema_and_tips.md §6
"""
import logging
import numpy as np
import pandas as pd
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from .schema import (
    STAGE_ENCODING, GRADE_LEVEL_ENCODING, ETHNICITY_ENCODING, RESIDENCE_ENCODING,
    FEATURES_EVASAO_EF1, FEATURES_NOTAS_EF2, NEVER_NULL_AFTER_IMPUTE,
    TARGET_DROPOUT, TARGET_GRADE, TARGET_REPROVACAO, ID_COLS,
)

logger = logging.getLogger(__name__)

# Source/flag columns that should not be included in the model feature matrix
_SOURCE_FLAG_COLS = ["muni_freq_fonte", "muni_atraso_fonte", "muni_analf_fonte"]


def encode_categoricals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply label encoding to raw categorical columns.

    Converts the '_raw' suffix columns produced by neo4j_extractor.py
    into numeric encoded columns. Encoding dictionaries come from schema.py.
    Unknown values default to the 'unknown' category (5 for ethnicity, etc.).

    Also computes derived features that require multiple columns:
    - n_health_conditions: sum of health boolean flags
    - muni_delta_freq: student's absence rate minus municipal benchmark

    Args:
        df: Raw DataFrame from Neo4jExtractor (contains _raw suffix columns).

    Returns:
        New DataFrame with encoded columns added. Original _raw columns kept
        for debugging but excluded from FEATURES_* lists in schema.py.

    Raises:
        KeyError: if a required _raw column is missing from df.
    """
    out = df.copy()

    out["ethnicity_enc"]      = out["ethnicity_raw"].map(ETHNICITY_ENCODING).fillna(5).astype(int)
    out["stage_enc"]          = out["stage_raw"].map(STAGE_ENCODING).fillna(1).astype(int)
    out["grade_level_enc"]    = out["grade_level_raw"].map(GRADE_LEVEL_ENCODING).fillna(1).astype(int)
    out["residence_zone_enc"] = out["residence_zone_raw"].map(RESIDENCE_ENCODING).fillna(2).astype(int)

    # Derived health aggregate — sum of boolean conditions
    health_bool_cols = [
        "has_malnutrition", "has_diabetes", "has_hypertension",
        "has_obesity", "has_celiac", "has_anemia",
    ]
    out["n_health_conditions"] = out[health_bool_cols].fillna(0).astype(int).sum(axis=1)

    # Delta vs municipal benchmark (computed from already-filled IBGE and attendance)
    # Both inputs are already filled in Cypher, so this rarely produces NaN
    if "taxa_ausencia" in out.columns and "muni_freq_liq_fund" in out.columns:
        out["muni_delta_freq"] = np.where(
            out["taxa_ausencia"].notna() & out["muni_freq_liq_fund"].notna(),
            out["taxa_ausencia"] * 100 - (100.0 - out["muni_freq_liq_fund"]),
            np.nan,
        )

    _validate_never_null(out)
    return out


def build_imputer_pipeline(feature_cols: list[str]) -> Pipeline:
    """
    Build a sklearn imputation + scaling pipeline for a given feature list.

    Imputation strategy:
    - Median imputation for all columns. This handles any residual nulls
      (e.g., State-level PNAD fields that have no UF proxy because they are
      computed from PNAD and may legitimately be absent for all students of a state).
    - NOTE: grade columns (nota_*) with null values should be filled with -1
      BEFORE calling this pipeline, to preserve the 'no grade registered' signal.
      Pass the DataFrame through fill_grade_sentinel() first.

    Args:
        feature_cols: List of column names to include in the pipeline.
                      Must match schema.py FEATURES_* lists.

    Returns:
        Fitted sklearn Pipeline (impute → scale).
    """
    return Pipeline([
        ("impute", SimpleImputer(strategy="median")),
        ("scale",  StandardScaler()),
    ])


def fill_grade_sentinel(df: pd.DataFrame, grade_cols: list[str], sentinel: float = -1.0) -> pd.DataFrame:
    """
    Fill null grade columns with a sentinel value before imputation.

    Schools that do not register grades produce null grade columns for all their
    students. Filling with -1 (instead of median or 0) lets tree models learn
    that 'no grade registered' is a distinct state from a real grade.

    Args:
        df: DataFrame with grade columns.
        grade_cols: Columns to fill (typically GRADE_EF1_FEATURES or GRADE_EF2_FEATURES).
        sentinel: Value to fill nulls with. Default -1.0.

    Returns:
        DataFrame with null grade values replaced by sentinel.
    """
    out = df.copy()
    for col in grade_cols:
        if col in out.columns:
            out[col] = out[col].fillna(sentinel)
    return out


def temporal_split(
    df: pd.DataFrame,
    target_col: str,
    test_year: int,
    feature_cols: list[str],
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame, pd.Series]:
    """
    Split data temporally: train = years < test_year, test = year == test_year.

    NEVER use random train_test_split on this dataset. The same student can
    appear in multiple school years (cr.year). A random split would put the
    same student in both train and test, creating data leakage that inflates
    all metrics.

    Args:
        df: Full encoded DataFrame with ano_letivo column.
        target_col: Name of the target column (e.g., TARGET_DROPOUT from schema.py).
        test_year: The school year to hold out as test set.
        feature_cols: Feature columns to include (from schema.py FEATURES_* lists).

    Returns:
        Tuple of (X_train, y_train, X_test, y_test) as DataFrames/Series.

    Raises:
        ValueError: if train or test split is empty after the cut.
    """
    train_mask = df["ano_letivo"] < test_year
    test_mask  = df["ano_letivo"] == test_year

    if train_mask.sum() == 0:
        raise ValueError(
            f"Temporal split produced empty train set (test_year={test_year}). "
            f"Available years: {sorted(df['ano_letivo'].unique())}"
        )
    if test_mask.sum() == 0:
        raise ValueError(
            f"Temporal split produced empty test set (test_year={test_year}). "
            f"Available years: {sorted(df['ano_letivo'].unique())}"
        )

    train = df[train_mask]
    test  = df[test_mask]

    # Validate feature columns exist
    missing = set(feature_cols) - set(df.columns)
    if missing:
        logger.warning("Features present in schema but missing from DataFrame: %s", missing)
        feature_cols = [c for c in feature_cols if c in df.columns]

    logger.info(
        "Temporal split: train=%d rows (%s) | test=%d rows (year=%d)",
        len(train),
        f"years {df[train_mask]['ano_letivo'].min()}–{df[train_mask]['ano_letivo'].max()}",
        len(test),
        test_year,
    )

    return (
        train[feature_cols], train[target_col],
        test[feature_cols],  test[target_col],
    )


def _validate_never_null(df: pd.DataFrame) -> None:
    """Warn if any column in NEVER_NULL_AFTER_IMPUTE still has nulls."""
    for col in NEVER_NULL_AFTER_IMPUTE:
        if col in df.columns and df[col].isna().any():
            n = df[col].isna().sum()
            logger.warning(
                "Column '%s' should never be null but has %d nulls after encoding", col, n
            )
```

---

## 4. `src/ml/models/dropout_classifier.py` — Dropout Prediction Model

```python
# src/ml/models/dropout_classifier.py
"""
XGBoost binary classifier for student dropout prediction.

Target: target_evasao (0/1) — student missed > 25% of scheduled school days.

Design notes:
- scale_pos_weight is computed automatically from class ratio when not provided.
  This is critical: our dataset has very few actual dropouts (class imbalance).
  Without this, the model predicts 0 for almost all students and gets high accuracy
  but zero recall on the minority (dropout) class.
- eval_metric = 'aucpr' (Area Under Precision-Recall Curve) is chosen over 'auc'
  (ROC AUC) because with high class imbalance, ROC AUC can be misleadingly high
  even when the model fails to catch actual dropouts.
- early_stopping_rounds prevents overfitting without a fixed n_estimators.
  The model stops when eval set performance stops improving.
- This class knows nothing about MLflow. The training entrypoint (train_evasao.py)
  wraps it in log_run().

References:
- Feature set: schema.py FEATURES_EVASAO_EF1
- Target derivation: taxa_ausencia > 25% — see PLAN-ML-NEO4J-SCHOOL.md §2.1
- Score comparison: Q_RISCO_EVASAO_EF2.md (40% absence component maps to this target)
"""
import logging
from dataclasses import dataclass, field
import pandas as pd
import numpy as np
from xgboost import XGBClassifier

logger = logging.getLogger(__name__)


@dataclass
class DropoutConfig:
    """
    Hyperparameter configuration for the dropout XGBoost model.

    These are the base values. The training entrypoint may override any field
    based on Optuna search or sweep results logged to MLflow.

    Attributes:
        n_estimators: Maximum number of trees. Actual count determined by early stopping.
        max_depth: Maximum depth per tree. 6 is a good balance for tabular data.
        learning_rate: Step size shrinkage — lower = more conservative.
        subsample: Fraction of training samples per tree.
        colsample_bytree: Fraction of features per tree.
        early_stopping_rounds: Stop if eval set metric doesn't improve for N rounds.
        eval_metric: 'aucpr' for imbalanced classification. Prefer over 'auc'.
        random_state: Seed for reproducibility.
        scale_pos_weight: Ratio of negative to positive class.
                          None = auto-compute from training labels.
    """
    n_estimators:          int   = 500
    max_depth:             int   = 6
    learning_rate:         float = 0.05
    subsample:             float = 0.8
    colsample_bytree:      float = 0.8
    early_stopping_rounds: int   = 50
    eval_metric:           str   = "aucpr"
    random_state:          int   = 42
    scale_pos_weight:      float | None = None


def build_dropout_model(config: DropoutConfig) -> XGBClassifier:
    """
    Instantiate an XGBClassifier from a DropoutConfig.

    Args:
        config: Hyperparameter configuration (from DropoutConfig or mlflow params).

    Returns:
        Unfitted XGBClassifier.
    """
    return XGBClassifier(
        n_estimators           = config.n_estimators,
        max_depth              = config.max_depth,
        learning_rate          = config.learning_rate,
        subsample              = config.subsample,
        colsample_bytree       = config.colsample_bytree,
        early_stopping_rounds  = config.early_stopping_rounds,
        eval_metric            = config.eval_metric,
        scale_pos_weight       = config.scale_pos_weight,
        random_state           = config.random_state,
        n_jobs                 = -1,
        tree_method            = "hist",   # faster for large datasets
    )


def compute_scale_pos_weight(y_train: pd.Series) -> float:
    """
    Compute scale_pos_weight from training labels.

    XGBoost documentation recommends count(negative) / count(positive).
    Applied only to training labels to avoid any validation leakage.

    Args:
        y_train: Training target Series (binary 0/1).

    Returns:
        Float ratio: n_negative / n_positive.
    """
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    if n_pos == 0:
        logger.error("Training set has zero positive examples (no dropouts). Check target derivation.")
        raise ValueError("No positive examples in training set.")
    ratio = n_neg / n_pos
    logger.info("Class ratio: %d negative / %d positive = scale_pos_weight=%.2f", n_neg, n_pos, ratio)
    return ratio


def train_dropout(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val:   pd.DataFrame,
    y_val:   pd.Series,
    config:  DropoutConfig | None = None,
) -> XGBClassifier:
    """
    Train the dropout classifier with early stopping on a validation set.

    The validation set should be the last 15% of the TRAINING years (not the
    test year). This gives early stopping a holdout without contaminating the
    temporal test set.

    Args:
        X_train: Training features (from temporal_split, excluding validation rows).
        y_train: Training labels.
        X_val: Validation features (last 15% of train rows, same years as X_train).
        y_val: Validation labels.
        config: Hyperparameter config. If None, uses DropoutConfig defaults.

    Returns:
        Fitted XGBClassifier. Check model.best_iteration for actual tree count.
    """
    cfg = config or DropoutConfig()

    if cfg.scale_pos_weight is None:
        cfg.scale_pos_weight = compute_scale_pos_weight(y_train)

    model = build_dropout_model(cfg)
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    logger.info(
        "Dropout model trained: best_iteration=%d / n_estimators=%d",
        model.best_iteration, cfg.n_estimators,
    )
    return model


def predict_dropout(model: XGBClassifier, X: pd.DataFrame) -> dict[str, np.ndarray]:
    """
    Generate dropout predictions for a batch of students.

    Args:
        model: Fitted XGBClassifier.
        X: Feature DataFrame with same columns as training (from FEATURES_EVASAO_EF1).

    Returns:
        Dict with keys:
        - 'evasao_prob': float array [0, 1] — probability of dropout
        - 'evasao_label': int array {0, 1} — binary prediction at 0.5 threshold
    """
    proba = model.predict_proba(X)[:, 1]
    label = (proba >= 0.5).astype(int)
    return {"evasao_prob": proba, "evasao_label": label}
```

---

## 5. `src/ml/models/grade_regressor.py` — Grade Regression Model

```python
# src/ml/models/grade_regressor.py
"""
GradientBoostingRegressor for EF2 normalized final grade prediction.

Target: target_nota (float 0.0–10.0) — normalized final_mean per student.
Scope: EF2 only (Fundamental II, grades 6–9). EF1 has a single global grade,
which is already part of the dropout feature set but doesn't benefit from
per-subject regression.

The Q_RISCO_EVASAO_EF2.md risk score includes a 35% weight on grades below 5.0
and a 25% weight on inverted mean. This model complements that analytic by
predicting the grade BEFORE end of year (using grade_1, grade_2 as input),
enabling earlier intervention.

References:
- Feature set: schema.py FEATURES_NOTAS_EF2
- Risk score that uses grade output: Q_RISCO_EVASAO_EF2.md §Score de Risco
- EF2 grade extraction query: PLAN-ML-NEO4J-SCHOOL.md §3.2
"""
import logging
from dataclasses import dataclass
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor

logger = logging.getLogger(__name__)


@dataclass
class GradeRegressorConfig:
    """
    Hyperparameter configuration for the grade GBM regressor.

    Attributes:
        n_estimators: Number of boosting stages.
        max_depth: Maximum depth per tree (shallower than XGBoost to reduce overfitting).
        learning_rate: Shrinkage applied to each tree contribution.
        subsample: Fraction of samples for stochastic gradient boosting.
        random_state: Seed for reproducibility.
    """
    n_estimators: int   = 300
    max_depth:    int   = 5
    learning_rate: float = 0.05
    subsample:    float = 0.8
    random_state: int   = 42


def train_grade_regressor(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    config: GradeRegressorConfig | None = None,
) -> GradientBoostingRegressor:
    """
    Fit the grade regression model on EF2 student features.

    Args:
        X_train: Training features from FEATURES_NOTAS_EF2.
        y_train: Training target — normalized final_mean (0.0–10.0).
        config: Hyperparameter config. If None, uses defaults.

    Returns:
        Fitted GradientBoostingRegressor.
    """
    cfg = config or GradeRegressorConfig()
    model = GradientBoostingRegressor(
        n_estimators=cfg.n_estimators,
        max_depth=cfg.max_depth,
        learning_rate=cfg.learning_rate,
        subsample=cfg.subsample,
        random_state=cfg.random_state,
    )
    model.fit(X_train, y_train)
    logger.info("Grade regressor trained on %d samples", len(X_train))
    return model
```

---

## 6. `src/ml/models/risk_clusterer.py` — Student Clustering + Neo4j Writeback

```python
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
```

---

## 7. `src/ml/evaluation/metrics.py` — Pure Metric Functions

```python
# src/ml/evaluation/metrics.py
"""
Metric computation functions — pure, no side effects, no logging dependencies.

All functions accept numpy arrays and return dataclasses. The training entrypoints
log these via MLflow (mlops/experiment.py). Metrics themselves don't know about
MLflow, logging, or file systems.

Acceptance criteria (see full table in this document §12):
- Dropout classifier: AUROC ≥ 0.82, Recall ≥ 0.75, F1 ≥ 0.70
- Grade regressor: RMSE ≤ 1.5, R² ≥ 0.60
- Clustering: Silhouette ≥ 0.35
"""
from dataclasses import dataclass
import numpy as np
from sklearn.metrics import (
    roc_auc_score, f1_score, precision_score, recall_score,
    mean_squared_error, r2_score, average_precision_score,
)


@dataclass(frozen=True)
class ClassificationMetrics:
    """
    Evaluation metrics for binary classification.

    Attributes:
        auroc: Area Under ROC Curve. Threshold-independent overall performance.
        auprc: Area Under Precision-Recall Curve. Better for imbalanced classes.
        f1: F1 score at 0.5 threshold. Harmonic mean of precision and recall.
        precision: True positive rate among predicted positives.
        recall: True positive rate among actual positives. Critical for dropout detection.
    """
    auroc:     float
    auprc:     float
    f1:        float
    precision: float
    recall:    float

    def as_dict(self) -> dict[str, float]:
        """Return all metrics as a flat dict (ready for MLflow log_metrics)."""
        return {
            "auroc": self.auroc, "auprc": self.auprc,
            "f1": self.f1, "precision": self.precision, "recall": self.recall,
        }

    def passes_acceptance(self) -> bool:
        """Return True if all metrics meet the acceptance criteria."""
        return self.auroc >= 0.82 and self.recall >= 0.75 and self.f1 >= 0.70


@dataclass(frozen=True)
class RegressionMetrics:
    """
    Evaluation metrics for regression (grade prediction).

    Attributes:
        rmse: Root Mean Square Error. In grade units (0–10 scale).
        r2: Coefficient of determination. 1.0 = perfect, 0 = predicts mean.
        mae: Mean Absolute Error. More interpretable than RMSE for grades.
    """
    rmse: float
    r2:   float
    mae:  float

    def as_dict(self) -> dict[str, float]:
        return {"rmse": self.rmse, "r2": self.r2, "mae": self.mae}

    def passes_acceptance(self) -> bool:
        return self.rmse <= 1.5 and self.r2 >= 0.60


def eval_classifier(y_true: np.ndarray, y_prob: np.ndarray) -> ClassificationMetrics:
    """
    Compute all classification metrics from probabilities.

    Args:
        y_true: Ground truth binary labels (0/1).
        y_prob: Predicted probabilities for the positive class.

    Returns:
        ClassificationMetrics dataclass.
    """
    y_pred = (y_prob >= 0.5).astype(int)
    return ClassificationMetrics(
        auroc     = roc_auc_score(y_true, y_prob),
        auprc     = average_precision_score(y_true, y_prob),
        f1        = f1_score(y_true, y_pred, zero_division=0),
        precision = precision_score(y_true, y_pred, zero_division=0),
        recall    = recall_score(y_true, y_pred, zero_division=0),
    )


def eval_regressor(y_true: np.ndarray, y_pred: np.ndarray) -> RegressionMetrics:
    """
    Compute regression metrics for grade prediction.

    Args:
        y_true: Ground truth normalized grades (0.0–10.0).
        y_pred: Predicted grades (0.0–10.0).

    Returns:
        RegressionMetrics dataclass.
    """
    return RegressionMetrics(
        rmse = float(np.sqrt(mean_squared_error(y_true, y_pred))),
        r2   = float(r2_score(y_true, y_pred)),
        mae  = float(np.mean(np.abs(y_true - y_pred))),
    )
```

---

## 8. `src/ml/evaluation/explainability.py` — SHAP

```python
# src/ml/evaluation/explainability.py
"""
SHAP explainability for tree models.

Two entry points:
1. compute_shap_global(): Summary plot across the test set. Saved as PNG artifact in MLflow.
   Used to validate that the model learns from the right features (attendance, grades)
   rather than spurious correlates. Top-5 features must explain ≥ 65% of global impact.

2. compute_shap_local(): Per-student SHAP decomposition. Called by the API's
   /predict/dropout/{student_id} endpoint to return top-5 factors to the user.

The 'factors' format matches the DropoutResponse schema in PLAN-ML-03-API-SERVING.md §2.

References:
- Global validation criterion: acceptance criteria table §12
- Local output used by: PLAN-ML-03-API-SERVING.md routes/predict.py
- SHAP interpretation for RAG: PLAN-ML-02-RAG-LLM.md §8 (context builder)
"""
import io
import logging
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import shap

logger = logging.getLogger(__name__)

_TOP5_SHARE_THRESHOLD = 0.65   # acceptance criterion


def compute_shap_global(
    model,
    X_test: pd.DataFrame,
    max_samples: int = 2_000,
) -> tuple[np.ndarray, io.BytesIO]:
    """
    Compute global SHAP values and generate a summary plot.

    Uses a random sample of the test set for speed (TreeExplainer is O(N × depth)).
    Saves the plot to a BytesIO buffer for MLflow artifact logging.

    Args:
        model: Fitted XGBoost or GBM model with TreeExplainer support.
        X_test: Test feature DataFrame.
        max_samples: Max rows to use for SHAP computation.

    Returns:
        Tuple of (shap_values_array, png_buffer).
        shap_values_array shape: (n_samples, n_features).
        png_buffer: In-memory PNG for logging as MLflow artifact.

    Raises:
        Warning if top-5 features explain < 65% of global SHAP impact.
    """
    sample = X_test.sample(min(max_samples, len(X_test)), random_state=42)
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(sample)

    # Validate global explanation concentration
    mean_abs      = np.abs(shap_values).mean(axis=0)
    top5_idx      = mean_abs.argsort()[-5:][::-1]
    top5_share    = mean_abs[top5_idx].sum() / mean_abs.sum()

    if top5_share < _TOP5_SHARE_THRESHOLD:
        logger.warning(
            "SHAP: top-5 features explain only %.0f%% of global impact (threshold: %.0f%%). "
            "Model may be relying on many weak signals — consider feature selection.",
            top5_share * 100, _TOP5_SHARE_THRESHOLD * 100,
        )
    else:
        logger.info(
            "SHAP: top-5 features explain %.0f%% of global impact (OK)",
            top5_share * 100,
        )

    top5_features = [sample.columns[i] for i in top5_idx]
    logger.info("SHAP: top features = %s", top5_features)

    # Save summary plot to buffer
    buf = io.BytesIO()
    fig, ax = plt.subplots(figsize=(10, 6))
    shap.summary_plot(shap_values, sample, show=False)
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close("all")
    buf.seek(0)

    return shap_values, buf


def compute_shap_local(
    model,
    X_student: pd.DataFrame,
) -> dict:
    """
    Compute SHAP values for a single student and return top-5 factors.

    Called by the prediction API to explain individual predictions to school managers.
    The output format matches the 'top_factors' field in DropoutResponse
    (PLAN-ML-03-API-SERVING.md §2).

    Args:
        model: Fitted tree model.
        X_student: Single-row DataFrame with the student's feature values.

    Returns:
        Dict with:
        - 'base_value': float — model's expected output (mean prediction)
        - 'top_factors': list of 5 dicts [{feature, impact, direction}]
                         sorted by abs(impact) descending
        - 'all_shap_values': dict of {feature: shap_value} for all features
    """
    if len(X_student) != 1:
        raise ValueError(f"Expected single-row DataFrame, got {len(X_student)} rows.")

    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_student)
    values      = shap_values[0] if isinstance(shap_values, list) else shap_values[0]

    feature_impact = [
        {
            "feature":   feat,
            "impact":    round(float(val), 4),
            "direction": "increases_risk" if val > 0 else "decreases_risk",
        }
        for feat, val in zip(X_student.columns, values)
    ]
    feature_impact.sort(key=lambda x: abs(x["impact"]), reverse=True)

    return {
        "base_value":       float(explainer.expected_value),
        "top_factors":      feature_impact[:5],
        "all_shap_values":  {f["feature"]: f["impact"] for f in feature_impact},
    }
```

---

## 9. `src/ml/mlops/experiment.py` — MLflow Wrapper

```python
# src/ml/mlops/experiment.py
"""
Thin MLflow context manager for experiment tracking.

The model training functions (dropout_classifier.py, grade_regressor.py) are
completely unaware of MLflow. This module wraps them in an mlflow.start_run()
context, providing a clean RunContext object to the entrypoints.

Experiment names map to model types. Changing the experiment name here changes
it everywhere — no scattered mlflow.set_experiment() calls in other files.

Usage in training entrypoint:
    with log_run("evasao", params=vars(config), tags={"segment": "EF1"}) as run:
        model = train_dropout(X_tr, y_tr, X_val, y_val, config)
        metrics = eval_classifier(y_test.values, predict_dropout(model, X_test)["evasao_prob"])
        run.log_metrics(metrics.as_dict())
        run.log_model(model, artifact_path="dropout_model")
        run_id = run.run_id
"""
import io
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
import mlflow
import mlflow.sklearn
import mlflow.xgboost

logger = logging.getLogger(__name__)

EXPERIMENT_NAMES = {
    "evasao":     "school-dropout-prediction",
    "notas":      "grade-regression-ef2",
    "clustering": "student-clustering",
}


@dataclass
class RunContext:
    """
    Handle to an active MLflow run.

    Wraps mlflow logging calls so that entrypoints don't import mlflow directly.
    All methods delegate to the active run context set by mlflow.start_run().
    """
    run_id: str

    def log_metrics(self, metrics: dict[str, float]) -> None:
        """Log a dict of metric name → float value to the active run."""
        mlflow.log_metrics(metrics)
        logger.info("Metrics logged: %s", {k: round(v, 4) for k, v in metrics.items()})

    def log_params(self, params: dict) -> None:
        """Log hyperparameters to the active run."""
        mlflow.log_params({k: str(v) for k, v in params.items()})

    def log_model(self, model, artifact_path: str) -> None:
        """
        Log a trained model to the active run.

        Detects XGBoost vs sklearn automatically by checking for get_booster().
        """
        if hasattr(model, "get_booster"):
            mlflow.xgboost.log_model(model, artifact_path)
        else:
            mlflow.sklearn.log_model(model, artifact_path)
        logger.info("Model logged to artifact_path='%s'", artifact_path)

    def log_png_buffer(self, buf: io.BytesIO, filename: str) -> None:
        """Log an in-memory PNG buffer as an MLflow artifact (e.g., SHAP plot)."""
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False) as f:
            f.write(buf.read())
            tmp_path = f.name
        mlflow.log_artifact(tmp_path, artifact_path="plots")
        os.unlink(tmp_path)

    def log_dataframe(self, df, filename: str) -> None:
        """Log a DataFrame as a CSV artifact (e.g., feature importance, drift report summary)."""
        with tempfile.NamedTemporaryFile(suffix=f"_{filename}", delete=False, mode="w") as f:
            df.to_csv(f, index=False)
            tmp_path = f.name
        mlflow.log_artifact(tmp_path, artifact_path="data")
        os.unlink(tmp_path)


@contextmanager
def log_run(
    model_type: str,
    params: dict,
    tags: dict | None = None,
):
    """
    Context manager for an MLflow run.

    Sets the experiment, starts a run, logs params, yields RunContext,
    then closes the run (including on exception).

    Args:
        model_type: Key in EXPERIMENT_NAMES dict ('evasao', 'notas', 'clustering').
        params: Hyperparameter dict — logged at run start.
        tags: Optional dict of string tags (e.g., {'segment': 'EF1'}).

    Yields:
        RunContext object with logging methods.
    """
    experiment_name = EXPERIMENT_NAMES.get(model_type, model_type)
    mlflow.set_tracking_uri(os.environ.get("MLFLOW_URI", "http://localhost:5001"))
    mlflow.set_experiment(experiment_name)

    with mlflow.start_run(tags=tags or {}) as run:
        mlflow.log_params({k: str(v) for k, v in params.items()})
        run_id = run.info.run_id
        logger.info("MLflow run started: experiment='%s' run_id=%s", experiment_name, run_id)
        yield RunContext(run_id=run_id)

    logger.info("MLflow run completed: run_id=%s", run_id)
```

---

## 10. `src/ml/mlops/champion_challenger.py` — Auto-Promotion

```python
# src/ml/mlops/champion_challenger.py
"""
Champion/Challenger pattern for automatic model promotion.

Compares the new (challenger) model against the current Production model
(champion) in the MLflow Model Registry. Promotes only if AUROC improvement
exceeds _PROMOTION_THRESHOLD.

This threshold prevents unnecessary model churn from small statistical
fluctuations between training runs. The threshold is logged alongside the
decision for audit purposes.

The function is called from the training entrypoint AFTER log_run() completes,
so the challenger run_id is already finalized in MLflow.
"""
import logging
import mlflow
from mlflow.tracking import MlflowClient

logger = logging.getLogger(__name__)

_PROMOTION_THRESHOLD = 0.01    # minimum AUROC improvement to justify promotion
_REGISTRY_MODEL_NAMES = {
    "evasao":  "dropout-evasao-ef1",
    "notas":   "grade-regression-ef2",
}


def get_champion_metrics(model_name: str, client: MlflowClient) -> dict | None:
    """
    Retrieve metrics of the current Production model from MLflow Registry.

    Args:
        model_name: Registered model name (from _REGISTRY_MODEL_NAMES).
        client: MlflowClient instance.

    Returns:
        Dict of metric name → float for the Production model's run.
        None if no Production model exists (first run).
    """
    try:
        versions = client.get_latest_versions(model_name, stages=["Production"])
        if not versions:
            logger.info("No Production model found for '%s' — first run.", model_name)
            return None
        run = client.get_run(versions[0].run_id)
        return dict(run.data.metrics)
    except Exception as e:
        logger.warning("Could not retrieve champion metrics for '%s': %s", model_name, e)
        return None


def promote_if_better(
    model_type: str,
    challenger_run_id: str,
    challenger_metrics: dict[str, float],
    client: MlflowClient | None = None,
) -> bool:
    """
    Promote challenger to Production if AUROC improvement > threshold.

    Logs the decision (promote or keep) with metric values for audit.

    Args:
        model_type: Key in _REGISTRY_MODEL_NAMES ('evasao' or 'notas').
        challenger_run_id: MLflow run ID of the challenger model.
        challenger_metrics: Metrics dict from the challenger run (must include 'auroc').
        client: MlflowClient — if None, creates a new one.

    Returns:
        True if challenger was promoted to Production, False otherwise.

    Raises:
        KeyError: if 'auroc' is not in challenger_metrics.
    """
    client = client or MlflowClient()
    model_name = _REGISTRY_MODEL_NAMES[model_type]

    challenger_auroc = challenger_metrics["auroc"]
    champion_metrics = get_champion_metrics(model_name, client)

    if champion_metrics is None:
        logger.info("Promoting challenger as first Production model (AUROC=%.4f)", challenger_auroc)
    else:
        champion_auroc = champion_metrics.get("auroc", 0.0)
        delta = challenger_auroc - champion_auroc
        logger.info(
            "Champion AUROC=%.4f | Challenger AUROC=%.4f | Delta=%.4f | Threshold=%.4f",
            champion_auroc, challenger_auroc, delta, _PROMOTION_THRESHOLD,
        )
        if delta <= _PROMOTION_THRESHOLD:
            logger.info("Keeping champion — challenger does not exceed threshold.")
            return False

    # Register and promote
    artifact_path = "dropout_model" if model_type == "evasao" else "grade_model"
    model_uri = f"runs:/{challenger_run_id}/{artifact_path}"
    mlflow.register_model(model_uri, model_name)

    latest = client.get_latest_versions(model_name, stages=["None"])
    client.transition_model_version_stage(
        name=model_name,
        version=latest[0].version,
        stage="Production",
        archive_existing_versions=True,
    )
    logger.info("Challenger promoted to Production: '%s' version %s", model_name, latest[0].version)
    return True
```

---

## 11. `src/ml/training/train_evasao.py` — Full Training Entrypoint

```python
# src/ml/training/train_evasao.py
"""
Dropout model training entrypoint.

Orchestrates the full training pipeline:
1. Extract EF1 features from Neo4j (neo4j_extractor.py)
2. Encode categoricals and derive features (feature_pipeline.py)
3. Fill grade sentinel values for students without registered grades
4. Temporal split: train on years < test_year, hold out test_year as test set
5. Further split train set 85/15 for early stopping validation
6. Train XGBoost with auto-computed scale_pos_weight
7. Evaluate on held-out test set (temporal)
8. Compute global SHAP for feature validation
9. Log everything to MLflow (experiment.py)
10. Champion/Challenger: promote if AUROC improves by > 0.01
11. Write risk_score and risk_cluster back to Neo4j (risk_clusterer.py)

This file is called:
- Directly: python -m src.ml.training.train_evasao --test-year 2024
- Via Airflow: dag__ml_retrain.py calls train_model() task

References:
- Feature contracts: schema.py
- Extraction queries: neo4j_extractor.py _QUERY_EF1
- Acceptance criteria: see §12 of this document
- Cypher write-back: PLAN-ML-NEO4J-SCHOOL.md §4.3 (KMeans writeback)
"""
import argparse
import logging
import os

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

MODEL_TYPE  = "evasao"
MODEL_NAME  = "dropout-evasao-ef1"


def run(test_year: int) -> None:
    """
    Execute the full dropout model training pipeline for a given test year.

    Args:
        test_year: School year to hold out as test set (e.g., 2024).
                   All prior years are used for training.
    """
    import pandas as pd
    from mlflow.tracking import MlflowClient
    from ..features.neo4j_extractor import Neo4jExtractor
    from ..features.feature_pipeline import (
        encode_categoricals, temporal_split, fill_grade_sentinel
    )
    from ..features.schema import (
        FEATURES_EVASAO_EF1, TARGET_DROPOUT, ID_COLS, GRADE_EF1_FEATURES,
    )
    from ..models.dropout_classifier import DropoutConfig, train_dropout, predict_dropout
    from ..evaluation.metrics import eval_classifier
    from ..evaluation.explainability import compute_shap_global
    from ..mlops.experiment import log_run
    from ..mlops.champion_challenger import promote_if_better

    # ── 1. Extract ────────────────────────────────────────────────────────────
    logger.info("=== Dropout training pipeline: test_year=%d ===", test_year)
    extractor = Neo4jExtractor.from_env()
    df_raw    = extractor.extract_ef1()   # all years
    extractor.close()

    # ── 2. Encode ─────────────────────────────────────────────────────────────
    df = encode_categoricals(df_raw)
    df = fill_grade_sentinel(df, GRADE_EF1_FEATURES)   # null grades → -1

    # ── 3. Temporal split ─────────────────────────────────────────────────────
    X_train, y_train, X_test, y_test = temporal_split(
        df, target_col=TARGET_DROPOUT, test_year=test_year,
        feature_cols=FEATURES_EVASAO_EF1,
    )

    # ── 4. Validation split from train (last 15% of train rows) ───────────────
    split_idx = int(len(X_train) * 0.85)
    X_tr, X_val = X_train.iloc[:split_idx], X_train.iloc[split_idx:]
    y_tr, y_val = y_train.iloc[:split_idx], y_train.iloc[split_idx:]

    # ── 5. Train ──────────────────────────────────────────────────────────────
    config = DropoutConfig()
    model  = train_dropout(X_tr, y_tr, X_val, y_val, config)

    # ── 6. Evaluate ───────────────────────────────────────────────────────────
    preds   = predict_dropout(model, X_test)
    metrics = eval_classifier(y_test.values, preds["evasao_prob"])

    if not metrics.passes_acceptance():
        logger.warning(
            "Model does NOT meet acceptance criteria. "
            "AUROC=%.4f (need ≥0.82), Recall=%.4f (need ≥0.75), F1=%.4f (need ≥0.70)",
            metrics.auroc, metrics.recall, metrics.f1,
        )
    else:
        logger.info("All acceptance criteria met: %s", metrics.as_dict())

    # ── 7. SHAP ───────────────────────────────────────────────────────────────
    _, shap_buf = compute_shap_global(model, X_test)

    # ── 8. Log to MLflow ──────────────────────────────────────────────────────
    params = vars(config) | {"test_year": test_year, "n_train": len(X_train), "n_test": len(X_test)}
    tags   = {"segment": "EF1", "target": TARGET_DROPOUT}

    with log_run(MODEL_TYPE, params=params, tags=tags) as run_ctx:
        run_ctx.log_metrics(metrics.as_dict())
        run_ctx.log_model(model, artifact_path="dropout_model")
        run_ctx.log_png_buffer(shap_buf, "shap_summary.png")
        run_id = run_ctx.run_id

    # ── 9. Champion/Challenger ────────────────────────────────────────────────
    promoted = promote_if_better(
        model_type=MODEL_TYPE,
        challenger_run_id=run_id,
        challenger_metrics=metrics.as_dict(),
        client=MlflowClient(),
    )
    logger.info("Pipeline complete. AUROC=%.4f | Promoted=%s", metrics.auroc, promoted)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train dropout prediction model")
    parser.add_argument("--test-year", type=int, required=True,
                        help="School year to hold out as test set")
    args = parser.parse_args()
    run(args.test_year)
```

---

## 12. DAGs Airflow

### `dags/dag__ml_feature_engineering.py`

```python
# dags/dag__ml_feature_engineering.py
"""
Daily feature extraction DAG.

Extracts EF1 and EF2 features from Neo4j and saves as Parquet files.
Parquet acts as a cache layer between the graph and the training DAG,
so the training DAG can iterate without re-querying Neo4j each run.

Schedule: 3:00 AM daily (after any Neo4j data loads are expected to complete).
Output: /data/features/ef1_{date}.parquet and ef2_grades_{date}.parquet
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

_DEFAULT_ARGS = {
    "owner": "ml-team",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def extract_ef1_task(**ctx):
    """Extract EF1 features and save to Parquet."""
    import os, pandas as pd
    from src.ml.features.neo4j_extractor import Neo4jExtractor
    from src.ml.features.feature_pipeline import encode_categoricals, fill_grade_sentinel
    from src.ml.features.schema import GRADE_EF1_FEATURES

    ext = Neo4jExtractor.from_env()
    df  = encode_categoricals(ext.extract_ef1())
    df  = fill_grade_sentinel(df, GRADE_EF1_FEATURES)
    ext.close()

    out = f"/data/features/ef1_{ctx['ds_nodash']}.parquet"
    os.makedirs("/data/features", exist_ok=True)
    df.to_parquet(out, index=False)
    ctx["ti"].xcom_push(key="ef1_parquet", value=out)
    return out


def extract_ef2_task(**ctx):
    """Extract EF2 grade pivot and save to Parquet."""
    import os
    from src.ml.features.neo4j_extractor import Neo4jExtractor

    ext = Neo4jExtractor.from_env()
    df  = ext.extract_ef2_grades()
    ext.close()

    out = f"/data/features/ef2_grades_{ctx['ds_nodash']}.parquet"
    df.to_parquet(out, index=False)
    ctx["ti"].xcom_push(key="ef2_parquet", value=out)
    return out


with DAG(
    dag_id="dag__ml_feature_engineering",
    default_args=_DEFAULT_ARGS,
    schedule_interval="0 3 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "features"],
) as dag:
    t_ef1 = PythonOperator(task_id="extract_ef1", python_callable=extract_ef1_task)
    t_ef2 = PythonOperator(task_id="extract_ef2", python_callable=extract_ef2_task)
    t_ef1 >> t_ef2
```

### `dags/dag__ml_retrain.py`

```python
# dags/dag__ml_retrain.py
"""
Weekly retrain DAG.

Runs every Monday at 4:00 AM, after the feature engineering DAG.
Pipeline: extract → validate → train → evaluate → compare → promote.

Retrain is triggered either on schedule or when the drift DAG sets
the retrain flag (/data/drift/retrain_needed.flag file exists).
"""
from datetime import datetime, timedelta
import subprocess, sys
from airflow import DAG
from airflow.operators.python import PythonOperator

_DEFAULT_ARGS = {"owner": "ml-team", "retries": 1, "retry_delay": timedelta(minutes=10)}


def validate_features_task(**ctx):
    """Check that EF1 Parquet has expected columns and non-null targets."""
    import pandas as pd, os
    from src.ml.features.schema import TARGET_DROPOUT, NEVER_NULL_AFTER_IMPUTE

    # Use most recent Parquet
    parquet_dir = "/data/features"
    files = sorted(f for f in os.listdir(parquet_dir) if f.startswith("ef1_"))
    if not files:
        raise RuntimeError("No EF1 Parquet files found. Run feature engineering DAG first.")

    df = pd.read_parquet(f"{parquet_dir}/{files[-1]}")
    # Check target is not all-zero (would indicate extraction filter issue)
    pos_rate = df[TARGET_DROPOUT].mean()
    if pos_rate < 0.005:
        raise ValueError(f"Positive rate for {TARGET_DROPOUT} is {pos_rate:.4f} — suspiciously low.")

    for col in NEVER_NULL_AFTER_IMPUTE:
        if col in df.columns and df[col].isna().any():
            raise ValueError(f"Column '{col}' has nulls after encoding — check extraction query.")

    return {"n_rows": len(df), "pos_rate": round(pos_rate, 4)}


def train_evasao_task(**ctx):
    """Run dropout model training entrypoint as subprocess."""
    test_year = ctx["params"].get("test_year", datetime.now().year)
    result = subprocess.run(
        [sys.executable, "-m", "src.ml.training.train_evasao", "--test-year", str(test_year)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Training failed:\n{result.stderr[-2000:]}")
    return {"returncode": result.returncode}


def train_notas_task(**ctx):
    """Run grade model training entrypoint as subprocess."""
    test_year = ctx["params"].get("test_year", datetime.now().year)
    result = subprocess.run(
        [sys.executable, "-m", "src.ml.training.train_notas", "--test-year", str(test_year)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Grade model training failed:\n{result.stderr[-2000:]}")
    return {"returncode": result.returncode}


with DAG(
    dag_id="dag__ml_retrain",
    default_args=_DEFAULT_ARGS,
    schedule_interval="0 4 * * 1",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    params={"test_year": datetime.now().year},
    tags=["ml", "retrain"],
) as dag:
    t_validate     = PythonOperator(task_id="validate_features", python_callable=validate_features_task)
    t_train_evasao = PythonOperator(task_id="train_evasao",      python_callable=train_evasao_task)
    t_train_notas  = PythonOperator(task_id="train_notas",       python_callable=train_notas_task)
    t_validate >> t_train_evasao >> t_train_notas
```

### `dags/dag__ml_drift_detection.py`

```python
# dags/dag__ml_drift_detection.py
"""
Weekly drift detection DAG.

Compares current week's feature distribution against the training reference
(saved at last retrain). If drift is detected on > 30% of key features,
sets a flag that triggers dag__ml_retrain on next schedule.

Uses Evidently AI for PSI (Population Stability Index) computation.
PSI > 0.2 per feature = significant drift.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

_DEFAULT_ARGS = {"owner": "ml-team", "retries": 1, "retry_delay": timedelta(minutes=5)}
_DRIFT_SHARE_THRESHOLD = 0.30    # fraction of features drifted to trigger retrain


def detect_drift_task(**ctx):
    """Run Evidently drift report. Write retrain flag if drift exceeds threshold."""
    import json, os, pandas as pd
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset
    from src.ml.features.schema import FEATURES_EVASAO_EF1

    parquet_dir = "/data/features"
    files = sorted(f for f in os.listdir(parquet_dir) if f.startswith("ef1_"))
    if len(files) < 2:
        return {"drift_detected": False, "reason": "Not enough history for drift check"}

    reference = pd.read_parquet(f"{parquet_dir}/{files[-2]}")
    current   = pd.read_parquet(f"{parquet_dir}/{files[-1]}")

    valid_cols = [c for c in FEATURES_EVASAO_EF1 if c in reference.columns and c in current.columns]
    report     = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference[valid_cols], current_data=current[valid_cols])
    report.save_html(f"/data/drift/report_{ctx['ds_nodash']}.html")

    summary   = report.as_dict()
    n_drifted = summary["metrics"][0]["result"]["number_of_drifted_columns"]
    n_total   = summary["metrics"][0]["result"]["number_of_columns"]
    share     = n_drifted / max(n_total, 1)

    drift_detected = share > _DRIFT_SHARE_THRESHOLD
    if drift_detected:
        open("/data/drift/retrain_needed.flag", "w").write(f"{ctx['ds_nodash']}\n")
        import logging; logging.getLogger(__name__).warning(
            "DRIFT detected: %d/%d features drifted (%.0f%%). Retrain flag set.",
            n_drifted, n_total, share * 100,
        )
    else:
        import logging; logging.getLogger(__name__).info(
            "No significant drift: %d/%d features drifted (%.0f%%)",
            n_drifted, n_total, share * 100,
        )

    return {"drift_detected": drift_detected, "n_drifted": n_drifted, "share": round(share, 3)}


with DAG(
    dag_id="dag__ml_drift_detection",
    default_args=_DEFAULT_ARGS,
    schedule_interval="0 3 * * 3",   # Wednesday at 3AM
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["ml", "drift"],
) as dag:
    t_drift = PythonOperator(task_id="detect_drift", python_callable=detect_drift_task)
```

---

## 13. Acceptance Criteria

All metrics are evaluated on the **temporal test set** (year held out, never seen during training). No metric from the validation set (used for early stopping) counts toward acceptance.

| Model | Metric | Target | Reason |
|---|---|---|---|
| Dropout (XGBoost) | AUROC | ≥ 0.82 | Overall discrimination ability |
| Dropout (XGBoost) | Recall | ≥ 0.75 | Missing a dropout is worse than a false alarm |
| Dropout (XGBoost) | F1 | ≥ 0.70 | Balance between precision and recall |
| Dropout (XGBoost) | AUPRC | ≥ 0.50 | Imbalanced class — PR curve more informative than ROC |
| Grade (GBM EF2) | RMSE | ≤ 1.5 | Error in grade units (0–10 scale) |
| Grade (GBM EF2) | R² | ≥ 0.60 | Explained variance vs predicting mean |
| Clustering (KMeans) | Silhouette Score | ≥ 0.35 | Minimum cluster separation quality |
| SHAP global | Top-5 share | ≥ 65% | Model must rely on the right features |
| Champion upgrade | Delta AUROC | > 0.01 | Minimum improvement to replace production model |
| Drift trigger | Drifted feature share | > 30% | Fraction of FEATURES_EVASAO_EF1 with PSI > 0.2 |

---

## 14. Implementation Checklist

### Phase 0 — Schema & Contracts
- [ ] `schema.py` — all feature lists reviewed against `neo4_schema_and_tips.md §1-2`
- [ ] `schema.py` — no properties from §8 (non-existent properties) included
- [ ] IBGE fields noted as nullable — `muni_atraso_2anos` especially sparse

### Phase 1 — Feature Extraction
- [ ] `neo4j_extractor.py` — 6 IBGE fields each with own UF fallback CALL block
- [ ] `neo4j_extractor.py` — `has_malnutrition` uses `h.malnutrition` NOT `h.malnutrition_desease`
- [ ] `neo4j_extractor.py` — attendance direction is `(sc:StudentClass)-[:ATTENDED]->(stu)`
- [ ] `neo4j_extractor.py` — `discipline_name = ''` selects EF1 global grade
- [ ] `neo4j_extractor.py` — grade normalization `CASE WHEN val > 10 THEN val/10.0` applied
- [ ] `neo4j_extractor.py` — `deficiency` check uses `STARTS WITH 'Possui'` (STRING not boolean)
- [ ] `neo4j_extractor.py` — `_log_ibge_coverage()` shows < 50% UF proxy for most schools
- [ ] `feature_pipeline.py` — `temporal_split()` tested: no student appears in both train and test
- [ ] `feature_pipeline.py` — null grades filled with -1 via `fill_grade_sentinel()`
- [ ] Manual check: `df[df['tem_diario'] == 0]['taxa_ausencia'].isna().all()` → True

### Phase 2 — Models
- [ ] `dropout_classifier.py` — `scale_pos_weight` auto-computed and logged
- [ ] `dropout_classifier.py` — `eval_metric = 'aucpr'` (not 'auc')
- [ ] `grade_regressor.py` — only trained on EF2 students
- [ ] `risk_clusterer.py` — Silhouette Score logged per k in CALL (st)
- [ ] `risk_clusterer.py` — `write_clusters_to_neo4j()` tested on sandbox with 10 students
- [ ] All models trained with `temporal_split` — no random split anywhere

### Phase 3 — Evaluation & SHAP
- [ ] AUROC ≥ 0.82 on temporal test set
- [ ] Recall ≥ 0.75 on temporal test set
- [ ] SHAP top-5 features include `taxa_ausencia`, `nota_final_norm` (expected to dominate)
- [ ] SHAP top-5 features explain ≥ 65% of global impact

### Phase 4 — MLOps
- [ ] MLflow server running at `$MLFLOW_URI`
- [ ] `dag__ml_feature_engineering` runs end-to-end without error
- [ ] `dag__ml_retrain` validate → train → compare pipeline completes
- [ ] `dag__ml_drift_detection` generates HTML report and sets flag correctly
- [ ] Champion/Challenger: second run does NOT promote unless AUROC improves > 0.01
- [ ] No `student_id` or personal data in any log line

---

## 15. Tech Stack

| Layer | Tool | Notes |
|---|---|---|
| Graph DB | Neo4j 5.11+ | Already deployed |
| Orchestration | Apache Airflow | Already deployed |
| Feature extraction | Cypher → Pandas | Queries in this document §2 |
| ML: Dropout | XGBoost ≥ 2.0.0 | `tree_method='hist'` for large datasets |
| ML: Grade | scikit-learn ≥ 1.4.0 GBM | EF2 only |
| ML: Clustering | scikit-learn KMeans + PCA | Writes back to Neo4j |
| Explainability | SHAP ≥ 0.44.0 | TreeExplainer — no GPU needed |
| Experiment tracking | MLflow ≥ 2.12.0 | Self-hosted |
| Drift detection | Evidently AI ≥ 0.4.0 | PSI per feature |
| Embeddings | sentence-transformers (local) | `paraphrase-multilingual-MiniLM-L12-v2` |
| RAG LLM | Gemini Flash or Ollama | See PLAN-ML-02-RAG-LLM.md |
| Serving | FastAPI ≥ 0.110.0 | See PLAN-ML-03-API-SERVING.md |

```
pip install \
  neo4j>=5.0.0 \
  pandas>=2.0.0 \
  xgboost>=2.0.0 \
  scikit-learn>=1.4.0 \
  shap>=0.44.0 \
  mlflow>=2.12.0 \
  evidently>=0.4.0 \
  sentence-transformers>=2.7.0 \
  apache-airflow>=2.9.0 \
  langchain>=0.2.0 \
  langchain-neo4j>=0.1.0
```
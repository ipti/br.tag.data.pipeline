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
fallback computed ONCE per UF in Python (not repeated per school in Cypher).
Passed as Cypher parameters to school-level queries. Documented in
CYPHER-QUERY-MATRIX-ML.md §Fallback IBGE and neo4_schema_and_tips.md §4.4.

Architecture — chunked streaming to Parquet:
- Schools are fetched once and grouped by UF.
- IBGE UF averages are pre-computed once per UF via a single Cypher call (not
  repeated N times inside each school query).
- Each school chunk is streamed directly to a Parquet file via PyArrow
  RecordBatchWriter — no intermediate DataFrame accumulation.
- A single persistent Neo4j session is reused across all school chunks in a
  step to avoid connection overhead (sessions are not thread-safe but are
  cheap to reuse within a single thread).
- GC is triggered once per UF group switch, not per chunk.

References:
- EF1 extraction query: PLAN-ML-NEO4J-SCHOOL.md §3.1
- EF2 grade pivot query: PLAN-ML-NEO4J-SCHOOL.md §3.2
- Full analytic query matrix: CYPHER-QUERY-MATRIX-ML.md Q1–Q15
- Dropout risk score structure: Q_RISCO_EVASAO_EF2.md

# SCHEMA CONFLICT NOTE (resolved):
# CYPHER-QUERY-MATRIX-ML.md lists atl_branco_analf25m and atl_negro_analf25m
# under Municipality. NEO4J-SCHEMA-REFERENCE.md §8 confirms these do NOT exist
# in the Municipality node. The correct properties are:
#   st.branco_pnad_t_analf25m  (State, PNAD)
#   st.negro_pnad_t_analf25m   (State, PNAD)
# All queries in this file use the State-level properties. Do not add
# m.atl_branco_analf25m or m.atl_negro_analf25m — they return null or error.
"""
import gc
import logging
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from neo4j import GraphDatabase, Driver, Session

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-computation query: UF-level IBGE averages (run ONCE per UF, not per school)
# ─────────────────────────────────────────────────────────────────────────────
# Returns one row per State with all 6 fallback averages.
# These values are then passed as $uf_* parameters to school-level queries,
# eliminating the 6 CALL (st) { MATCH (m2:Municipality)... } blocks that
# previously ran for every school in the same UF.
_QUERY_UF_IBGE_AVERAGES = """
MATCH (st:State)
OPTIONAL MATCH (m:Municipality)-[:BELONGS_TO_STATE]->(st)
WITH st,
     avg(CASE WHEN m.atl_freq_liq_fund        IS NOT NULL AND m.atl_freq_liq_fund > 0
              THEN m.atl_freq_liq_fund        END) AS uf_avg_freq,
     avg(CASE WHEN m.atl_atraso_2_fund        IS NOT NULL AND m.atl_atraso_2_fund > 0
              THEN m.atl_atraso_2_fund        END) AS uf_avg_atraso,
     avg(CASE WHEN m.atl_t_analf25m           IS NOT NULL
              THEN m.atl_t_analf25m           END) AS uf_avg_analf,
     avg(CASE WHEN m.atl_expectativa_estudo_18 IS NOT NULL
              THEN m.atl_expectativa_estudo_18 END) AS uf_avg_expectativa,
     avg(CASE WHEN m.atl_negro_mat_pub_fund   IS NOT NULL
              THEN m.atl_negro_mat_pub_fund   END) AS uf_avg_negro_pub,
     avg(CASE WHEN m.atl_negro_internet_fund  IS NOT NULL
              THEN m.atl_negro_internet_fund  END) AS uf_avg_negro_internet
RETURN
  st.sigla             AS uf,
  uf_avg_freq,
  uf_avg_atraso,
  uf_avg_analf,
  uf_avg_expectativa,
  uf_avg_negro_pub,
  uf_avg_negro_internet
"""

# Pre-computation query: school → UF mapping (run once, groups schools by UF)
_QUERY_SCHOOLS_BY_UF = """
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
RETURN sch.id AS school_id, st.sigla AS uf
ORDER BY st.sigla, sch.id
"""


# ─────────────────────────────────────────────────────────────────────────────
# EF1 full extraction query (per school, IBGE fallbacks via $params)
# ─────────────────────────────────────────────────────────────────────────────
# IBGE fallbacks are now passed as Cypher parameters ($uf_avg_freq, etc.)
# instead of being recomputed in 6 CALL blocks for every school.
# One row per student. Grade filter injected via {grade_filter} placeholder.
# Note: h.malnutrition correct — NOT h.malnutrition_desease. See schema §8.
#
# PAGINATION: supports $skip / $limit to page through students within a school.
# The ORDER BY stu.id before SKIP/LIMIT ensures stable pagination — without it
# Neo4j can return the same student in two pages or skip one entirely when the
# planner changes row ordering between calls.
# Python side: _run_one_school(paginated=True) drives the loop.
_QUERY_STUDENTS_BASE = """
MATCH (sch:School {id: $school_id})-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// ── Main traversal: students in classrooms ──────────────────────────────────
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
{grade_filter}

// ORDER BY + SKIP/LIMIT for stable intra-school pagination.
// Neo4j evaluates the full MATCH before applying SKIP/LIMIT, but the
// subsequent CALL blocks (attendance, grades, health) only run on the
// $limit students in this page — limiting peak heap usage per transaction.
WITH DISTINCT stu, cr, sch, m, st
ORDER BY stu.id
SKIP $skip LIMIT $limit

// Health node is OPTIONAL — absence ≠ no conditions (see neo4_schema_and_tips.md §4.2)
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)

WITH stu, cr, sch, m, st, h

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

// ── Situation/Avaliation dimension ──────────────────────────────────────────
CALL (stu) {
  OPTIONAL MATCH (stu)-[:EVALUATED_IN]->(a:Avaliation)
  WHERE a.situation =~ '(?i).*REPROVADO.*'
  RETURN count(a) AS n_situacoes_reprovado
}

// ── Grade dimension — EF1: discipline_name = '' means global grade ───────────
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

WITH stu, cr, sch, m, st, h,
     total_faltas, total_dias, n_sc_records,
     n_situacoes_reprovado,
     nota_final, nota_g1, nota_g2, trajetoria,
     CASE WHEN n_sc_records > 0 THEN 1 ELSE 0 END AS tem_diario

RETURN
  // ── Identity ──────────────────────────────────────────────────────────────
  stu.id   AS student_id,
  sch.id   AS school_id,
  st.sigla AS uf,

  // ── Demographics ──────────────────────────────────────────────────────────
  CASE WHEN stu.gender =~ '(?i)^F.*' THEN 1 ELSE 0 END                          AS gender_bin,
  coalesce(stu.ethnicity, '')                                                      AS ethnicity_raw,
  CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN 1 ELSE 0 END AS has_deficiency,
  CASE WHEN coalesce(stu.bolsa_familia, false) THEN 1 ELSE 0 END                 AS bolsa_familia,
  coalesce(stu.residence_zone, 'Não Informado')                                   AS residence_zone_raw,

  // ── Health (h.malnutrition NOT h.malnutrition_desease) ────────────────────
  CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END                                       AS has_health_record,
  CASE WHEN coalesce(h.malnutrition, false) THEN 1 ELSE 0 END                    AS has_malnutrition,
  CASE WHEN coalesce(h.diabetes, false) THEN 1 ELSE 0 END                        AS has_diabetes,
  CASE WHEN coalesce(h.hypertension, false) THEN 1 ELSE 0 END                    AS has_hypertension,
  CASE WHEN coalesce(h.obesity, false) THEN 1 ELSE 0 END                         AS has_obesity,
  CASE WHEN coalesce(h.celiac, false) THEN 1 ELSE 0 END                          AS has_celiac,
  CASE WHEN coalesce(h.iron_deficiency_anemia, false)
        OR coalesce(h.sickle_cell_anemia, false) THEN 1 ELSE 0 END               AS has_anemia,

  // ── Attendance & Situations ────────────────────────────────────────────────
  tem_diario,
  total_faltas                                                                     AS total_faltas_abs,
  CASE WHEN tem_diario = 1 AND total_dias > 0
       THEN round(toFloat(total_faltas) / total_dias, 4)
       ELSE null END                                                               AS taxa_ausencia,
  CASE WHEN tem_diario = 1 AND total_dias > 0
        AND toFloat(total_faltas) / total_dias > 0.10
       THEN 1 ELSE 0 END                                                          AS falta_critica,
  CASE WHEN n_situacoes_reprovado > 0 THEN 1 ELSE 0 END                          AS aluno_reprovado_flag,

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

  // ── Municipality IBGE — fallbacks come from $uf_avg_* params (pre-computed) ─
  // This eliminates 6 CALL { MATCH Municipality... } blocks per school.
  coalesce(m.atl_freq_liq_fund,         $uf_avg_freq)          AS muni_freq_liq_fund,
  CASE WHEN m.atl_freq_liq_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_freq_fonte,

  coalesce(m.atl_atraso_2_fund,         $uf_avg_atraso)        AS muni_atraso_2anos,
  CASE WHEN m.atl_atraso_2_fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_atraso_fonte,

  coalesce(m.atl_t_analf25m,            $uf_avg_analf)         AS muni_analf_adulto,
  CASE WHEN m.atl_t_analf25m IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS muni_analf_fonte,

  coalesce(m.atl_expectativa_estudo_18, $uf_avg_expectativa)   AS muni_expectativa_estudo,
  coalesce(m.atl_negro_mat_pub_fund,    $uf_avg_negro_pub)     AS muni_pct_negro_pub,
  coalesce(m.atl_negro_internet_fund,   $uf_avg_negro_internet) AS muni_internet_negro,
  // Note: atl_branco_analf25m does NOT exist on Municipality — on State (PNAD)

  // Delta: school absence rate vs municipal benchmark
  CASE WHEN tem_diario = 1 AND total_dias > 0
        AND coalesce(m.atl_freq_liq_fund, $uf_avg_freq) IS NOT NULL
       THEN round(
         toFloat(total_faltas) / total_dias * 100
         - (100.0 - coalesce(m.atl_freq_liq_fund, $uf_avg_freq)), 4)
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
  CASE cr.grade_level
    WHEN 'NO 1* ANO' THEN st.qedu_distorcao_ef1
    WHEN 'NO 2* ANO' THEN st.qedu_distorcao_ef2
    WHEN 'NO 3* ANO' THEN st.qedu_distorcao_ef3
    WHEN 'NO 4* ANO' THEN st.qedu_distorcao_ef4
    WHEN 'NO 5* ANO' THEN st.qedu_distorcao_ef5
    WHEN 'NO 6* ANO' THEN coalesce(st.qedu_distorcao_ef6, st.qedu_distorcao_ef_af)
    WHEN 'NO 7* ANO' THEN coalesce(st.qedu_distorcao_ef7, st.qedu_distorcao_ef_af)
    WHEN 'NO 8* ANO' THEN coalesce(st.qedu_distorcao_ef8, st.qedu_distorcao_ef_af)
    WHEN 'NO 9* ANO' THEN coalesce(st.qedu_distorcao_ef9, st.qedu_distorcao_ef_af)
    ELSE coalesce(st.qedu_distorcao_ef_ai, st.qedu_distorcao_ef_af)
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
  CASE WHEN tem_diario = 1 AND total_dias > 0
        AND toFloat(total_faltas) / total_dias > 0.25
       THEN 1 ELSE 0 END AS target_evasao,
  CASE WHEN nota_final IS NOT NULL AND nota_final < 5.0
       THEN 1 ELSE 0 END AS target_reprovacao,
  nota_final             AS target_nota
"""

# ─────────────────────────────────────────────────────────────────────────────
# EF2 grade pivot query (per school, via $school_id param)
# ─────────────────────────────────────────────────────────────────────────────
_QUERY_EF2_GRADES = """
MATCH (sch:School {id: $school_id})<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
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
  round(avg(CASE WHEN disciplina =~ '(?i).*MATEM.*'   THEN nota_final_norm END), 4) AS nota_mat_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*PORTUGU.*' THEN nota_final_norm END), 4) AS nota_lp_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*CIÊN.*'    THEN nota_final_norm END), 4) AS nota_ciencias_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*HISTÓR.*'  THEN nota_final_norm END), 4) AS nota_historia_norm,
  round(avg(CASE WHEN disciplina =~ '(?i).*GEOGRAF.*' THEN nota_final_norm END), 4) AS nota_geo_norm
"""

# ─────────────────────────────────────────────────────────────────────────────
# School-level feature query (per school, IBGE fallbacks via $params)
# ─────────────────────────────────────────────────────────────────────────────
_QUERY_SCHOOL_FEATURES = """
MATCH (sch:School {id: $school_id})-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)
WITH sch, m, st, collect(DISTINCT stu) AS todos_alunos

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
  n_com_diario,
  CASE WHEN n_com_diario = 0 THEN null
       WHEN total_dias_escola > 0
       THEN round(toFloat(total_faltas_escola) / total_dias_escola * 100, 2)
       ELSE null END AS taxa_ausencia_pct,
  n_notas,
  media_nota_escola,
  CASE WHEN n_notas > 0
       THEN round(toFloat(n_abaixo5) / n_notas * 100, 1)
       ELSE null END AS pct_abaixo5,
  n_com_saude,
  n_desnutridos,
  size([s IN todos_alunos WHERE coalesce(s.bolsa_familia, false)]) AS n_bolsa_familia,
  size([s IN todos_alunos WHERE coalesce(s.deficiency,'Não') STARTS WITH 'Possui']) AS n_pcd,
  coalesce(m.atl_freq_liq_fund, $uf_avg_freq)   AS muni_freq_liq_fund,
  coalesce(m.atl_t_analf25m,    $uf_avg_analf)  AS muni_analf_adulto,
  st.qedu_ideb_af                               AS est_ideb_af,
  st.qedu_taxa_abandono                         AS est_taxa_abandono,
  st.qedu_taxa_reprovacao                       AS est_taxa_reprovacao
"""

# ─────────────────────────────────────────────────────────────────────────────
# Q15 God Matrix — classroom-level features (per school, IBGE via $params)
# ─────────────────────────────────────────────────────────────────────────────
_QUERY_CLASSROOM_EF1 = """
MATCH (sch:School {id: $school_id})-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

WITH sch, m, st, cr,
     collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 5

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

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))            AS cr_total_faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))  AS cr_total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS cr_n_com_falta
}

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
     cr_media_nota, cr_dispersao_nota, cr_n_notas, cr_n_abaixo5,
     cr_total_faltas, cr_total_dias, cr_n_com_falta, cr_n_risco_saude

RETURN
  sch.id        AS school_id,
  cr.name       AS classroom_name,
  cr.grade_level AS classroom_grade,
  cr.stage      AS classroom_stage,
  cr.year       AS ano_letivo,
  size(AlunosDaTurma) AS cr_n_alunos,
  size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, false) = true])   AS cr_n_bolsistas,
  size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS cr_n_pcd,
  size([s IN AlunosDaTurma WHERE coalesce(s.residence_zone, '') =~ '(?i).*rural.*']) AS cr_n_rural,
  coalesce(cr_n_risco_saude, 0)  AS cr_n_risco_saude,
  cr_media_nota,
  cr_dispersao_nota,
  cr_n_notas,
  CASE WHEN cr_n_notas > 0
       THEN round(toFloat(cr_n_abaixo5) / cr_n_notas * 100, 1)
       ELSE null END AS cr_pct_abaixo5,
  CASE WHEN cr_media_nota > 0 AND cr_dispersao_nota IS NOT NULL
       THEN round(cr_dispersao_nota / cr_media_nota * 100, 1)
       ELSE null END AS cr_cv_nota_pct,
  CASE WHEN cr_total_dias > 0
       THEN round(toFloat(cr_total_faltas) / cr_total_dias * 100, 2)
       ELSE null END AS cr_taxa_ausencia_pct,
  CASE WHEN size(AlunosDaTurma) > 0
       THEN round(toFloat(cr_n_com_falta) / size(AlunosDaTurma) * 100, 1)
       ELSE null END AS cr_pct_alunos_com_falta,
  CASE WHEN size(AlunosDaTurma) > 0 THEN
    round(
      (toFloat(cr_n_com_falta) / size(AlunosDaTurma)) * 0.40
    + (coalesce(toFloat(cr_n_abaixo5) / NULLIF(cr_n_notas, 0), 0.5)) * 0.35
    + (toFloat(cr_n_risco_saude) / size(AlunosDaTurma)) * 0.25,
    4)
  ELSE null END AS cr_soma_sinais_risco,
  // IBGE fallbacks from $params (pre-computed once per UF)
  coalesce(m.atl_freq_liq_fund, $uf_avg_freq)   AS cr_muni_freq_liq_fund,
  coalesce(m.atl_t_analf25m,    $uf_avg_analf)  AS cr_muni_analf_adulto,
  coalesce(m.atl_atraso_2_fund, $uf_avg_atraso) AS cr_muni_atraso_2anos,
  st.qedu_ideb_ai                              AS cr_est_ideb_ai,
  st.qedu_taxa_abandono                        AS cr_est_taxa_abandono,
  st.qedu_distorcao_ef_ai                      AS cr_est_distorcao_ai,
  CASE WHEN cr_n_com_falta > 0 THEN 1 ELSE 0 END AS flag_tem_diario,
  CASE WHEN cr_n_notas     > 0 THEN 1 ELSE 0 END AS flag_tem_notas
"""


# ─────────────────────────────────────────────────────────────────────────────
# PyArrow schema — defines column types for Parquet output.
# Explicit schema avoids type inference bugs when chunks have nulls only
# (e.g. a school with no health records → all health columns inferred as null).
# ─────────────────────────────────────────────────────────────────────────────
_SCHEMA_STUDENTS_BASE = pa.schema([
    ("student_id",             pa.string()),
    ("school_id",              pa.string()),
    ("uf",                     pa.string()),
    ("gender_bin",             pa.int8()),
    ("ethnicity_raw",          pa.string()),
    ("has_deficiency",         pa.int8()),
    ("bolsa_familia",          pa.int8()),
    ("residence_zone_raw",     pa.string()),
    ("has_health_record",      pa.int8()),
    ("has_malnutrition",       pa.int8()),
    ("has_diabetes",           pa.int8()),
    ("has_hypertension",       pa.int8()),
    ("has_obesity",            pa.int8()),
    ("has_celiac",             pa.int8()),
    ("has_anemia",             pa.int8()),
    ("tem_diario",             pa.int8()),
    ("total_faltas_abs",       pa.float32()),
    ("taxa_ausencia",          pa.float32()),
    ("falta_critica",          pa.int8()),
    ("aluno_reprovado_flag",   pa.int8()),
    ("nota_final_norm",        pa.float32()),
    ("nota_g1_norm",           pa.float32()),
    ("nota_g2_norm",           pa.float32()),
    ("trajetoria_nota",        pa.float32()),
    ("em_recuperacao",         pa.int8()),
    ("stage_raw",              pa.string()),
    ("grade_level_raw",        pa.string()),
    ("ano_letivo",             pa.int16()),
    ("muni_freq_liq_fund",     pa.float32()),
    ("muni_freq_fonte",        pa.string()),
    ("muni_atraso_2anos",      pa.float32()),
    ("muni_atraso_fonte",      pa.string()),
    ("muni_analf_adulto",      pa.float32()),
    ("muni_analf_fonte",       pa.string()),
    ("muni_expectativa_estudo",pa.float32()),
    ("muni_pct_negro_pub",     pa.float32()),
    ("muni_internet_negro",    pa.float32()),
    ("muni_delta_freq",        pa.float32()),
    ("est_ideb_ai",            pa.float32()),
    ("est_ideb_af",            pa.float32()),
    ("est_taxa_abandono",      pa.float32()),
    ("est_taxa_reprovacao",    pa.float32()),
    ("est_fluxo_ai",           pa.float32()),
    ("est_pct_fora_escola",    pa.float32()),
    ("est_lp_insuf_ai",        pa.float32()),
    ("est_mat_insuf_ai",       pa.float32()),
    ("est_lp_adequado_ai",     pa.float32()),
    ("est_mat_adequado_ai",    pa.float32()),
    ("est_aprendizado_ai",     pa.float32()),
    ("est_distorcao_serie",    pa.float32()),
    ("est_analf_negro",        pa.float32()),
    ("est_analf_branco",       pa.float32()),
    ("est_atraso_negro",       pa.float32()),
    ("est_atraso_branco",      pa.float32()),
    ("est_analf_homem",        pa.float32()),
    ("est_analf_mulher",       pa.float32()),
    ("est_rdpc_negro",         pa.float32()),
    ("est_rdpc_branco",        pa.float32()),
    ("target_evasao",          pa.int8()),
    ("target_reprovacao",      pa.int8()),
    ("target_nota",            pa.float32()),
])


def _coerce_batch_to_schema(records: list[dict], schema: pa.Schema) -> pa.RecordBatch:
    """
    Convert a list of Neo4j record dicts to a PyArrow RecordBatch using an
    explicit schema. Handles type coercion (e.g. Neo4j int64 → int8, Python
    None → null) so chunks with partial data don't corrupt the Parquet file.
    """
    if not records:
        return pa.record_batch(
            {name: pa.array([], type=field.type) for name, field in zip(schema.names, schema)},
            schema=schema,
        )
    df = pd.DataFrame(records)
    arrays = []
    for i, field in enumerate(schema):
        col = field.name
        if col in df.columns:
            arr = pa.array(df[col].tolist(), type=field.type, from_pandas=True)
        else:
            arr = pa.array([None] * len(df), type=field.type)
        arrays.append(arr)
    return pa.record_batch(arrays, schema=schema)


class Neo4jExtractor:
    """
    Extracts feature data from Neo4j for the ML pipeline.

    Returns Path objects pointing to Parquet files — never loads 15M+ rows
    into RAM. Downstream consumers read with pq.read_table() or in batches:

        for batch in pq.ParquetFile(path).iter_batches(batch_size=200_000):
            process(batch.to_pandas())

    Output layout (all inside output_dir, default = src/ml/data/raw/):
        EF1.parquet              ← extract_students_base("EF1")
        EF2.parquet              ← extract_students_base("EF2")
        EF2_grades.parquet       ← extract_ef2_grades()
        school_features.parquet  ← extract_school_features()
        classrooms_EF1.parquet   ← extract_classroom_features("EF1")
        shards/<label>/          ← temp shards, deleted after merge

    Usage:
        extractor = Neo4jExtractor.from_env()
        path = extractor.extract_students_base("EF1", year=2024)
        df   = pd.read_parquet(path)   # only if RAM allows the full dataset
        extractor.close()
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        output_dir: Path | None = None,
    ) -> None:
        """
        Args:
            uri:        Neo4j bolt URI, e.g. 'bolt://localhost:7687'
            user:       Neo4j username
            password:   Neo4j password
            output_dir: Where Parquet outputs are written.
                        Defaults to src/ml/data/raw/ (relative to this file).
        """
        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        if output_dir is None:
            # __file__ = src/ml/features/neo4j_extractor.py
            # parent.parent = src/ml/
            output_dir = Path(__file__).parent.parent / "data" / "raw"
        self._output_dir: Path = output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Neo4jExtractor output_dir: %s", self._output_dir.resolve())
        self._uf_ibge: dict[str, dict] | None = None
        self._schools_by_uf: dict[str, list[str]] | None = None

    @classmethod
    def from_env(cls, output_dir: Path | None = None) -> "Neo4jExtractor":
        """
        Create an extractor from environment variables.
        Expected: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD.
        Optional: pass output_dir to override the default src/ml/data/raw/.
        """
        return cls(
            uri=os.environ["NEO4J_URI"],
            user=os.environ["NEO4J_USER"],
            password=os.environ["NEO4J_PASSWORD"],
            output_dir=output_dir,
        )

    def close(self) -> None:
        """Close the driver and release the connection pool."""
        self._driver.close()

    # ── Context pre-computation ───────────────────────────────────────────────

    def _fetch_uf_context(self) -> dict[str, dict]:
        """
        Fetch IBGE averages for all UFs in a single query.
        Result is cached on the instance — subsequent calls return the cache.

        Returns dict keyed by UF sigla:
            {
              "SE": {
                "uf_avg_freq": 94.2,
                "uf_avg_atraso": 12.1,
                ...
              },
              ...
            }
        """
        if self._uf_ibge is not None:
            return self._uf_ibge

        logger.info("Pre-computing IBGE UF averages (single query, all states)...")
        with self._driver.session() as session:
            result = session.run(_QUERY_UF_IBGE_AVERAGES)
            rows = [r.data() for r in result]

        self._uf_ibge = {
            row["uf"]: {k: v for k, v in row.items() if k != "uf"}
            for row in rows
        }
        logger.info("IBGE UF averages cached for %d states", len(self._uf_ibge))
        return self._uf_ibge

    def _fetch_schools_by_uf(self) -> dict[str, list[str]]:
        """
        Fetch all school IDs grouped by UF.
        Cached on the instance. Returns dict: uf → [school_id, ...]
        """
        if self._schools_by_uf is not None:
            return self._schools_by_uf

        logger.info("Fetching school→UF mapping...")
        with self._driver.session() as session:
            result = session.run(_QUERY_SCHOOLS_BY_UF)
            rows = [r.data() for r in result]

        grouped: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            grouped[row["uf"]].append(row["school_id"])

        self._schools_by_uf = dict(grouped)
        total = sum(len(v) for v in self._schools_by_uf.values())
        logger.info(
            "School→UF mapping cached: %d schools across %d UFs",
            total, len(self._schools_by_uf),
        )
        return self._schools_by_uf

    # ── Core streaming engine ─────────────────────────────────────────────────

    # Page size for intra-school student pagination.
    # 200 students × ~15 CALL-block sub-queries ≈ 3.000 sub-traversals per
    # transaction — well within the 3 GB Neo4j heap budget.
    # Raise to 500 if your Neo4j heap is ≥ 6 GB; lower to 100 if still OOM.
    _STUDENT_PAGE_SIZE: int = 200

    def _run_one_school(
        self,
        session: "Session",
        query: str,
        params: dict,
        paginated: bool,
    ) -> list[dict]:
        """
        Run a query for one school and return all records.

        If paginated=True, issues repeated SKIP/LIMIT calls until the server
        returns an empty page, keeping each transaction small.
        If paginated=False, runs the query once (used for non-student queries
        like school features or classroom aggregates, which are already
        lightweight because they aggregate over students rather than returning
        one row per student).
        """
        if not paginated:
            result = session.run(query, **params)
            return [r.data() for r in result]

        all_records: list[dict] = []
        skip = 0
        while True:
            page_params = {**params, "skip": skip, "limit": self._STUDENT_PAGE_SIZE}
            result = session.run(query, **page_params)
            page = [r.data() for r in result]
            if not page:
                break
            all_records.extend(page)
            skip += self._STUDENT_PAGE_SIZE
            # Early-exit: if page is smaller than limit, it was the last page
            if len(page) < self._STUDENT_PAGE_SIZE:
                break
        return all_records

    # How many schools per Parquet shard before rotating the writer.
    # PyArrow's ParquetWriter accumulates row-group footer metadata in RAM for
    # its entire lifetime. With 1002 schools × 61 columns the footer grows to
    # ~1-2 GB and triggers the kernel OOM killer near the end of the run.
    # Rotating every 100 schools caps footer RAM at ~100 MB per shard.
    _SHARD_SIZE: int = 100

    def _stream_to_parquet(
        self,
        query: str,
        step_label: str,
        schema: pa.Schema,
        paginated: bool = False,
    ) -> "Path":
        """
        Stream query results school-by-school to a final Parquet file.

        Returns the Path to the merged Parquet — never loads all rows into RAM.
        The caller (extract_* methods) works with the Path directly; downstream
        code reads it with pq.read_table / pd.read_parquet in chunks as needed.

        Output location:  <output_dir>/<step_label>.parquet
        Temp shards:      <output_dir>/shards/<step_label>/shard_NNNN.parquet
                          (deleted after merge)

        Memory budget:
        - During extraction: ≤ _STUDENT_PAGE_SIZE rows in Python RAM at once.
        - During merge: one shard (~100 schools) in RAM at a time.
        - After return: zero — the caller holds only a Path, not a DataFrame.

        Args:
            query:      Cypher query. Must accept $school_id.
                        If paginated=True, must also accept $skip / $limit.
            step_label: Used for file naming and log messages.
            schema:     PyArrow schema for type-safe Parquet output.
            paginated:  If True, pages through students within each school
                        using $skip/$limit. Use for extract_students_base();
                        False for school/classroom aggregates.
        """
        schools_by_uf = self._fetch_schools_by_uf()
        uf_ibge = self._fetch_uf_context()

        # ── Output paths ────────────────────────────────────────────────────
        out_dir = self._output_dir
        shards_dir = out_dir / "shards" / step_label
        shards_dir.mkdir(parents=True, exist_ok=True)
        # Wipe any leftover shards from a previous aborted run
        for f in shards_dir.iterdir():
            f.unlink()

        final_path = out_dir / f"{step_label}.parquet"

        total_schools = sum(len(v) for v in schools_by_uf.values())
        success_chunks = 0
        processed = 0
        shard_idx = 0
        current_writer: pq.ParquetWriter | None = None

        def _open_shard() -> pq.ParquetWriter:
            p = shards_dir / f"shard_{shard_idx:04d}.parquet"
            return pq.ParquetWriter(str(p), schema, compression="snappy")

        try:
            with self._driver.session() as session:
                prev_uf = None
                for uf, school_ids in schools_by_uf.items():
                    if prev_uf is not None and uf != prev_uf:
                        gc.collect()
                    prev_uf = uf
                    uf_params = uf_ibge.get(uf, {})

                    for school_id in school_ids:
                        processed += 1
                        if processed % 100 == 0:
                            logger.info(
                                "[%s] %d/%d schools processed (%d written)",
                                step_label, processed, total_schools, success_chunks,
                            )

                        # Rotate writer every _SHARD_SIZE schools
                        if (processed - 1) % self._SHARD_SIZE == 0:
                            if current_writer is not None:
                                current_writer.close()
                                current_writer = None
                                shard_idx += 1
                                gc.collect()
                            current_writer = _open_shard()

                        params = {"school_id": school_id, **uf_params}
                        try:
                            records = self._run_one_school(
                                session, query, params, paginated
                            )
                            if records:
                                batch = _coerce_batch_to_schema(records, schema)
                                current_writer.write_batch(batch)  # type: ignore[union-attr]
                                success_chunks += 1
                        except Exception as exc:
                            logger.warning(
                                "[%s] Skipped school %s: %s",
                                step_label, school_id, str(exc).strip(),
                            )
        finally:
            if current_writer is not None:
                current_writer.close()
                current_writer = None

        shard_files = sorted(shards_dir.glob("shard_*.parquet"))

        if not shard_files or success_chunks == 0:
            raise RuntimeError(
                f"[{step_label}] No data written — 0 successful school chunks."
            )

        # ── Merge shards into final file (one shard in RAM at a time) ────────
        logger.info(
            "[%s] Merging %d shards → %s", step_label, len(shard_files), final_path
        )
        with pq.ParquetWriter(str(final_path), schema, compression="snappy") as merger:
            for shard_path in shard_files:
                tbl = pq.read_table(str(shard_path), schema=schema)
                merger.write_table(tbl)
                del tbl
                shard_path.unlink()   # free disk as we go
                gc.collect()

        shards_dir.rmdir()  # now empty

        # ── Row count from metadata only — zero RAM cost ──────────────────────
        meta = pq.read_metadata(str(final_path))
        total_rows = meta.num_rows
        logger.info(
            "[%s] Done: %d rows, %d columns → %s (%d shards, %d/%d schools)",
            step_label, total_rows, len(schema),
            final_path, shard_idx + 1, success_chunks, total_schools,
        )
        return final_path

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_students_base(
        self,
        segment: Literal["EF1", "EF2"],
        year: int | None = None,
    ) -> Path:
        """
        Extract the base feature set (one row per student) for a given segment.

        Returns the Path to the Parquet file — does NOT load into RAM.
        15M rows × 61 columns ≈ 7-9 GB in pandas; always read in batches:

            path = extractor.extract_students_base("EF1")
            for batch in pq.ParquetFile(path).iter_batches(batch_size=200_000):
                df_chunk = batch.to_pandas()

        Args:
            segment: "EF1" or "EF2" to scope the grade level filter.
            year:    Filter to a single school year (cr.year = year).
                     None returns all years (historical training sets).

        Returns:
            Path to <output_dir>/<segment>.parquet
        """
        grade_filters = {
            "EF1": (
                "WHERE (cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']\n"
                "       OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\\\\\\\* SÉRIE')\n"
                "       OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL'])"
            ),
            "EF2": (
                "WHERE (cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']\n"
                "       OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\\\\\\\* SÉRIE'))"
            ),
        }

        filter_clause = grade_filters[segment]
        if year is not None:
            filter_clause += f"\n  AND cr.year = {year}"

        query = _QUERY_STUDENTS_BASE.replace("{grade_filter}", filter_clause)
        logger.info("Extracting %s students (year=%s)...", segment, year or "all")

        path = self._stream_to_parquet(query, segment, _SCHEMA_STUDENTS_BASE, paginated=True)
        self._log_ibge_coverage(path, segment)
        return path

    def extract_ef2_grades(self) -> Path:
        """
        Extract EF2 subject-level grade pivot (one row per student).

        Returns Path to <output_dir>/EF2_grades.parquet.
        Join with extract_students_base("EF2") via student_id.
        """
        schema = pa.schema([
            ("student_id",              pa.string()),
            ("n_disciplinas_total",     pa.int16()),
            ("nota_media_geral",        pa.float32()),
            ("nota_dispersao",          pa.float32()),
            ("n_disciplinas_abaixo5",   pa.int16()),
            ("pct_disciplinas_abaixo5", pa.float32()),
            ("trajetoria_media",        pa.float32()),
            ("nota_mat_norm",           pa.float32()),
            ("nota_lp_norm",            pa.float32()),
            ("nota_ciencias_norm",      pa.float32()),
            ("nota_historia_norm",      pa.float32()),
            ("nota_geo_norm",           pa.float32()),
        ])
        logger.info("Extracting EF2 grade pivot...")
        return self._stream_to_parquet(_QUERY_EF2_GRADES, "EF2_grades", schema)

    def extract_school_features(self) -> Path:
        """
        Extract school-level aggregated features.
        Returns Path to <output_dir>/school_features.parquet.
        """
        schema = pa.schema([
            ("school_id",          pa.string()),
            ("school_name",        pa.string()),
            ("municipio",          pa.string()),
            ("uf",                 pa.string()),
            ("n_alunos",           pa.int32()),
            ("n_com_diario",       pa.int32()),
            ("taxa_ausencia_pct",  pa.float32()),
            ("n_notas",            pa.int32()),
            ("media_nota_escola",  pa.float32()),
            ("pct_abaixo5",        pa.float32()),
            ("n_com_saude",        pa.int32()),
            ("n_desnutridos",      pa.int32()),
            ("n_bolsa_familia",    pa.int32()),
            ("n_pcd",              pa.int32()),
            ("muni_freq_liq_fund", pa.float32()),
            ("muni_analf_adulto",  pa.float32()),
            ("est_ideb_af",        pa.float32()),
            ("est_taxa_abandono",  pa.float32()),
            ("est_taxa_reprovacao",pa.float32()),
        ])
        logger.info("Extracting school-level features...")
        return self._stream_to_parquet(_QUERY_SCHOOL_FEATURES, "school_features", schema)

    def extract_classroom_features(self, segment: str = "EF1") -> Path:
        """
        Extract classroom-level feature aggregates (Q15 God Matrix).

        Returns Path to <output_dir>/classrooms_<segment>.parquet.
        Classrooms with < 5 students are excluded (filtered in Cypher).

        Merge pattern (read in batches to stay within RAM):
            path_stu = extractor.extract_students_base("EF1")
            path_cr  = extractor.extract_classroom_features("EF1")
            # feature_pipeline.py handles the join in chunks

        Raises:
            ValueError: if segment is not "EF1" or "EF2".
        """
        if segment not in ("EF1", "EF2"):
            raise ValueError(f"segment must be 'EF1' or 'EF2', got {segment!r}")

        schema = pa.schema([
            ("school_id",              pa.string()),
            ("classroom_name",         pa.string()),
            ("classroom_grade",        pa.string()),
            ("classroom_stage",        pa.string()),
            ("ano_letivo",             pa.int16()),
            ("cr_n_alunos",            pa.int16()),
            ("cr_n_bolsistas",         pa.int16()),
            ("cr_n_pcd",               pa.int16()),
            ("cr_n_rural",             pa.int16()),
            ("cr_n_risco_saude",       pa.int16()),
            ("cr_media_nota",          pa.float32()),
            ("cr_dispersao_nota",      pa.float32()),
            ("cr_n_notas",             pa.int16()),
            ("cr_pct_abaixo5",         pa.float32()),
            ("cr_cv_nota_pct",         pa.float32()),
            ("cr_taxa_ausencia_pct",   pa.float32()),
            ("cr_pct_alunos_com_falta",pa.float32()),
            ("cr_soma_sinais_risco",   pa.float32()),
            ("cr_muni_freq_liq_fund",  pa.float32()),
            ("cr_muni_analf_adulto",   pa.float32()),
            ("cr_muni_atraso_2anos",   pa.float32()),
            ("cr_est_ideb_ai",         pa.float32()),
            ("cr_est_taxa_abandono",   pa.float32()),
            ("cr_est_distorcao_ai",    pa.float32()),
            ("flag_tem_diario",        pa.int8()),
            ("flag_tem_notas",         pa.int8()),
        ])

        logger.info("Extracting classroom features (segment=%s)...", segment)
        query = _QUERY_CLASSROOM_EF1  # EF2 variant TBD
        return self._stream_to_parquet(query, f"classrooms_{segment}", schema)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run(self, query: str, paginate: bool = True, batch_size: int = 500, **kwargs) -> pd.DataFrame:
        """
        Execute a Cypher query and return results as a DataFrame.
        Used internally for pre-computation queries (school/UF listing, etc.).
        For bulk extraction, _stream_to_parquet() is used instead.
        """
        if paginate and "SKIP $skip LIMIT $limit" in query:
            all_records = []
            skip = 0
            with self._driver.session() as session:
                while True:
                    result = session.run(query, skip=skip, limit=batch_size, **kwargs)
                    batch = [r.data() for r in result]
                    if not batch:
                        break
                    all_records.extend(batch)
                    skip += batch_size
            return pd.DataFrame(all_records)
        else:
            with self._driver.session() as session:
                result = session.run(query, **kwargs)
                return pd.DataFrame([r.data() for r in result])

    def _log_ibge_coverage(self, parquet_path: Path, segment: str) -> None:
        """
        Log IBGE proxy coverage without loading the full file into RAM.
        Reads only the 'muni_freq_fonte' column from the Parquet file.
        """
        try:
            col = pq.read_table(
                str(parquet_path), columns=["muni_freq_fonte"]
            ).column("muni_freq_fonte")
        except Exception:
            return  # column absent — schema mismatch, skip silently

        import pyarrow.compute as pc
        total = len(col)
        if total == 0:
            return
        n_proxy = pc.sum(pc.equal(col, "Media_UF_Proxy")).as_py() or 0
        proxy_pct = n_proxy / total * 100
        if proxy_pct > 40:
            logger.warning(
                "%s: %.0f%% of students have IBGE freq from UF proxy (municipality field NULL)",
                segment, proxy_pct,
            )
        else:
            logger.info(
                "%s: IBGE freq coverage — %.0f%% municipal, %.0f%% UF proxy",
                segment, 100 - proxy_pct, proxy_pct,
            )
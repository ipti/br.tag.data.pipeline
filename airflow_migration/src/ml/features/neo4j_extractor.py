import gc
import logging
import os
import shutil
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
// Schools without electronic journal have ZERO StudentClass nodes.
// total_faults_per_discipline is sparse — not all StudentClass nodes have it.
// DO NOT use coalesce(..., 200) for scheduled_student_class_days when sc IS NULL
// — that would fake 200 scheduled days for students with no diary at all.
CALL (stu) {
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    count(DISTINCT sc)                                              AS n_sc_records,
    sum(CASE WHEN sc IS NOT NULL THEN coalesce(sc.total_faults_per_day, 0) ELSE null END)
                                                                    AS total_faltas,
    sum(CASE WHEN sc IS NOT NULL THEN coalesce(sc.scheduled_student_class_days, 0) ELSE null END)
                                                                    AS total_dias,
    sum(CASE WHEN sc IS NOT NULL THEN coalesce(sc.total_faults_per_discipline, 0) ELSE null END)
                                                                    AS total_faltas_disciplina
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
     total_faltas, total_dias, n_sc_records, total_faltas_disciplina,
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
  // tem_diario=1 → school uses electronic journal
  // total_faltas_disciplina is sparse — only set when school tracks per-discipline absence
  tem_diario,
  total_faltas                                                                     AS total_faltas_abs,
  total_faltas_disciplina                                                          AS total_faltas_disciplina,
  CASE WHEN tem_diario = 1 AND coalesce(total_dias, 0) > 0
       THEN round(toFloat(total_faltas) / total_dias, 4)
       ELSE null END                                                               AS taxa_ausencia,
  CASE WHEN tem_diario = 1 AND coalesce(total_dias, 0) > 0
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
    sum(CASE WHEN sc IS NOT NULL THEN coalesce(sc.total_faults_per_day, 0) ELSE null END)           AS cr_total_faltas,
    sum(CASE WHEN sc IS NOT NULL THEN coalesce(sc.scheduled_student_class_days, 0) ELSE null END)   AS cr_total_dias,
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END)           AS cr_n_com_falta,
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END)                                           AS cr_n_com_diario
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

// ── Class (scheduled lessons per discipline) ─────────────────────────────
// One Class node per (classroom, discipline, day) — aggregate by discipline
// 'Ensino Fundamental' = generic (EF1/no breakdown), named = specific discipline (EF2)
CALL (cr) {
  OPTIONAL MATCH (c:Class)-[:TAUGHT_IN]->(cr)
  WHERE c.scheduled_year = cr.year
  RETURN
    count(c)                                                           AS cr_n_class_nodes,
    sum(coalesce(c.scheduled_class_days, 0))                          AS cr_total_dias_agendados,
    sum(coalesce(c.scheduled_lessons_per_day, 0))                     AS cr_total_aulas_agendadas,
    count(DISTINCT CASE WHEN c.discipline_name <> 'Ensino Fundamental'
                         AND c.discipline_name IS NOT NULL
                        THEN c.discipline_name END)                   AS cr_n_disciplinas,
    count(DISTINCT CASE WHEN c.discipline_name <> 'Ensino Fundamental'
                         AND c.discipline_name IS NOT NULL
                        THEN c END)                                   AS cr_aulas_disciplinas_especificas
}

WITH sch, m, st, cr, AlunosDaTurma,
     cr_media_nota, cr_dispersao_nota, cr_n_notas, cr_n_abaixo5,
     cr_total_faltas, cr_total_dias, cr_n_com_falta, cr_n_com_diario, cr_n_risco_saude,
     cr_n_class_nodes, cr_total_dias_agendados, cr_total_aulas_agendadas,
     cr_n_disciplinas, cr_aulas_disciplinas_especificas

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
  CASE WHEN coalesce(cr_total_dias, 0) > 0
       THEN round(toFloat(cr_total_faltas) / cr_total_dias * 100, 2)
       ELSE null END AS cr_taxa_ausencia_pct,
  CASE WHEN size(AlunosDaTurma) > 0
       THEN round(toFloat(cr_n_com_falta) / size(AlunosDaTurma) * 100, 1)
       ELSE null END AS cr_pct_alunos_com_falta,
  cr_n_com_diario,
  // Class (scheduled lessons) features
  cr_total_dias_agendados,
  cr_total_aulas_agendadas,
  cr_n_disciplinas,
  cr_aulas_disciplinas_especificas,
  CASE WHEN cr_total_dias_agendados > 0 AND size(AlunosDaTurma) > 0
       THEN round(toFloat(cr_total_aulas_agendadas) / size(AlunosDaTurma), 2)
       ELSE null END AS cr_aulas_per_aluno,
  CASE WHEN cr_n_disciplinas > 0 THEN 1 ELSE 0 END AS cr_flag_tem_disciplinas,
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
  CASE WHEN cr_n_com_diario > 0 THEN 1 ELSE 0 END AS flag_tem_diario,
  CASE WHEN cr_n_notas     > 0 THEN 1 ELSE 0 END AS flag_tem_notas
"""


# ─────────────────────────────────────────────────────────────────────────────
# PyArrow schema — defines column types for Parquet output.
# Explicit schema avoids type inference bugs when chunks have nulls only
# (e.g. a school with no health records → all health columns inferred as null).
# ─────────────────────────────────────────────────────────────────────────────
_SCHEMA_STUDENTS_BASE = pa.schema(
    [
        ("student_id", pa.string()),
        ("school_id", pa.string()),
        ("uf", pa.string()),
        ("gender_bin", pa.int8()),
        ("ethnicity_raw", pa.string()),
        ("has_deficiency", pa.int8()),
        ("bolsa_familia", pa.int8()),
        ("residence_zone_raw", pa.string()),
        ("has_health_record", pa.int8()),
        ("has_malnutrition", pa.int8()),
        ("has_diabetes", pa.int8()),
        ("has_hypertension", pa.int8()),
        ("has_obesity", pa.int8()),
        ("has_celiac", pa.int8()),
        ("has_anemia", pa.int8()),
        ("tem_diario", pa.int8()),
        ("total_faltas_abs", pa.float32()),
        ("total_faltas_disciplina", pa.float32()),
        ("taxa_ausencia", pa.float32()),
        ("falta_critica", pa.int8()),
        ("aluno_reprovado_flag", pa.int8()),
        ("nota_final_norm", pa.float32()),
        ("nota_g1_norm", pa.float32()),
        ("nota_g2_norm", pa.float32()),
        ("trajetoria_nota", pa.float32()),
        ("em_recuperacao", pa.int8()),
        ("stage_raw", pa.string()),
        ("grade_level_raw", pa.string()),
        ("ano_letivo", pa.int16()),
        ("muni_freq_liq_fund", pa.float32()),
        ("muni_freq_fonte", pa.string()),
        ("muni_atraso_2anos", pa.float32()),
        ("muni_atraso_fonte", pa.string()),
        ("muni_analf_adulto", pa.float32()),
        ("muni_analf_fonte", pa.string()),
        ("muni_expectativa_estudo", pa.float32()),
        ("muni_pct_negro_pub", pa.float32()),
        ("muni_internet_negro", pa.float32()),
        ("muni_delta_freq", pa.float32()),
        ("est_ideb_ai", pa.float32()),
        ("est_ideb_af", pa.float32()),
        ("est_taxa_abandono", pa.float32()),
        ("est_taxa_reprovacao", pa.float32()),
        ("est_fluxo_ai", pa.float32()),
        ("est_pct_fora_escola", pa.float32()),
        ("est_lp_insuf_ai", pa.float32()),
        ("est_mat_insuf_ai", pa.float32()),
        ("est_lp_adequado_ai", pa.float32()),
        ("est_mat_adequado_ai", pa.float32()),
        ("est_aprendizado_ai", pa.float32()),
        ("est_distorcao_serie", pa.float32()),
        ("est_analf_negro", pa.float32()),
        ("est_analf_branco", pa.float32()),
        ("est_atraso_negro", pa.float32()),
        ("est_atraso_branco", pa.float32()),
        ("est_analf_homem", pa.float32()),
        ("est_analf_mulher", pa.float32()),
        ("est_rdpc_negro", pa.float32()),
        ("est_rdpc_branco", pa.float32()),
        ("target_evasao", pa.int8()),
        ("target_reprovacao", pa.int8()),
        ("target_nota", pa.float32()),
    ]
)


def _coerce_batch_to_schema(records: list[dict], schema: pa.Schema) -> pa.RecordBatch:
    """
    Convert a list of Neo4j record dicts to a PyArrow RecordBatch using an explicit schema.

    Handles continuous type coercion (e.g. Neo4j int64 to int8, Python None to null) so chunks with partial
    data don't corrupt the Parquet file.

    Args:
        records (list[dict]): A list of dictionaries representing the extracted records from Neo4j.
        schema (pa.Schema): PyArrow schema mapping indicating proper serialization domains.

    Raises:
        Exception: If pyarrow fails to interpret extracted fields under defined target domain lengths.

    Returns:
        pa.RecordBatch: Type-safe RecordBatch structure representing the target block.
    """
    if not records:
        return pa.record_batch(
            {
                name: pa.array([], type=field.type)
                for name, field in zip(schema.names, schema)
            },
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

    Returns Path objects pointing to Parquet files - never loads 15M+ rows
    into RAM. Downstream consumers read with pq.read_table() or in batches.
    """

    def __init__(
        self,
        uri: str,
        user: str,
        password: str,
        output_dir: Path | None = None,
    ) -> None:
        """
        Initializes the Neo4jExtractor session parameters.

        Args:
            uri (str): Neo4j bolt URI, e.g. 'bolt://localhost:7687'
            user (str): Neo4j username
            password (str): Neo4j password
            output_dir (Path | None, optional): Where Parquet outputs are written (local mode only).

        Raises:
            Exception: If initialization dependencies block driver startup.

        Returns:
            None
        """
        from src.ml.features._azure_storage import is_configured, get_fs, CONTAINER

        self._driver: Driver = GraphDatabase.driver(uri, auth=(user, password))
        self._azure: bool = is_configured()

        if self._azure:
            self._fs = get_fs()
            self._container: str = CONTAINER
            # Shards stay local in /tmp/ — only the merged Parquet goes to blob.
            # This avoids N Azure write transactions (one per shard).
            self._shards_dir: Path = Path(tempfile.mkdtemp(prefix="neo4j_shards_"))
            self._output_dir: Path = self._shards_dir
            logger.info(
                "Neo4jExtractor → Azure Blob mode (container=%s)", self._container
            )
        else:
            self._fs = None
            if output_dir is None:
                output_dir = Path(__file__).parent.parent / "data" / "raw"
            self._output_dir = output_dir
            self._output_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                "Neo4jExtractor → local mode (output_dir=%s)",
                self._output_dir.resolve(),
            )

        self._uf_ibge: dict[str, dict] | None = None
        self._schools_by_uf: dict[str, list[str]] | None = None

    @classmethod
    def from_env(cls, output_dir: Path | None = None) -> "Neo4jExtractor":
        """
        Create an extractor from environment variables.

        Args:
            output_dir (Path | None, optional): Optional override for Parquet output path.

        Raises:
            KeyError: If one of the required environment variables (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD) is absent.

        Returns:
            Neo4jExtractor: Built class instance drawing properties directly from environment variables.
        """
        return cls(
            uri=os.environ["NEO4J_URI"],
            user=os.environ["NEO4J_USER"],
            password=os.environ["NEO4J_PASSWORD"],
            output_dir=output_dir,
        )

    @property
    def fs(self):
        """Return the adlfs filesystem (None in local mode)."""
        return self._fs

    def close(self) -> None:
        """
        Close the Neo4j driver and release the localized connection pool.
        In Azure mode, also cleans up the temporary local shards directory.

        Args:
            None

        Raises:
            Exception: If Neo4j session disconnections hang or trip external handlers.

        Returns:
            None
        """
        self._driver.close()
        if self._azure and self._shards_dir.exists():
            shutil.rmtree(self._shards_dir, ignore_errors=True)

    # ── Context pre-computation ───────────────────────────────────────────────

    def _fetch_uf_context(self) -> dict[str, dict]:
        """
        Fetch IBGE averages for all UFs in a single query.

        Result is cached on the instance - subsequent calls return the cache.

        Args:
            None

        Raises:
            Exception: If execution times out or caching dictionaries corrupt structurally.

        Returns:
            dict[str, dict]: Formatted string dictionary linking 'UF' to specific sub-metrics logic mappings.
        """
        if self._uf_ibge is not None:
            return self._uf_ibge

        logger.info("Pre-computing IBGE UF averages (single query, all states)...")
        with self._driver.session() as session:
            result = session.run(_QUERY_UF_IBGE_AVERAGES)
            rows = [r.data() for r in result]

        self._uf_ibge = {
            row["uf"]: {k: v for k, v in row.items() if k != "uf"} for row in rows
        }
        logger.info("IBGE UF averages cached for %d states", len(self._uf_ibge))
        return self._uf_ibge

    def _fetch_schools_by_uf(self) -> dict[str, list[str]]:
        """
        Fetch all school IDs properly mapped and grouped by UF.

        Result is cached on the instance setup.

        Args:
            None

        Raises:
            Exception: If internal driver instances error.

        Returns:
            dict[str, list[str]]: String dictionaries linking 'UF' abbreviations to localized array blocks of string IDs.
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
            total,
            len(self._schools_by_uf),
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
        Run a query for one school isolated logic node block and return compiled extraction lists.

        If paginated=True, it repeatedly fires SKIP/LIMIT calls to keep transaction footprints low.

        Args:
            session (Session): Neo4j session parameter holding current live transaction footprint connections.
            query (str): Cypher query string passed for execution.
            params (dict): Injection dictionary carrying targeted Cypher substitutions.
            paginated (bool): Switch checking explicit batch paginating status on school extractions.

        Raises:
            Exception: Thrown natively per PyArrow/Neo4j bindings during chunk size overflows or mismatched syntax rules.

        Returns:
            list[dict]: Flattened list dict containing output variables per specified school bounds mapping.
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

    def _blob_path_for_step(self, step_label: str) -> str:
        """Map a step_label to an adlfs-compatible blob path (container/key).

        EF1_2025, EF2_2025 → raw/segment=EF1/year=2025/EF1_2025.parquet
        EF2_grades, classrooms_EF1, school_features → raw/{step_label}.parquet
        """
        parts = step_label.split("_")
        if len(parts) == 2 and parts[0] in ("EF1", "EF2") and parts[1].isdigit():
            segment, year = parts[0], parts[1]
            return f"{self._container}/raw/segment={segment}/year={year}/{step_label}.parquet"
        return f"{self._container}/raw/{step_label}.parquet"

    def _stream_to_parquet(
        self,
        query: str,
        step_label: str,
        schema: pa.Schema,
        paginated: bool = False,
    ) -> str:
        """
        Stream query results progressively school-by-school into a composed Parquet storage file.

        Strictly enforces batch ingestion to keep RAM overhead static against data variance.

        Args:
            query (str): Cypher query. Must accept nested parameters.
            step_label (str): Logging indicator string determining output filename block.
            schema (pa.Schema): PyArrow mapping matching exact structural return fields against input lists.
            paginated (bool, optional): Nested scoping argument targeting intra-query paginations over pure aggregations. Defaults to False.

        Raises:
            RuntimeError: If data streams register zero successful row writes indicating structural collapse underneath bounds.
            Exception: System memory access interruptions thrown within PyArrow library contexts directly.

        Returns:
            Path: Compiled pathlib path pointing cleanly to resulting .parquet merged destination.
        """
        schools_by_uf = self._fetch_schools_by_uf()
        uf_ibge = self._fetch_uf_context()

        # ── Output paths ────────────────────────────────────────────────────
        if self._azure:
            # Shards stay local; only the merged final file goes to blob.
            shards_dir = self._shards_dir / step_label
            blob_dest = self._blob_path_for_step(step_label)
        else:
            out_dir = self._output_dir
            shards_dir = out_dir / "shards" / step_label
            final_path = out_dir / f"{step_label}.parquet"

        shards_dir.mkdir(parents=True, exist_ok=True)
        # Wipe any leftover shards from a previous aborted run
        for f in shards_dir.iterdir():
            f.unlink()

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
                                step_label,
                                processed,
                                total_schools,
                                success_chunks,
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
                                step_label,
                                school_id,
                                str(exc).strip(),
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

        # ── Merge shards → final destination (blob or local) ─────────────────
        if self._azure:
            dest_label = blob_dest
            logger.info(
                "[%s] Merging %d shards → blob:%s",
                step_label,
                len(shard_files),
                blob_dest,
            )
            with pq.ParquetWriter(
                blob_dest, schema, compression="snappy", filesystem=self._fs
            ) as merger:
                for shard_path in shard_files:
                    tbl = pq.read_table(str(shard_path), schema=schema)
                    merger.write_table(tbl)
                    del tbl
                    shard_path.unlink()
                    gc.collect()
            shards_dir.rmdir()
            meta = pq.read_metadata(blob_dest, filesystem=self._fs)
            output: str = blob_dest
        else:
            dest_label = str(final_path)
            logger.info(
                "[%s] Merging %d shards → %s", step_label, len(shard_files), final_path
            )
            with pq.ParquetWriter(
                str(final_path), schema, compression="snappy"
            ) as merger:
                for shard_path in shard_files:
                    tbl = pq.read_table(str(shard_path), schema=schema)
                    merger.write_table(tbl)
                    del tbl
                    shard_path.unlink()
                    gc.collect()
            shards_dir.rmdir()
            meta = pq.read_metadata(str(final_path))
            output = str(final_path)

        total_rows = meta.num_rows
        logger.info(
            "[%s] Done: %d rows, %d columns → %s (%d shards, %d/%d schools)",
            step_label,
            total_rows,
            len(schema),
            dest_label,
            shard_idx + 1,
            success_chunks,
            total_schools,
        )
        return output

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_students_base(
        self,
        segment: Literal["EF1", "EF2"],
        year: int | None = None,
    ) -> str:
        """
        Extract the base feature set modeling student definitions within designated segments.

        Returns Path block and sidesteps full structure serialization in pure RAM scopes.

        Args:
            segment (Literal["EF1", "EF2"]): Text flag bounding strict grade tier separations over returned values.
            year (int | None, optional): Numerical target fetching single-year isolated blocks vs aggregate groupings. Defaults to None.

        Raises:
            KeyError: Missing definitions inside filter lookup targets matching explicit inputs over static dictionaries.
            Exception: Pyarrow level interruptions during chunk write-downs or IO bindings.

        Returns:
            Path: pathlib generated reference leading towards fully formed Parquet schema output points.
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

        step_label = f"{segment}_{year}" if year is not None else segment
        path = self._stream_to_parquet(
            query, step_label, _SCHEMA_STUDENTS_BASE, paginated=True
        )
        self._log_ibge_coverage(path, segment)
        return path

    def extract_ef2_grades(self) -> str:
        """
        Extract EF2 subject-level grade dimension constraints mapped onto pivot configurations per student node.

        Args:
            None

        Raises:
            Exception: Failure points bubbling outwards through internal PyArrow execution layers.

        Returns:
            Path: Reference pointing exactly towards destination EF2_grades compiled Parquet file logic block.
        """
        schema = pa.schema(
            [
                ("student_id", pa.string()),
                ("n_disciplinas_total", pa.int16()),
                ("nota_media_geral", pa.float32()),
                ("nota_dispersao", pa.float32()),
                ("n_disciplinas_abaixo5", pa.int16()),
                ("pct_disciplinas_abaixo5", pa.float32()),
                ("trajetoria_media", pa.float32()),
                ("nota_mat_norm", pa.float32()),
                ("nota_lp_norm", pa.float32()),
                ("nota_ciencias_norm", pa.float32()),
                ("nota_historia_norm", pa.float32()),
                ("nota_geo_norm", pa.float32()),
            ]
        )
        logger.info("Extracting EF2 grade pivot...")
        return self._stream_to_parquet(_QUERY_EF2_GRADES, "EF2_grades", schema)

    def extract_school_features(self) -> str:
        """
        Execute general overarching query generating school-level localized aggregate dimensions mapping.

        Args:
            None

        Raises:
            Exception: Any runtime timeout breaking extraction streams midway to storage chunks.

        Returns:
            Path: File representation connecting storage drives locally with target school_features structure.
        """
        schema = pa.schema(
            [
                ("school_id", pa.string()),
                ("school_name", pa.string()),
                ("municipio", pa.string()),
                ("uf", pa.string()),
                ("n_alunos", pa.int32()),
                ("n_com_diario", pa.int32()),
                ("taxa_ausencia_pct", pa.float32()),
                ("n_notas", pa.int32()),
                ("media_nota_escola", pa.float32()),
                ("pct_abaixo5", pa.float32()),
                ("n_com_saude", pa.int32()),
                ("n_desnutridos", pa.int32()),
                ("n_bolsa_familia", pa.int32()),
                ("n_pcd", pa.int32()),
                ("muni_freq_liq_fund", pa.float32()),
                ("muni_analf_adulto", pa.float32()),
                ("est_ideb_af", pa.float32()),
                ("est_taxa_abandono", pa.float32()),
                ("est_taxa_reprovacao", pa.float32()),
            ]
        )
        logger.info("Extracting school-level features...")
        return self._stream_to_parquet(
            _QUERY_SCHOOL_FEATURES, "school_features", schema
        )

    def extract_classroom_features(self, segment: str = "EF1") -> str:
        """
        Extract specific classroom-level feature attributes forming dimension God Matrix nodes.

        Exclude environments smaller than base 5 bounds against extreme statistical drift.

        Args:
            segment (str, optional): Text designation switching parsing between standard segment logic. Defaults to "EF1".

        Raises:
            ValueError: Automatically thrown whenever segment variable mismatches expected "EF1", "EF2" constraints explicitly.
            Exception: Upstream stream connection interrupts terminating mid-layer IO hooks on pyarrow writes.

        Returns:
            Path: Address generating specific access hooks wrapping 'classrooms_<segment>' generated outputs correctly.
        """
        if segment not in ("EF1", "EF2"):
            raise ValueError(f"segment must be 'EF1' or 'EF2', got {segment!r}")

        schema = pa.schema(
            [
                ("school_id", pa.string()),
                ("classroom_name", pa.string()),
                ("classroom_grade", pa.string()),
                ("classroom_stage", pa.string()),
                ("ano_letivo", pa.int16()),
                ("cr_n_alunos", pa.int16()),
                ("cr_n_bolsistas", pa.int16()),
                ("cr_n_pcd", pa.int16()),
                ("cr_n_rural", pa.int16()),
                ("cr_n_risco_saude", pa.int16()),
                ("cr_media_nota", pa.float32()),
                ("cr_dispersao_nota", pa.float32()),
                ("cr_n_notas", pa.int16()),
                ("cr_pct_abaixo5", pa.float32()),
                ("cr_cv_nota_pct", pa.float32()),
                ("cr_taxa_ausencia_pct", pa.float32()),
                ("cr_pct_alunos_com_falta", pa.float32()),
                ("cr_soma_sinais_risco", pa.float32()),
                ("cr_muni_freq_liq_fund", pa.float32()),
                ("cr_muni_analf_adulto", pa.float32()),
                ("cr_muni_atraso_2anos", pa.float32()),
                ("cr_est_ideb_ai", pa.float32()),
                ("cr_est_taxa_abandono", pa.float32()),
                ("cr_est_distorcao_ai", pa.float32()),
                ("cr_n_com_diario", pa.int32()),
                ("cr_total_dias_agendados", pa.int32()),
                ("cr_total_aulas_agendadas", pa.int32()),
                ("cr_n_disciplinas", pa.int16()),
                ("cr_aulas_disciplinas_especificas", pa.int32()),
                ("cr_aulas_per_aluno", pa.float32()),
                ("cr_flag_tem_disciplinas", pa.int8()),
                ("flag_tem_diario", pa.int8()),
                ("flag_tem_notas", pa.int8()),
            ]
        )

        logger.info("Extracting classroom features (segment=%s)...", segment)
        query = _QUERY_CLASSROOM_EF1  # EF2 variant TBD
        return self._stream_to_parquet(query, f"classrooms_{segment}", schema)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _run(
        self, query: str, paginate: bool = True, batch_size: int = 500, **kwargs
    ) -> pd.DataFrame:
        """
        Execute a basic Cypher node query mapping results sequentially back towards single DataFrames.

        Best reserved explicitly towards early stage initialization variables/light metadata lists.

        Args:
            query (str): Cypher syntax code matching graph structures directly.
            paginate (bool, optional): Toggles manual sub-batching through repeated offset query limits. Defaults to True.
            batch_size (int, optional): Caps pagination size limits dictating record counts matching skip limits. Defaults to 500.

        Raises:
            Exception: Neo4j API disconnection parameters falling backwards onto missing driver pools.

        Returns:
            pd.DataFrame: Consolidated mapping combining all iterative extracted layers back across combined axis values.
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

    def _log_ibge_coverage(self, parquet_path: str, segment: str) -> None:
        """
        Log precise statistics about generated proxy coverage arrays mapping without heavy structure serialization limits.

        Reads targeted properties strictly isolating specified columns inside target PyArrow spaces natively.

        Args:
            parquet_path (Path): Pathlib argument dictating which precise generated dataset to investigate.
            segment (str): Name bounds tracking targeted logging output identifiers cleanly.

        Raises:
            Exception: If generic parsing execution breaks from missing library functions dynamically injected midway.

        Returns:
            None
        """
        try:
            if self._azure:
                col = pq.read_table(
                    parquet_path, columns=["muni_freq_fonte"], filesystem=self._fs
                ).column("muni_freq_fonte")
            else:
                col = pq.read_table(parquet_path, columns=["muni_freq_fonte"]).column(
                    "muni_freq_fonte"
                )
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
                segment,
                proxy_pct,
            )
        else:
            logger.info(
                "%s: IBGE freq coverage — %.0f%% municipal, %.0f%% UF proxy",
                segment,
                100 - proxy_pct,
                proxy_pct,
            )

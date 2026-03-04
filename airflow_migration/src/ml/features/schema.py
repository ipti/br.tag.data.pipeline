# ── Identity columns (drop before training, keep for joins and writebacks) ────
ID_COLS = ["student_id", "school_id", "uf"]

# ── Targets ───────────────────────────────────────────────────────────────────
TARGET_DROPOUT = "target_evasao"  # binary 0/1 — absence > 25% of scheduled days
TARGET_GRADE = "target_nota"  # float 0.0–10.0 — normalized final_mean
TARGET_REPROVACAO = "target_reprovacao"  # binary 0/1 — final_mean_norm < 5.0

# ── Demographic features (Student node) ──────────────────────────────────────
# Source: stu.gender, stu.ethnicity, stu.deficiency (STRING not bool),
#         stu.bolsa_familia (bool), stu.residence_zone
# See neo4_schema_and_tips.md §2 for correct property names and types.
DEMO_FEATURES = [
    "gender_bin",  # 0=male, 1=female — from stu.gender =~ '(?i)^F.*'
    "ethnicity_enc",  # 0–5 label encoded — see ETHNICITY_ENCODING below
    "has_deficiency",  # 0/1 — STARTS WITH 'Possui' on stu.deficiency (STRING, not boolean!)
    "bolsa_familia",  # 0/1 — coalesce(stu.bolsa_familia, false)
    "residence_zone_enc",  # 0=Rural, 1=Urban, 2=Not Reported
]

# ── Health features (Health node — OPTIONAL via HAS_HEALTH) ──────────────────
# Source: (stu)-[:HAS_HEALTH]->(h:Health)
# Not all students have this node. Absence ≠ no conditions — it is missing data.
# See neo4_schema_and_tips.md §4.2 for sparsity documentation.
# CRITICAL: property names are h.malnutrition, h.diabetes (NOT h.malnutrition_desease)
HEALTH_FEATURES = [
    "has_health_record",  # 0/1 — whether the Health node exists at all
    "has_malnutrition",  # 0/1 — h.malnutrition (boolean, correct name)
    "has_diabetes",  # 0/1 — h.diabetes (boolean, correct name)
    "has_hypertension",  # 0/1 — h.hypertension
    "has_obesity",  # 0/1 — h.obesity
    "has_celiac",  # 0/1 — h.celiac
    "has_anemia",  # 0/1 — h.iron_deficiency_anemia OR h.sickle_cell_anemia
    "n_health_conditions",  # int — sum of all boolean conditions above
]

# ── Attendance features (StudentClass node — OPTIONAL via ATTENDED) ───────────
# Source: (sc:StudentClass)-[:ATTENDED]->(stu)  ← direction is StudentClass → Student
# Only exists for schools using electronic attendance journal.
# If school has no journal: ZERO StudentClass nodes for ALL its students.
# DO NOT infer 0 absences when node is missing — it is missing data.
# See neo4_schema_and_tips.md §4.1 for electronic journal coverage sparsity.
FREQ_FEATURES = [
    "tem_diario",  # 0/1 — flag: does school use electronic journal?
    "taxa_ausencia",  # float — null when tem_diario=0 (missing data, not zero)
    "falta_critica",  # 0/1 — taxa_ausencia > 10% threshold
    "total_faltas_abs",  # int — raw count of absence days
]

# ── EF1 grade features (StudentDiscipline WHERE discipline_name = '') ─────────
# Source: (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
# EF1 has ONE record per student with discipline_name = '' (global grade).
# Grades may be on 0–100 scale (legacy) or 0–10 scale (current).
# Normalization: CASE WHEN val > 10 THEN val/10.0 ELSE val END — done in Cypher.
GRADE_EF1_FEATURES = [
    "nota_final_norm",  # float 0–10, normalized — sd.final_mean
    "nota_g1_norm",  # float 0–10, normalized — sd.grade_1 (first bimester)
    "nota_g2_norm",  # float 0–10, normalized — sd.grade_2
    "trajetoria_nota",  # float (can be negative) — nota_final_norm - nota_g1_norm
    "em_recuperacao",  # 0/1 — nota_final_norm < 5.0
]

# ── EF2 grade features (StudentDiscipline WHERE discipline_name <> '') ────────
# EF2 has N records per student, one per subject (discipline_name is non-empty).
# These are pivoted in the EF2 query: avg per subject, global aggregates.
GRADE_EF2_FEATURES = [
    "nota_mat_norm",  # float — Matemática final mean normalized
    "nota_lp_norm",  # float — Português final mean normalized
    "nota_ciencias_norm",  # float — Ciências final mean normalized
    "nota_historia_norm",  # float — História final mean normalized
    "nota_geo_norm",  # float — Geografia final mean normalized
    "nota_media_geral",  # float — avg across all disciplines
    "nota_dispersao",  # float — stDev across all disciplines
    "n_disciplinas_total",  # int — count of distinct disciplines with grades
    "n_disciplinas_abaixo5",  # int — count of disciplines where final < 5.0
    "pct_disciplinas_abaixo5",  # float — n_abaixo5 / n_total
    "trajetoria_media",  # float — avg(final_norm) - avg(g1_norm)
]

# ── Classroom context ─────────────────────────────────────────────────────────
CLASSROOM_FEATURES = [
    "stage_enc",  # 0=EI, 1=EF1, 2=EF2, 3=EM, 4=Superior, 5=EJA
    "grade_level_enc",  # ordinal 0–10 — see GRADE_LEVEL_ENCODING
    "ano_letivo",  # int — school year (cr.year)
]

# ── Municipal IBGE context (Municipality node — may be NULL) ──────────────────
# Many small municipalities have NULL values in Atlas fields.
# Estimated 30–50% nulls for equity-related fields.
# ALL of these are computed in Cypher with same-UF municipality average as fallback.
# See CYPHER-QUERY-MATRIX-ML.md §Fallback IBGE for the fallback pattern.
MUNICIPAL_FEATURES = [
    "muni_freq_liq_fund",  # m.atl_freq_liq_fund → % net attendance rate in municipality
    "muni_atraso_2anos",  # m.atl_atraso_2_fund → % students 2+ years behind in municipality
    "muni_analf_adulto",  # m.atl_t_analf25m → % adult illiteracy (proxy for family support)
    "muni_expectativa_estudo",  # m.atl_expectativa_estudo_18 → expected years of study at age 18
    "muni_pct_negro_pub",  # m.atl_negro_mat_pub_fund → % Black students in public schools
    "muni_internet_negro",  # m.atl_negro_internet_fund → % fund. schools with internet for Black students
    "muni_internet_branco",  # m.atl_branco_internet_fund → % fund. schools with internet for White students
    "muni_delta_freq",  # calculated: taxa_ausencia*100 - (100 - muni_freq_liq_fund)
    # Source flags (not model features — for monitoring and debugging only)
    "muni_freq_fonte",  # 'Municipal' | 'Media_UF_Proxy' — which source was used
    "muni_atraso_fonte",  # same pattern for atraso field
    "muni_analf_fonte",  # same pattern for analf field
]

# ── State QEdu context ────────────────────────────────────────────────────────
STATE_QEDU_FEATURES = [
    "est_ideb_ai",  # st.qedu_ideb_ai — IDEB early years
    "est_ideb_af",  # st.qedu_ideb_af — IDEB final years
    "est_taxa_abandono",  # st.qedu_taxa_abandono — official dropout rate
    "est_taxa_reprovacao",  # st.qedu_taxa_reprovacao — official failure rate
    "est_fluxo_af",  # st.qedu_fluxo_af — school flow (0=full retention, 1=perfect)
    "est_pct_fora_escola",  # st.qedu_pct_fora_escola — % children out of school
    "est_distorcao_serie",  # qedu_distorcao_ef{N} matched to grade_level (e.g., ef6 for 6th year)
    "est_lp_insuf_af",  # st.qedu_lp_insuficiente_af — % insufficient LP proficiency
    "est_mat_insuf_af",  # st.qedu_mt_insuficiente_af — % insufficient Math proficiency
    "est_lp_adequado_af",  # st.qedu_lp_adequado_af — % adequate LP proficiency
    "est_mat_adequado_af",  # st.qedu_mt_adequado_af — % adequate Math proficiency
    "est_aprendizado_af",  # st.qedu_aprendizado_af — learning score (state level)
]

# ── State PNAD context (racial and gender equity) ─────────────────────────────
# NOTE: racial illiteracy fields exist on State (PNAD), NOT on Municipality (Atlas).
# Municipality does NOT have atl_branco_analf25m or atl_negro_analf25m.
# See neo4_schema_and_tips.md §8 for properties that do NOT exist.
STATE_PNAD_FEATURES = [
    "est_analf_negro",  # st.negro_pnad_t_analf25m
    "est_analf_branco",  # st.branco_pnad_t_analf25m
    "est_atraso_negro",  # st.negro_pnad_t_atraso_fund
    "est_atraso_branco",  # st.branco_pnad_t_atraso_fund
    "est_analf_homem",  # st.homem_pnad_t_analf25m
    "est_analf_mulher",  # st.mulher_pnad_t_analf25m
    "est_rdpc_negro",  # st.negro_pnad_rdpc — per capita income Black (equity proxy)
    "est_rdpc_branco",  # st.branco_pnad_rdpc — per capita income White
]

# ── Classroom context features (from Q15 God Matrix) ─────────────────────────
# Source: Neo4jExtractor.extract_classroom_features()
# These are classroom-level aggregates joined back to student rows.
# Join keys: (school_id, classroom_name, ano_letivo)
# Prefix cr_ distinguishes classroom-level from student-level columns.
# Q8 composite signal (cr_soma_sinais_risco) is normalized 0–1 per classroom.
CLASSROOM_CONTEXT_FEATURES = [
    "cr_n_alunos",  # int — total students in classroom
    "cr_n_bolsistas",  # int — BF students count
    "cr_n_pcd",  # int — PCD students count
    "cr_n_rural",  # int — rural students count
    "cr_n_risco_saude",  # int — students with health risk conditions (Q8 health dimension)
    "cr_media_nota",  # float — classroom average grade (0–10 normalized)
    "cr_dispersao_nota",  # float — stDev of grades in classroom
    "cr_cv_nota_pct",  # float — coefficient of variation % (Q1 polarization signal)
    "cr_pct_abaixo5",  # float — % students failing (nota < 5)
    "cr_taxa_ausencia_pct",  # float — classroom attendance rate %
    "cr_pct_alunos_com_falta",  # float — % students with at least one recorded absence
    "cr_soma_sinais_risco",  # float 0–1 — Q8 composite (0.40 faltas + 0.35 notas + 0.25 saúde)
    "cr_muni_freq_liq_fund",  # float — IBGE net attendance rate (UF proxy if null)
    "cr_muni_analf_adulto",  # float — IBGE adult illiteracy (UF proxy if null)
    "cr_est_taxa_abandono",  # float — state official dropout rate (QEdu)
    "flag_tem_diario",  # 0/1 — classroom has electronic attendance journal
    "flag_tem_notas",  # 0/1 — classroom has registered grades
]

# ── Features derivadas de queries analíticas — futura inclusão ────────────────
# These features require additional extraction queries or post-processing.
# They are documented here so schema.py remains the single source of truth.
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

# ── Full feature sets per model ───────────────────────────────────────────────
FEATURES_EVASAO_EF1 = (
    DEMO_FEATURES
    + HEALTH_FEATURES
    + FREQ_FEATURES
    + GRADE_EF1_FEATURES
    + CLASSROOM_FEATURES
    + MUNICIPAL_FEATURES
    + STATE_QEDU_FEATURES
    + STATE_PNAD_FEATURES
)

# ── Enriched feature set: EF1 + classroom context (for models that benefit from turma context) ──
FEATURES_EVASAO_EF1_ENRICHED = FEATURES_EVASAO_EF1 + CLASSROOM_CONTEXT_FEATURES

FEATURES_NOTAS_EF2 = (
    DEMO_FEATURES
    + HEALTH_FEATURES
    + FREQ_FEATURES
    + GRADE_EF2_FEATURES
    + CLASSROOM_FEATURES
    + MUNICIPAL_FEATURES
    + STATE_QEDU_FEATURES
    + STATE_PNAD_FEATURES
)

# Columns that must NEVER be null after imputation (checked in test suite)
NEVER_NULL_AFTER_IMPUTE = [
    "gender_bin",
    "bolsa_familia",
    "has_deficiency",
    "tem_diario",
    "has_health_record",
    "stage_enc",
    "grade_level_enc",
    "ano_letivo",
    "n_health_conditions",
]

# ── Encoding dictionaries ─────────────────────────────────────────────────────
STAGE_ENCODING = {
    "EDUCAÇÃO INFANTIL": 0,
    "ENSINO FUNDAMENTAL": 1,  # used for both EF1 and EF2 — grade_level_enc differentiates
    "ENSINO MÉDIO": 2,
    "ENSINO SUPERIOR": 3,
    "EDUCAÇÃO DE JOVENS E ADULTOS": 4,
    "MULTIETAPA": 5,
    "EDUCAÇÃO PROFISSIONAL": 6,
}

GRADE_LEVEL_ENCODING = {
    # EI
    "NA PRÉ-ESCOLA": 0,
    "NA CRECHE": 0,
    "NA EDUCAÇÃO INFANTIL": 0,
    # EF1
    "NO 1* ANO": 1,
    "NO 2* ANO": 2,
    "NO 3* ANO": 3,
    "NO 4* ANO": 4,
    "NO 5* ANO": 5,
    # EF2
    "NO 6* ANO": 6,
    "NO 7* ANO": 7,
    "NO 8* ANO": 8,
    "NO 9* ANO": 9,
    # Legacy série format — see neo4_schema_and_tips.md §5 for disambiguation
    "NA 1* SÉRIE": 1,  # EF only when stage = ENSINO FUNDAMENTAL
    "NA 2* SÉRIE": 2,
    "NA 3* SÉRIE": 3,
    "NA 4* SÉRIE": 4,
    "NA 5* SÉRIE": 5,
    "NA 6* SÉRIE": 6,
    "NA 7* SÉRIE": 7,
    "NA 8* SÉRIE": 8,
    "NA 9* SÉRIE": 9,
}

ETHNICITY_ENCODING = {
    "Branca": 0,
    "Parda": 1,
    "Preta": 2,
    "Amarela": 3,
    "Indígena": 4,
    "Não Declarada": 5,
    "": 5,  # empty string treated as not declared
}

RESIDENCE_ENCODING = {
    "Rural": 0,
    "Urbana": 1,
    "Não Informado": 2,
    None: 2,
}

# Source labels for IBGE fallback monitoring
IBGE_SOURCE_MUNICIPAL = "Municipal"
IBGE_SOURCE_UF_PROXY = "Media_UF_Proxy"

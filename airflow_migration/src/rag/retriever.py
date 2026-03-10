import logging
from typing import Any
from neo4j import Driver
import numpy as np

from src.embeddings.student_embedder import get_model

logger = logging.getLogger(__name__)

_STUDENT_CONTEXT = """
MATCH (s:Student {id: $student_id})
OPTIONAL MATCH (s)-[:ENROLLED_IN]->(c)
OPTIONAL MATCH (c)<-[:ENROLLED_IN]-(s)-[:ENROLLED_AT_SCHOOL]->(sch:School)
OPTIONAL MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
OPTIONAL MATCH (m)-[:BELONGS_TO_STATE]->(st:State)


OPTIONAL MATCH (s)-[:HAS_HEALTH_RECORD]->(h:Health)
OPTIONAL MATCH (s)-[:HAS_GRADES]->(g:Grades)

RETURN 
    s.id AS id,
    s.gender_bin AS gender_bin,
    s.ethnicity_raw AS ethnicity,
    s.bolsa_familia AS bolsa_familia,
    s.has_deficiency AS has_deficiency,
    s.residence_zone_enc AS residence_zone_enc,
    s.risk_score AS risk_score,
    s.risk_cluster AS risk_cluster,
    
    coalesce(0, null) AS taxa_ausencia,
    0 AS tem_diario,
    null AS total_faltas,
    
    collect(DISTINCT {
        disciplina: g.subject,
        nota_g1: g.grade_g1,
        nota_final: g.final_grade
    }) AS notas,
    
    {
        tem_registro: h IS NOT NULL,
        malnutrition: coalesce(h.malnutrition, false),
        diabetes: coalesce(h.diabetes, false),
        obesity: coalesce(h.obesity, false),
        hypertension: coalesce(h.hypertension, false),
        celiac: coalesce(h.celiac, false),
        anemia: coalesce(h.anemia, false)
    } AS saude,
    
    c.name AS classroom_name,
    c.grade_level AS grade_level,
    c.year AS ano_letivo,
    
    sch.name AS school_name,
    sch.id AS school_id,
    m.name AS municipio,
    st.uf AS uf,
    
    null AS freq_liq_escola,
    m.atl_freq_liq_fund AS freq_liq_muni,
    m.atl_t_analfabetismo_15m AS analf_adulto_muni,
    "IBGE" AS fonte_freq_ibge,
    
    st.qedu_ideb_af AS est_ideb_af,
    st.qedu_taxa_abandono AS est_abandono
"""

_CLASSROOM_CONTEXT = """
MATCH (c:Classroom {id: $classroom_id})
MATCH (c)<-[:ENROLLED_IN]-(:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (m)-[:BELONGS_TO_STATE]->(st:State)


// Agregar Alunos da turma
MATCH (s)-[:ENROLLED_IN]->(c)
OPTIONAL MATCH (s)-[:HAS_HEALTH]->(h:Health)
OPTIONAL MATCH (s)-[:HAS_GRADES]->(g:Grades)

WITH c, sch, m, st, count(DISTINCT s) AS n_alunos,
     sum(toInteger(s.bolsa_familia)) AS n_bolsistas,
     sum(toInteger(s.has_deficiency)) AS n_pcd,
     sum(CASE WHEN s.residence_zone_enc = 0 THEN 1 ELSE 0 END) AS n_rural,
     
     avg(0) AS media_ausencia,
     sum(CASE WHEN 0 > 25 THEN 1 ELSE 0 END) AS n_falta_critica,
     max(0) AS tem_diario,
     
     avg(g.final_grade) AS media_nota,
     stDev(g.final_grade) AS dispersao_nota,
     sum(CASE WHEN g.final_grade < 5 THEN 1 ELSE 0 END) AS n_abaixo_5,
     count(g) > 0 AS tem_notas,
     
     sum(CASE WHEN h IS NOT NULL AND 
         (h.malnutrition=true OR h.anemia=true OR h.obesity=true OR h.diabetes=true) 
         THEN 1 ELSE 0 END) AS n_risco_saude

// Calcular sinal de risco composto
WITH *,
     (CASE WHEN n_alunos > 0 THEN toFloat(n_bolsistas)/n_alunos ELSE 0 END) +
     (CASE WHEN n_alunos > 0 THEN toFloat(n_falta_critica)/n_alunos ELSE 0 END) +
     (CASE WHEN tem_notas AND n_alunos > 0 THEN toFloat(n_abaixo_5)/(n_alunos*8) ELSE 0 END) +
     (CASE WHEN n_alunos > 0 THEN toFloat(n_risco_saude)/n_alunos ELSE 0 END) AS soma_sinais_risco

RETURN 
    c.id AS classroom_id,
    c.name AS classroom_name,
    c.grade_level AS grade_level,
    c.stage AS stage,
    
    n_alunos, n_bolsistas, n_pcd, n_rural, n_risco_saude,
    
    media_ausencia AS taxa_ausencia_pct,
    CASE WHEN n_alunos > 0 THEN (toFloat(n_falta_critica)/n_alunos)*100 ELSE 0 END AS pct_com_falta,
    tem_diario,
    
    media_nota,
    dispersao_nota,
    CASE WHEN media_nota > 0 THEN (dispersao_nota/media_nota)*100 ELSE null END AS cv_nota_pct,
    CASE WHEN tem_notas AND n_alunos > 0 THEN (toFloat(n_abaixo_5)/(n_alunos*8))*100 ELSE 0 END AS pct_abaixo5,
    tem_notas,
    
    soma_sinais_risco,
    
    sch.name AS school_name,
    m.name AS municipio,
    st.uf AS uf,
    
    m.atl_freq_liq_fund AS muni_freq_liq,
    "IBGE" AS fonte_freq_ibge,
    st.qedu_ideb_af AS est_ideb_af,
    st.qedu_taxa_abandono AS est_abandono
"""

_SCHOOL_CONTEXT = """
MATCH (sch:School {id: $school_id})
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)

MATCH (s)-[:ENROLLED_IN]->(c)
MATCH (s)-[:ENROLLED_AT_SCHOOL]->(sch)
OPTIONAL MATCH (s)-[:HAS_HEALTH]->(h:Health)
OPTIONAL MATCH (s)-[:HAS_GRADES]->(g:Grades)

WITH sch, m, st, count(DISTINCT s) AS n_alunos,
     count(DISTINCT c) AS n_turmas,
     
     // Presença
     avg(0) AS media_ausencia,
     sum(CASE WHEN 0 > 25 THEN 1 ELSE 0 END) AS n_falta_critica,
     max(0) AS tem_diario,
     
     // Desempenho
     avg(g.final_grade) AS media_nota,
     stDev(g.final_grade) AS dispersao_nota,
     sum(CASE WHEN g.final_grade < 5 THEN 1 ELSE 0 END) AS n_abaixo_5,
     count(g) > 0 AS tem_notas,
     
     // Equidade (Bolsa Familia gap)
     sum(toInteger(s.bolsa_familia)) AS n_bolsistas,
     avg(CASE WHEN s.bolsa_familia = true THEN g.final_grade ELSE null END) AS media_nota_bf,
     avg(CASE WHEN s.bolsa_familia = false THEN g.final_grade ELSE null END) AS media_nota_nobf,
     sum(toInteger(s.has_deficiency)) AS n_pcd,
     sum(CASE WHEN s.residence_zone_enc = 0 THEN 1 ELSE 0 END) AS n_rural,
     
     // Saúde
     sum(CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END) AS n_com_saude,
     sum(toInteger(h.malnutrition)) AS n_desnutridos,
     sum(toInteger(h.diabetes)) AS n_diabetes,
     sum(toInteger(h.obesity)) AS n_obesidade

RETURN 
    sch.id AS school_id,
    sch.name AS school_name,
    m.name AS municipio,
    st.uf AS uf,
    
    n_alunos, n_turmas,
    
    media_ausencia AS taxa_ausencia_pct,
    n_falta_critica,
    tem_diario,
    
    media_nota, dispersao_nota, tem_notas,
    CASE WHEN tem_notas AND n_alunos > 0 THEN (toFloat(n_abaixo_5)/(n_alunos*8))*100 ELSE 0 END AS pct_abaixo5,
    
    CASE WHEN n_alunos > 0 THEN (toFloat(n_bolsistas)/n_alunos)*100 ELSE 0 END AS pct_bolsa_familia,
    media_nota_bf, media_nota_nobf,
    (media_nota_bf - media_nota_nobf) AS gap_bf,
    n_pcd, n_rural,
    
    n_com_saude, n_desnutridos, n_diabetes, n_obesidade,
    
    m.atl_freq_liq_fund AS muni_freq_liq,
    m.atl_atraso_2_fund AS muni_atraso,
    m.atl_t_analfabetismo_15m AS muni_analf,
    m.atl_esperanca_anos_estudo AS muni_expectativa,
    "IBGE" AS fonte_freq_ibge,
    
    st.qedu_ideb_af AS est_ideb_af,
    st.qedu_taxa_abandono AS est_abandono,
    st.qedu_taxa_reprovacao AS est_reprovacao,
    st.qedu_distorcao_ef_af AS est_distorcao_af,
    st.qedu_lp_adequado_af AS est_lp_adequado,
    st.qedu_mt_adequado_af AS est_mat_adequado
"""

_MUNICIPALITY_CONTEXT = """
MATCH (m:Municipality {id: $municipality_id})-[:BELONGS_TO_STATE]->(st:State)

MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m)
OPTIONAL MATCH (s:Student)-[:ATTENDED]->(:StudentClass)-[:BELONGS_TO]->(:Classroom)
OPTIONAL MATCH (s)-[:ENROLLED_AT_SCHOOL]->(sch)

WITH m, st, sch,
     count(DISTINCT s) AS sch_alunos,
     avg(s.risk_score) AS sch_risco,
     sum(toInteger(s.bolsa_familia)) AS sch_bf

// Precisamos do score macro de presença e nota por escola para rankear, extraído previamente
WITH m, st, collect({
         school_id: sch.id,
         school_name: sch.name,
         n_alunos: sch_alunos,
         pct_bf: CASE WHEN sch_alunos>0 THEN (toFloat(sch_bf)/sch_alunos)*100 ELSE 0 END
     }) AS escolas,
     sum(sch_alunos) AS total_alunos,
     count(DISTINCT sch) AS n_escolas,
     0 AS media_ausencia_muni,
     0 AS media_nota_muni

RETURN
    m.id AS municipality_id,
    m.name AS municipio,
    st.uf AS uf,
    
    n_escolas, total_alunos, media_ausencia_muni, media_nota_muni,
    escolas,
    
    m.atl_freq_liq_fund AS muni_freq_liq,
    m.atl_atraso_2_fund AS muni_atraso_2anos,
    m.atl_t_analfabetismo_15m AS muni_analf,
    m.atl_esperanca_anos_estudo AS muni_expectativa,
    "IBGE" AS fonte_freq_ibge,
    
    m.atl_negro_pub AS muni_negro_pub,
    m.atl_negro_internet AS muni_negro_internet,
    
    st.qedu_ideb_af AS est_ideb_af,
    st.qedu_taxa_abandono AS est_abandono,
    st.qedu_taxa_reprovacao AS est_reprovacao,
    st.qedu_distorcao_ef_af AS est_distorcao_af,
    st.qedu_pct_fora_escola AS est_pct_fora_escola,
    
    st.negro_pnad_t_analf25m AS est_analf_negro,
    st.branco_pnad_t_analf25m AS est_analf_branco,
    st.negro_pnad_t_atraso_fund AS est_atraso_negro,
    st.branco_pnad_t_atraso_fund AS est_atraso_branco
"""

_STATE_CONTEXT = """
MATCH (st:State {uf: $uf})

MATCH (m:Municipality)-[:BELONGS_TO_STATE]->(st)

WITH st, count(DISTINCT m) AS n_municipios, sum(sq.matriculas_fund_em) AS total_matriculas,
     collect({
         municipio: m.name,
         muni_analf: m.atl_t_analfabetismo_15m,
         muni_atraso: m.atl_atraso_2_fund,
         muni_expectativa: m.atl_esperanca_anos_estudo
     }) AS municipios

RETURN
    st.uf AS uf,
    st.name AS nome_estado,
    n_municipios,
    total_matriculas,
    
    st.qedu_ideb_ai AS ideb_ai,
    st.qedu_ideb_af AS ideb_af,
    st.qedu_ideb_em AS ideb_em,
    
    st.qedu_fluxo_ai AS fluxo_ai,
    st.qedu_fluxo_af AS fluxo_af,
    st.qedu_taxa_abandono AS abandono,
    st.qedu_taxa_reprovacao AS reprovacao,
    st.qedu_distorcao_ef_ai AS distorcao_ai,
    st.qedu_distorcao_ef_af AS distorcao_af,
    st.qedu_pct_fora_escola AS pct_fora_escola,
    
    st.qedu_lp_adequado_ai AS lp_adequado_ai,
    st.qedu_mt_adequado_ai AS mat_adequado_ai,
    st.qedu_lp_adequado_af AS lp_adequado_af,
    st.qedu_mt_adequado_af AS mat_adequado_af,
    st.qedu_lp_insuficiente_af AS lp_insuf_af,
    st.qedu_mt_insuficiente_af AS mat_insuf_af,
    
    st.negro_pnad_t_analf25m AS analf_negro,
    st.branco_pnad_t_analf25m AS analf_branco,
    st.homem_pnad_t_analf25m AS analf_homem,
    st.mulher_pnad_t_analf25m AS analf_mulher,
    
    st.negro_pnad_t_atraso_fund AS atraso_negro,
    st.branco_pnad_t_atraso_fund AS atraso_branco,
    st.negro_pnad_t_flfund AS freq_fund_negro,
    st.branco_pnad_t_flfund AS freq_fund_branco,
    st.homem_pnad_t_flfund AS freq_fund_homem,
    st.mulher_pnad_t_flfund AS freq_fund_mulher,
    
    st.negro_pnad_t_med18a20 AS med18_negro,
    st.branco_pnad_t_med18a20 AS med18_branco,
    
    st.negro_pnad_idhm_e AS idhm_e_negro,
    st.branco_pnad_idhm_e AS idhm_e_branco,
    st.homem_pnad_anosest AS anosest_homem,
    st.mulher_pnad_anosest AS anosest_mulher,
    
    municipios
"""

_SIMILAR_STUDENTS = """
CALL db.index.vector.queryNodes('student_embeddings', $top_k, $embedding)
YIELD node AS sim_student, score
WHERE sim_student.id <> $student_id
MATCH (sim_student)-[:ENROLLED_IN]->(:Classroom)
MATCH (sim_student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
RETURN 
    sim_student.id AS id,
    sim_student.risk_cluster AS cluster,
    sim_student.outcome AS desfecho,
    sch.name AS escola,
    score AS similarity
"""

_SIMILAR_SCHOOLS = """
CALL db.index.vector.queryNodes('school_embeddings', $top_k, $embedding)
YIELD node AS sim_school, score
WHERE sim_school.id <> $school_id
MATCH (sim_school)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
RETURN
    sim_school.id AS id,
    sim_school.name AS escola,
    m.name AS municipio,
    st.uf AS uf,
    sim_school.health_level AS nivel_saude,
    score AS similarity
"""


class Retriever:
    """
    Neo4j context retriever with hierarchical entity context extraction.

    This class encapsulates Cypher queries for educational data retrieval across
    five granularity levels:
    1. Student profiles with risk scores, grades, health records, and similar peer data
    2. Classroom aggregates including risk composition, attendance, and performance metrics
    3. School-wide analytics across four dimensions: presence, performance, equity, and health
    4. Municipality contextual data with school rankings and IBGE socioeconomic indicators
    5. State-level QEDU quality indicators with racial and gender equity breakdowns
    """

    def __init__(self, driver: Driver):
        """
        Initialize the Retriever with a Neo4j driver connection.

        Args:
            driver (Driver): Active Neo4j driver for executing Cypher queries.
        """
        self._driver = driver

    def get_student_context(self, student_id: str) -> dict[str, Any]:
        """
        Extract comprehensive student profile context with demographics, performance, and health data.

        Retrieves a single student's profile including demographic attributes (gender, ethnicity,
        social program enrollment), academic performance (grades by subject), attendance metrics,
        health conditions (malnutrition, diabetes, etc.), classroom assignment, school affiliation,
        and regional IBGE socioeconomic context (municipal liquid enrollment, adult illiteracy,
        state IDEB and dropout rates).

        Args:
            student_id (str): Student identifier (Neo4j node property `Student.id`).

        Returns:
            dict[str, Any]: Nested dictionary with keys:
                - 'perfil': Demographics (gender, ethnicity, bolsa_familia, PCD status, residence_zone, risk_score, cluster)
                - 'frequencia': Attendance (taxa_ausencia, tem_diario, total_faltas)
                - 'notas': List of subject grade records (disciplina, nota_g1, nota_final)
                - 'saude': Health conditions (malnutrition, diabetes, obesity, hypertension, celiac, anemia)
                - 'turma': Classroom details (nome, grade_level, ano_letivo)
                - 'escola_ibge': School and regional IBGE data (nome, municipio, uf, freq_liq, analf_adulto, IDEB, abandono)
            Empty dictionary if student not found.

        Raises:
            No exceptions raised; returns empty dict on lookup failure.
        """
        with self._driver.session() as session:
            res = session.run(_STUDENT_CONTEXT, student_id=student_id).single()
            if not res:
                return {}

            p = {
                "gender": "F" if res["gender_bin"] else "M",
                "ethnicity": res["ethnicity"],
                "bolsa_familia": res["bolsa_familia"],
                "has_deficiency": res["has_deficiency"],
                "residence_zone": (
                    "Rural" if res["residence_zone_enc"] == 0 else "Urbana"
                ),
                "risk_score": res["risk_score"],
                "risk_cluster": res["risk_cluster"],
            }

            f = {
                "taxa_ausencia": res["taxa_ausencia"],
                "tem_diario": res["tem_diario"],
                "total_faltas": res["total_faltas"],
            }

            s = res["saude"]
            t = {
                "nome": res["classroom_name"],
                "grade_level": res["grade_level"],
                "ano_letivo": res["ano_letivo"],
            }
            ei = {
                "nome": res["school_name"],
                "municipio": res["municipio"],
                "uf": res["uf"],
                "muni_freq_liq": res["freq_liq_muni"],
                "muni_analf_adulto": res["analf_adulto_muni"],
                "fonte_freq_ibge": res["fonte_freq_ibge"],
                "est_ideb_af": res["est_ideb_af"],
                "est_taxa_abandono": res["est_abandono"],
            }

            return {
                "perfil": p,
                "frequencia": f,
                "notas": res["notas"],
                "saude": s,
                "turma": t,
                "escola_ibge": ei,
            }

    def get_classroom_context(self, classroom_id: str) -> dict[str, Any]:
        """
        Extract aggregated classroom context with composition, risk, and performance data.

        Retrieves classroom-level metrics computed as aggregates over enrolled students,
        including class size, demographic composition (Bolsa Família %, PCD, rural),
        attendance aggregates (absence rate, critical absence count), performance metrics
        (mean grade, standard deviation, coefficient of variation, below-threshold %), and
        composite risk signal. Also includes school location (municipality, state) and
        IBGE/QEDU benchmarks for regional comparison.

        Args:
            classroom_id (str): Classroom identifier (Neo4j node property `Classroom.id`).

        Returns:
            dict[str, Any]: Flat dictionary containing:
                - Classroom identity: classroom_id, classroom_name, grade_level, stage
                - Composition: n_alunos, n_bolsistas, n_pcd, n_rural, n_risco_saude
                - Attendance: taxa_ausencia_pct, pct_com_falta, tem_diario
                - Performance: media_nota, dispersao_nota, cv_nota_pct, pct_abaixo5, tem_notas
                - Risk: soma_sinais_risco (Q8 composite risk signal, 0–1 scale)
                - Location: school_name, municipio, uf
                - IBGE/QEDU: muni_freq_liq, fonte_freq_ibge, est_ideb_af, est_abandono
            Empty dictionary if classroom not found.

        Raises:
            No exceptions raised; returns empty dict on lookup failure.
        """
        with self._driver.session() as session:
            res = session.run(_CLASSROOM_CONTEXT, classroom_id=classroom_id).single()
            return dict(res) if res else {}

    def get_school_context(self, school_id: str) -> dict[str, Any]:
        """
        Extract school-wide analytics across four key dimensions and IBGE benchmarks.

        Retrieves school-level metrics aggregated over all enrolled students, organized
        in four dimensions:
        1. **Presence**: Absence percentage, critical absence count, electronic diary availability
        2. **Performance**: Mean grade, standard deviation, coefficient of variation, below-threshold %
        3. **Equity**: Bolsa Família enrollment, performance gap by income, PCD and rural counts
        4. **Health**: Students with health records, counts of malnutrition, diabetes, obesity
        Also includes IBGE municipal indicators (liquid enrollment, adult illiteracy, expectations)
        and state QEDU benchmarks (IDEB, dropout rate, misalignment %, proficiency %).

        Args:
            school_id (str): School identifier (Neo4j node property `School.id`).

        Returns:
            dict[str, Any]: Flat dictionary containing:
                - School identity: school_id, school_name, municipio, uf
                - Scope: n_alunos, n_turmas
                - Presence: taxa_ausencia_pct, n_falta_critica, tem_diario
                - Performance: media_nota, dispersao_nota, pct_abaixo5, tem_notas
                - Equity: pct_bolsa_familia, media_nota_bf, media_nota_nobf, gap_bf, n_pcd, n_rural
                - Health: n_com_saude, n_desnutridos, n_diabetes, n_obesidade
                - IBGE: muni_freq_liq, muni_analf, muni_atraso, muni_expectativa, fonte_freq_ibge
                - QEDU: est_ideb_af, est_abandono, est_reprovacao, est_distorcao_af, est_lp_adequado, est_mat_adequado
            Empty dictionary if school not found.

        Raises:
            No exceptions raised; returns empty dict on lookup failure.
        """
        with self._driver.session() as session:
            res = session.run(_SCHOOL_CONTEXT, school_id=school_id).single()
            return dict(res) if res else {}

    def get_municipality_context(self, municipality_id: str) -> dict[str, Any]:
        """
        Extract municipality-wide context with school rankings and socioeconomic indicators.

        Retrieves municipality-level data including school census information, aggregated
        student metrics per school, digital coverage (schools with/without electronic diaries),
        IBGE socioeconomic indicators (enrollment rates, literacy, life expectancy, racial
        public schooling and internet access), and state-level QEDU benchmarks for regional
        comparison and equity analysis.

        Args:
            municipality_id (str): Municipality identifier (Neo4j node property `Municipality.id`).

        Returns:
            dict[str, Any]: Flat dictionary containing:
                - Municipality identity: municipality_id, municipio, uf
                - Scope: n_escolas, total_alunos, media_ausencia_muni, media_nota_muni
                - Schools: escolas (list of dicts with school_id, school_name, n_alunos, pct_bf)
                - IBGE municipal: muni_freq_liq, muni_atraso_2anos, muni_analf, muni_expectativa,
                  fonte_freq_ibge, muni_negro_pub, muni_negro_internet
                - QEDU state: est_ideb_af, est_abandono, est_reprovacao, est_distorcao_af, est_pct_fora_escola
                - PNAD racial: est_analf_negro, est_analf_branco, est_atraso_negro, est_atraso_branco
            Empty dictionary if municipality not found.

        Raises:
            No exceptions raised; returns empty dict on lookup failure.
        """
        with self._driver.session() as session:
            res = session.run(
                _MUNICIPALITY_CONTEXT, municipality_id=municipality_id
            ).single()
            return dict(res) if res else {}

    def get_state_context(self, uf: str) -> dict[str, Any]:
        """
        Extract state-level quality and equity indicators with municipal rankings.

        Retrieves state-wide educational quality metrics from QEDU system (IDEB across
        all school levels, flux rates, grade misalignment %, dropout/repetition rates,
        reading and math proficiency %), demographic equity analysis from PNAD Census
        (literacy gaps by race and gender, high school completion rates, years of study,
        human development index by race), and municipality rankings by vulnerability
        (adult illiteracy, school delay rates).

        Args:
            uf (str): State abbreviation (e.g., 'BA', 'RJ', 'MG'). Case-insensitive;
                automatically converted to uppercase.

        Returns:
            dict[str, Any]: Flat dictionary containing:
                - State identity: uf, nome_estado
                - Scope: n_municipios, total_matriculas
                - IDEB: ideb_ai, ideb_af, ideb_em
                - Flux: fluxo_ai, fluxo_af
                - Misalignment: distorcao_ai, distorcao_af, pct_fora_escola
                - Achievement gaps: lp_adequado_ai, mat_adequado_ai, lp_adequado_af, mat_adequado_af, lp_insuf_af, mat_insuf_af
                - Dropout/repetition: abandono, reprovacao
                - PNAD racial: analf_negro, analf_branco, atraso_negro, atraso_branco, freq_fund_negro, freq_fund_branco,
                  med18_negro, med18_branco, idhm_e_negro, idhm_e_branco
                - PNAD gender: analf_homem, analf_mulher, anosest_homem, anosest_mulher, freq_fund_homem, freq_fund_mulher
                - Municipalities: municipios (list of dicts with name, illiteracy, school delay, life expectancy)
            Empty dictionary if state not found.

        Raises:
            No exceptions raised; returns empty dict on lookup failure.
        """
        with self._driver.session() as session:
            res = session.run(_STATE_CONTEXT, uf=uf.upper()).single()
            return dict(res) if res else {}

    def find_similar_students(
        self, student_id: str, text_representation: str, top_k: int = 5
    ) -> list[dict]:
        """
        Find similar students using multilingual sentence transformer embeddings.

        Encodes a student's narrative profile text using a multilingual embedding model
        and queries the Neo4j vector index `student_embeddings` for semantically similar
        students. Excludes the target student from results and returns basic identifying
        information (ID, risk cluster, educational outcome, school) sorted by cosine similarity.

        Args:
            student_id (str): Target student identifier for similarity search (self-exclusion filter).
            text_representation (str): Student narrative profile generated by `student_to_text()`,
                approximately 100–200 words describing demographics, health, attendance, grades.
            top_k (int, optional): Maximum number of similar students to return. Defaults to 5.

        Returns:
            list[dict]: List of up to `top_k` similar student records, each containing:
                - 'id': Student identifier
                - 'cluster': Risk cluster assignment
                - 'desfecho': Educational outcome
                - 'escola': School name
                - 'similarity': Cosine similarity score (0–1, higher is more similar)
            Empty list if no matches found or vector index unavailable.

        Raises:
            No exceptions raised; returns empty list on embedding/index failure.
        """
        model = get_model()
        emb = model.encode(text_representation, normalize_embeddings=True).tolist()

        with self._driver.session() as session:
            res = session.run(
                _SIMILAR_STUDENTS, embedding=emb, student_id=student_id, top_k=top_k
            )
            return [dict(row) for row in res]

    def find_similar_schools(
        self, school_id: str, text_representation: str, top_k: int = 3
    ) -> list[dict]:
        """
        Find similar schools using multilingual sentence transformer embeddings.

        Encodes a school's narrative profile text using a multilingual embedding model
        and queries the Neo4j vector index `school_embeddings` for semantically similar
        schools. Excludes the target school from results and returns identifying information
        (ID, name, municipality, state, health level) sorted by cosine similarity.

        Args:
            school_id (str): Target school identifier for similarity search (self-exclusion filter).
            text_representation (str): School narrative profile generated by `school_to_text()`,
                approximately 150–300 words describing enrollment, presence, performance, equity, and health.
            top_k (int, optional): Maximum number of similar schools to return. Defaults to 3.

        Returns:
            list[dict]: List of up to `top_k` similar school records, each containing:
                - 'id': School identifier
                - 'escola': School name
                - 'municipio': Municipality name
                - 'uf': State abbreviation
                - 'nivel_saude': Health condition level (categorical)
                - 'similarity': Cosine similarity score (0–1, higher is more similar)
            Empty list if no matches found or vector index unavailable.

        Raises:
            No exceptions raised; returns empty list on embedding/index failure.
        """
        model = get_model()
        emb = model.encode(text_representation, normalize_embeddings=True).tolist()

        with self._driver.session() as session:
            res = session.run(
                _SIMILAR_SCHOOLS, embedding=emb, school_id=school_id, top_k=top_k
            )
            return [dict(row) for row in res]

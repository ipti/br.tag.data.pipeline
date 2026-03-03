# Q_SAUDE_ESCOLA + Q_PROXIMIDADE_ALUNOS
**Versão:** 1.0 — Schema confirmado v5.5 · Padrão coletar→isolar→agregar
**Complemento de:** Q_RISCO_EVASAO_EF2.md

---

## Q_SAUDE_ESCOLA — Score de Saúde Geral da Escola

### Objetivo

Produz uma **nota de 0 a 100** para cada escola, dividida em 4 dimensões. Funciona como um painel executivo: o gestor vê de uma vez quais escolas estão bem, quais precisam de atenção, e em qual dimensão específica o problema está concentrado.

### Modelo de Score

| Dimensão | Peso | Componentes |
|---|---|---|
| **Presença** | 35% | Taxa ausência geral + % falta crítica |
| **Desempenho** | 35% | Média notas + % abaixo de 5 + CV% |
| **Equidade** | 20% | Gap Bolsa Família vs não-BF + Gap PCD vs não-PCD |
| **Cobertura de dados** | 10% | % turmas com diário + % alunos com nota |

Cada dimensão é normalizada 0–10 antes da ponderação, garantindo que uma escola sem diário eletrônico não seja punida injustamente na dimensão Desempenho — mas seja penalizada explicitamente na dimensão Cobertura.

### Variante EF1 (fundamental menor) e EF2 (fundamental II / médio) — escolha o filtro

---

```cypher
// ─────────────────────────────────────────────────────────────────
// ÂNCORA: School com toda a cadeia geográfica + todos os IBGEs
// ─────────────────────────────────────────────────────────────────
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     // ── Contexto Municipal (Atlas IBGE) ──────────────────────────
     coalesce(m.atl_freq_liq_fund,         null) AS MUNI_Freq_Liq,
     coalesce(m.atl_atraso_2_fund,         null) AS MUNI_Atraso_2Anos,
     coalesce(m.atl_t_analf25m,            null) AS MUNI_Analf_Adulto,
     coalesce(m.atl_expectativa_estudo_18, null) AS MUNI_Expectativa_Estudo,

     // ── Contexto Estadual — QEdu ──────────────────────────────────
     coalesce(st.qedu_ideb_ai,             null) AS EST_IDEB_AI,
     coalesce(st.qedu_ideb_af,             null) AS EST_IDEB_AF,
     coalesce(st.qedu_taxa_abandono,       null) AS EST_Taxa_Abandono,
     coalesce(st.qedu_taxa_reprovacao,     null) AS EST_Taxa_Reprovacao,
     coalesce(st.qedu_taxa_aprovacao,      null) AS EST_Taxa_Aprovacao,
     coalesce(st.qedu_fluxo_ai,            null) AS EST_Fluxo_AI,
     coalesce(st.qedu_fluxo_af,            null) AS EST_Fluxo_AF,
     coalesce(st.qedu_distorcao_ef_ai,     null) AS EST_Distorcao_AI,
     coalesce(st.qedu_distorcao_ef_af,     null) AS EST_Distorcao_AF,
     coalesce(st.qedu_pct_fora_escola,     null) AS EST_Pct_Fora_Escola,
     coalesce(st.qedu_aprendizado_ai,      null) AS EST_Aprendizado_AI,
     coalesce(st.qedu_aprendizado_af,      null) AS EST_Aprendizado_AF,
     coalesce(st.qedu_lp_adequado_ai,      null) AS EST_LP_Adequado_AI,
     coalesce(st.qedu_mt_adequado_ai,      null) AS EST_Mat_Adequado_AI,
     coalesce(st.qedu_lp_insuficiente_ai,  null) AS EST_LP_Insuf_AI,
     coalesce(st.qedu_mt_insuficiente_ai,  null) AS EST_Mat_Insuf_AI,

     // ── Contexto Estadual — PNAD racial e gênero ──────────────────
     coalesce(st.negro_pnad_t_atraso_fund,  null) AS EST_Atraso_Negro,
     coalesce(st.branco_pnad_t_atraso_fund, null) AS EST_Atraso_Branco,
     coalesce(st.negro_pnad_t_analf25m,     null) AS EST_Analf_Negro,
     coalesce(st.branco_pnad_t_analf25m,    null) AS EST_Analf_Branco,
     coalesce(st.homem_pnad_t_analf25m,     null) AS EST_Analf_Homem,
     coalesce(st.mulher_pnad_t_analf25m,    null) AS EST_Analf_Mulher

// Fallback: se município não tem freq_liq_fund, usa média da UF
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS UF_Media_Freq
}

WITH sch, m, st,
     MUNI_Freq_Liq, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     coalesce(MUNI_Freq_Liq, UF_Media_Freq) AS Freq_Ref,
     CASE WHEN MUNI_Freq_Liq IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_Freq,
     EST_IDEB_AI, EST_IDEB_AF, EST_Taxa_Abandono, EST_Taxa_Reprovacao, EST_Taxa_Aprovacao,
     EST_Fluxo_AI, EST_Fluxo_AF, EST_Distorcao_AI, EST_Distorcao_AF, EST_Pct_Fora_Escola,
     EST_Aprendizado_AI, EST_Aprendizado_AF,
     EST_LP_Adequado_AI, EST_Mat_Adequado_AI, EST_LP_Insuf_AI, EST_Mat_Insuf_AI,
     EST_Atraso_Negro, EST_Atraso_Branco, EST_Analf_Negro, EST_Analf_Branco,
     EST_Analf_Homem, EST_Analf_Mulher

// ─────────────────────────────────────────────────────────────────
// PASSO 1: coleta todos os alunos da escola
// TROQUE o filtro abaixo para EF1 ou EF2 conforme necessário:
//
//   EF1 (Fundamental Menor):
//     cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
//     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
//     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
//
//   EF2 + EM (Fundamental II / Médio):
//     cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
//     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
//     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
// ─────────────────────────────────────────────────────────────────
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  RETURN collect(DISTINCT stu) AS ListaAlunos,
         count(DISTINCT cr)    AS N_Turmas_Total
}

WITH sch, m, st, ListaAlunos, N_Turmas_Total,
     Freq_Ref, Fonte_Freq,
     MUNI_Freq_Liq, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     EST_IDEB_AI, EST_IDEB_AF, EST_Taxa_Abandono, EST_Taxa_Reprovacao, EST_Taxa_Aprovacao,
     EST_Fluxo_AI, EST_Fluxo_AF, EST_Distorcao_AI, EST_Distorcao_AF, EST_Pct_Fora_Escola,
     EST_Aprendizado_AI, EST_Aprendizado_AF,
     EST_LP_Adequado_AI, EST_Mat_Adequado_AI, EST_LP_Insuf_AI, EST_Mat_Insuf_AI,
     EST_Atraso_Negro, EST_Atraso_Branco, EST_Analf_Negro, EST_Analf_Branco,
     EST_Analf_Homem, EST_Analf_Mulher

WHERE size(ListaAlunos) >= 15

// ─────────────────────────────────────────────────────────────────
// DIMENSÃO PRESENÇA — faltas (isolada)
// ─────────────────────────────────────────────────────────────────
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))           AS TotalFaltas,
    sum(coalesce(sc.scheduled_student_class_days, 200)) AS TotalDias,
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0      THEN stu END) AS N_ComFalta,
    count(DISTINCT CASE WHEN sc IS NOT NULL
                         AND sc.scheduled_student_class_days > 0
                         AND toFloat(sc.total_faults_per_day) /
                             sc.scheduled_student_class_days > 0.10              THEN stu END) AS N_FaltaCritica,
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS N_TurmComDiario_Proxy
}

// ─────────────────────────────────────────────────────────────────
// DIMENSÃO DESEMPENHO — notas globais (isolada)
// ─────────────────────────────────────────────────────────────────
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''        // nota global (EF1)
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN
    count(Nota)                                  AS N_Notas,
    round(avg(Nota), 2)                          AS Media_Global,
    round(stDev(Nota), 2)                        AS Dispersao_Global,
    count(CASE WHEN Nota < 5.0 THEN 1 END)       AS N_Abaixo5,
    count(CASE WHEN Nota < 3.0 THEN 1 END)       AS N_Abaixo3,
    count(CASE WHEN Nota >= 7.0 THEN 1 END)      AS N_Acima7
}

// ─────────────────────────────────────────────────────────────────
// DIMENSÃO EQUIDADE — notas por grupo social (isolada)
// Compara BF vs não-BF e PCD vs não-PCD para medir gap interno
// ─────────────────────────────────────────────────────────────────
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH stu,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN
    // Bolsa Família gap
    round(avg(CASE WHEN coalesce(stu.bolsa_familia, false) = true  THEN Nota END), 2) AS Media_BF,
    round(avg(CASE WHEN coalesce(stu.bolsa_familia, false) = false THEN Nota END), 2) AS Media_NaoBF,
    // PCD gap
    round(avg(CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN Nota END), 2) AS Media_PCD,
    round(avg(CASE WHEN NOT coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN Nota END), 2) AS Media_NaoPCD
}

// ─────────────────────────────────────────────────────────────────
// PERFIL SOCIAL — list comprehension (sem UNWIND extra)
// ─────────────────────────────────────────────────────────────────
WITH sch, m, st, ListaAlunos, N_Turmas_Total,
     Freq_Ref, Fonte_Freq,
     MUNI_Freq_Liq, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     EST_IDEB_AI, EST_IDEB_AF, EST_Taxa_Abandono, EST_Taxa_Reprovacao, EST_Taxa_Aprovacao,
     EST_Fluxo_AI, EST_Fluxo_AF, EST_Distorcao_AI, EST_Distorcao_AF, EST_Pct_Fora_Escola,
     EST_Aprendizado_AI, EST_Aprendizado_AF,
     EST_LP_Adequado_AI, EST_Mat_Adequado_AI, EST_LP_Insuf_AI, EST_Mat_Insuf_AI,
     EST_Atraso_Negro, EST_Atraso_Branco, EST_Analf_Negro, EST_Analf_Branco,
     EST_Analf_Homem, EST_Analf_Mulher,
     TotalFaltas, TotalDias, N_ComFalta, N_FaltaCritica, N_TurmComDiario_Proxy,
     N_Notas, Media_Global, Dispersao_Global, N_Abaixo5, N_Abaixo3, N_Acima7,
     Media_BF, Media_NaoBF, Media_PCD, Media_NaoPCD,

     size(ListaAlunos) AS N_Alunos,
     size([s IN ListaAlunos WHERE coalesce(s.bolsa_familia, false) = true])           AS N_BolsaFamilia,
     size([s IN ListaAlunos WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS N_PCD

// ─────────────────────────────────────────────────────────────────
// CÁLCULO DAS MÉTRICAS DERIVADAS
// ─────────────────────────────────────────────────────────────────
WITH *,
     // Taxa de ausência geral da escola (%)
     CASE WHEN TotalDias > 0
          THEN round(toFloat(TotalFaltas) / TotalDias * 100, 2)
          ELSE null END AS Taxa_Ausencia_Pct,

     // CV% — coeficiente de variação (heterogeneidade)
     CASE WHEN Media_Global > 0 AND Dispersao_Global IS NOT NULL
          THEN round(Dispersao_Global / Media_Global * 100, 1)
          ELSE null END AS CV_Pct,

     // % com nota registrada
     CASE WHEN N_Alunos > 0
          THEN round(toFloat(N_Notas) / N_Alunos * 100, 1)
          ELSE 0 END AS Pct_Com_Nota,

     // % com diário (proxy via alunos que têm SC)
     CASE WHEN N_Alunos > 0
          THEN round(toFloat(N_TurmComDiario_Proxy) / N_Alunos * 100, 1)
          ELSE 0 END AS Pct_Com_Diario,

     // Gaps de equidade
     CASE WHEN Media_BF IS NOT NULL AND Media_NaoBF IS NOT NULL
          THEN round(abs(Media_NaoBF - Media_BF), 2)
          ELSE null END AS Gap_BF,
     CASE WHEN Media_PCD IS NOT NULL AND Media_NaoPCD IS NOT NULL
          THEN round(abs(Media_NaoPCD - Media_PCD), 2)
          ELSE null END AS Gap_PCD

WITH *,
     // Delta frequência vs benchmark municipal
     CASE WHEN Taxa_Ausencia_Pct IS NOT NULL AND Freq_Ref IS NOT NULL
          THEN round(Taxa_Ausencia_Pct - (100.0 - Freq_Ref), 2)
          ELSE null END AS Delta_Freq_Vs_IBGE,

     // ════════════════════════════════════════════════
     // SUB-SCORE PRESENÇA (0–10)
     //   7.0 pontos → taxa de ausência (quanto menor, melhor)
     //   3.0 pontos → % falta crítica
     // ════════════════════════════════════════════════
     CASE WHEN Taxa_Ausencia_Pct IS NOT NULL THEN
       // ausência: 0% → 7 pontos; 20%+ → 0 pontos
       round(CASE WHEN Taxa_Ausencia_Pct <= 0 THEN 7.0
                  WHEN Taxa_Ausencia_Pct >= 20 THEN 0.0
                  ELSE (20.0 - Taxa_Ausencia_Pct) / 20.0 * 7.0 END
       // falta crítica: 0% → 3 pontos; 30%+ → 0 pontos
       + CASE WHEN N_Alunos > 0 AND N_FaltaCritica / toFloat(N_Alunos) * 100 <= 0 THEN 3.0
              WHEN N_Alunos > 0 AND N_FaltaCritica / toFloat(N_Alunos) * 100 >= 30 THEN 0.0
              WHEN N_Alunos > 0 THEN (30.0 - N_FaltaCritica / toFloat(N_Alunos) * 100) / 30.0 * 3.0
              ELSE 3.0 END, 2)
     ELSE 3.5 END AS SubScore_Presenca,   // 3.5 se sem diário = penalidade moderada

     // ════════════════════════════════════════════════
     // SUB-SCORE DESEMPENHO (0–10)
     //   4.0 pontos → média global
     //   4.0 pontos → % abaixo de 5 (invertido)
     //   2.0 pontos → CV% (quanto menor a heterogeneidade, melhor)
     // ════════════════════════════════════════════════
     CASE WHEN Media_Global IS NOT NULL THEN
       round(
         // média: 0→0 pontos, 10→4 pontos
         (Media_Global / 10.0 * 4.0)
         // % abaixo de 5: 0%→4 pts; 80%+→0 pts
         + CASE WHEN N_Notas > 0 THEN
             (CASE WHEN N_Abaixo5 / toFloat(N_Notas) * 100 <= 0 THEN 4.0
                   WHEN N_Abaixo5 / toFloat(N_Notas) * 100 >= 80 THEN 0.0
                   ELSE (80.0 - N_Abaixo5 / toFloat(N_Notas) * 100) / 80.0 * 4.0
              END) ELSE 2.0 END
         // CV%: 0%→2 pts; 60%+→0 pts
         + CASE WHEN CV_Pct IS NOT NULL THEN
             (CASE WHEN CV_Pct <= 0 THEN 2.0
                   WHEN CV_Pct >= 60 THEN 0.0
                   ELSE (60.0 - CV_Pct) / 60.0 * 2.0
              END) ELSE 1.0 END,
       2)
     ELSE 0.0 END AS SubScore_Desempenho,

     // ════════════════════════════════════════════════
     // SUB-SCORE EQUIDADE (0–10)
     //   5.0 pontos → gap BF (quanto menor, melhor)
     //   5.0 pontos → gap PCD
     // ════════════════════════════════════════════════
     round(
       // gap BF: 0→5 pts; 4+ pontos de gap→0 pts
       CASE WHEN Gap_BF IS NOT NULL THEN
         (CASE WHEN Gap_BF <= 0 THEN 5.0
               WHEN Gap_BF >= 4.0 THEN 0.0
               ELSE (4.0 - Gap_BF) / 4.0 * 5.0 END)
       ELSE 2.5 END   // sem BF registrado = neutro
       // gap PCD: 0→5 pts; 4+ pontos→0 pts
       + CASE WHEN Gap_PCD IS NOT NULL THEN
           (CASE WHEN Gap_PCD <= 0 THEN 5.0
                 WHEN Gap_PCD >= 4.0 THEN 0.0
                 ELSE (4.0 - Gap_PCD) / 4.0 * 5.0 END)
         ELSE 2.5 END,
     2) AS SubScore_Equidade,

     // ════════════════════════════════════════════════
     // SUB-SCORE COBERTURA DE DADOS (0–10)
     //   5.0 pontos → % com diário eletrônico
     //   5.0 pontos → % com nota cadastrada
     // Premia escolas que registram bem
     // ════════════════════════════════════════════════
     round(
       (Pct_Com_Diario / 100.0 * 5.0)
       + (Pct_Com_Nota  / 100.0 * 5.0),
     2) AS SubScore_Cobertura

WITH *,
     // SCORE FINAL PONDERADO (0–100)
     // Presença 35% + Desempenho 35% + Equidade 20% + Cobertura 10%
     round(
       (SubScore_Presenca   * 0.35
      + SubScore_Desempenho * 0.35
      + SubScore_Equidade   * 0.20
      + SubScore_Cobertura  * 0.10) * 10,
     1) AS Score_Saude_Escola

// ─────────────────────────────────────────────────────────────────
// RESULTADO FINAL
// ─────────────────────────────────────────────────────────────────
RETURN
  // ── Identificação ────────────────────────────────────────────
  sch.name  AS Escola,
  m.name    AS Municipio,
  st.sigla  AS UF,
  N_Alunos,
  N_Turmas_Total,

  // ── Score Geral ───────────────────────────────────────────────
  Score_Saude_Escola,
  CASE
    WHEN Score_Saude_Escola >= 75 THEN '🟢 Excelente'
    WHEN Score_Saude_Escola >= 55 THEN '🔵 Boa'
    WHEN Score_Saude_Escola >= 35 THEN '🟡 Regular'
    ELSE                               '🔴 Crítica'
  END AS Nivel_Saude,

  // ── Sub-Scores (0–10) ─────────────────────────────────────────
  SubScore_Presenca   AS SubScore_Presenca_0a10,
  SubScore_Desempenho AS SubScore_Desempenho_0a10,
  SubScore_Equidade   AS SubScore_Equidade_0a10,
  SubScore_Cobertura  AS SubScore_Cobertura_0a10,

  // ── Dimensão Presença ─────────────────────────────────────────
  CASE WHEN N_ComFalta = 0 THEN 'Sem Diário'
       ELSE toString(Taxa_Ausencia_Pct) + '%'
  END AS Taxa_Ausencia_Geral,
  round(toFloat(N_FaltaCritica) / N_Alunos * 100, 1) AS Pct_Alunos_Falta_Critica,
  Delta_Freq_Vs_IBGE,
  Fonte_Freq,

  // ── Dimensão Desempenho ───────────────────────────────────────
  Media_Global,
  Dispersao_Global,
  CV_Pct                                              AS CV_Heterogeneidade_Pct,
  round(toFloat(N_Abaixo5) / CASE WHEN N_Notas > 0 THEN N_Notas ELSE 1 END * 100, 1) AS Pct_Abaixo5,
  round(toFloat(N_Acima7)  / CASE WHEN N_Notas > 0 THEN N_Notas ELSE 1 END * 100, 1) AS Pct_Acima7,
  N_Notas,

  // ── Dimensão Equidade ─────────────────────────────────────────
  round(toFloat(N_BolsaFamilia) / N_Alunos * 100, 1) AS Pct_Bolsa_Familia,
  Media_BF,
  Media_NaoBF,
  Gap_BF                                              AS Gap_Nota_BF_vs_NaoBF,
  round(toFloat(N_PCD) / N_Alunos * 100, 1)          AS Pct_PCD,
  Media_PCD,
  Media_NaoPCD,
  Gap_PCD                                             AS Gap_Nota_PCD_vs_NaoPCD,

  // ── Dimensão Cobertura ────────────────────────────────────────
  Pct_Com_Diario                                      AS Pct_Alunos_Com_Diario_Eletronico,
  Pct_Com_Nota                                        AS Pct_Alunos_Com_Nota_Cadastrada,

  // ── Flag de onde melhorar (pior sub-score) ────────────────────
  CASE
    WHEN SubScore_Presenca   = [SubScore_Presenca, SubScore_Desempenho, SubScore_Equidade, SubScore_Cobertura][
           reduce(idx=0, i IN range(1,3) |
             CASE WHEN [SubScore_Presenca, SubScore_Desempenho, SubScore_Equidade, SubScore_Cobertura][i]
                       < [SubScore_Presenca, SubScore_Desempenho, SubScore_Equidade, SubScore_Cobertura][idx]
                  THEN i ELSE idx END)
         ] THEN 'Presença'
    WHEN SubScore_Desempenho <= SubScore_Presenca
     AND SubScore_Desempenho <= SubScore_Equidade
     AND SubScore_Desempenho <= SubScore_Cobertura   THEN 'Desempenho'
    WHEN SubScore_Equidade   <= SubScore_Cobertura   THEN 'Equidade'
    ELSE 'Cobertura de Dados'
  END AS Prioridade_Melhoria,

  // ── Contexto Municipal IBGE ───────────────────────────────────
  round(MUNI_Freq_Liq,          2) AS MUNI_Freq_Liquida_Fund,
  round(MUNI_Atraso_2Anos,      2) AS MUNI_Pct_Atraso_2Anos,
  round(MUNI_Analf_Adulto,      2) AS MUNI_Pct_Analf_Adultos,
  round(MUNI_Expectativa_Estudo,2) AS MUNI_Expectativa_Estudo_18,

  // ── Contexto QEdu Estadual ────────────────────────────────────
  EST_IDEB_AI                      AS EST_IDEB_Anos_Iniciais,
  EST_IDEB_AF                      AS EST_IDEB_Anos_Finais,
  round(EST_Taxa_Abandono,  2)     AS EST_Taxa_Abandono_Oficial,
  round(EST_Taxa_Reprovacao,2)     AS EST_Taxa_Reprovacao_Oficial,
  round(EST_Taxa_Aprovacao, 2)     AS EST_Taxa_Aprovacao_Oficial,
  EST_Fluxo_AI                     AS EST_Fluxo_AI,
  EST_Fluxo_AF                     AS EST_Fluxo_AF,
  round(EST_Distorcao_AI,   1)     AS EST_Distorcao_EF_AI,
  round(EST_Distorcao_AF,   1)     AS EST_Distorcao_EF_AF,
  round(EST_Pct_Fora_Escola * 100, 1) AS EST_Pct_Fora_Escola,
  EST_Aprendizado_AI               AS EST_Nota_Aprendizado_AI,
  EST_Aprendizado_AF               AS EST_Nota_Aprendizado_AF,
  round(EST_LP_Adequado_AI  * 100, 1) AS EST_LP_Adequado_AI_Pct,
  round(EST_Mat_Adequado_AI * 100, 1) AS EST_Mat_Adequado_AI_Pct,
  round(EST_LP_Insuf_AI     * 100, 1) AS EST_LP_Insuficiente_AI_Pct,
  round(EST_Mat_Insuf_AI    * 100, 1) AS EST_Mat_Insuficiente_AI_Pct,

  // ── Contexto PNAD racial e gênero ─────────────────────────────
  round(EST_Atraso_Negro,   2)     AS EST_Atraso_Escolar_Negro,
  round(EST_Atraso_Branco,  2)     AS EST_Atraso_Escolar_Branco,
  round(EST_Analf_Negro,    2)     AS EST_Analf_Adulto_Negro,
  round(EST_Analf_Branco,   2)     AS EST_Analf_Adulto_Branco,
  round(EST_Analf_Homem,    2)     AS EST_Analf_Adulto_Homem,
  round(EST_Analf_Mulher,   2)     AS EST_Analf_Adulto_Mulher

ORDER BY Score_Saude_Escola DESC
LIMIT 200
```

---

## Q_PROXIMIDADE_ALUNOS — Onde Cada Turma Está e O Que Falta Para Melhorar

### Objetivo

Para cada turma × matéria, mostra **onde os alunos estão agora e o que seria necessário para que mais deles passem ou melhorem**. A lógica central é a "distância até o próximo corte":

- Grupo **À Beira** (4.0–4.9): precisa de média 5 → faltam poucos décimos. Intervenção com alto retorno.
- Grupo **Intermediário** (3.0–3.9): falta mais, mas ainda recuperável.
- Grupo **Crítico** (<3.0): precisa de intervenção estrutural, não só reforço.

A **Trajetória** (se `grade_1 < final_mean`) detecta quem melhorou durante o ano — proxy de engajamento. O campo `Potencial_Impacto` indica qual grupo traria maior ganho se fosse recuperado.

### EF2 — Fundamental II (por matéria)

```cypher
// ─────────────────────────────────────────────────────────────────
// ÂNCORA + IBGE (mesmo padrão das outras queries)
// ─────────────────────────────────────────────────────────────────
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund,         null) AS MUNI_Freq_Liq,
     coalesce(m.atl_atraso_2_fund,         null) AS MUNI_Atraso_2Anos,
     coalesce(m.atl_t_analf25m,            null) AS MUNI_Analf_Adulto,
     coalesce(m.atl_expectativa_estudo_18, null) AS MUNI_Expectativa_Estudo,
     coalesce(st.qedu_ideb_af,             null) AS EST_IDEB_AF,
     coalesce(st.qedu_aprendizado_af,      null) AS EST_Aprendizado_AF,
     coalesce(st.qedu_taxa_reprovacao,     null) AS EST_Taxa_Reprovacao,
     coalesce(st.qedu_taxa_abandono,       null) AS EST_Taxa_Abandono,
     coalesce(st.qedu_lp_adequado_af,      null) AS EST_LP_Adequado_AF,
     coalesce(st.qedu_mt_adequado_af,      null) AS EST_Mat_Adequado_AF,
     coalesce(st.qedu_lp_insuficiente_af,  null) AS EST_LP_Insuf_AF,
     coalesce(st.qedu_mt_insuficiente_af,  null) AS EST_Mat_Insuf_AF,
     coalesce(st.qedu_distorcao_ef_af,     null) AS EST_Distorcao_AF,
     coalesce(st.qedu_distorcao_ef6,       null) AS EST_Distorcao_6,
     coalesce(st.qedu_distorcao_ef7,       null) AS EST_Distorcao_7,
     coalesce(st.qedu_distorcao_ef8,       null) AS EST_Distorcao_8,
     coalesce(st.qedu_distorcao_ef9,       null) AS EST_Distorcao_9,
     coalesce(st.qedu_pct_fora_escola,     null) AS EST_Pct_Fora_Escola,
     coalesce(st.negro_pnad_t_atraso_fund, null) AS EST_Atraso_Negro,
     coalesce(st.homem_pnad_t_analf25m,    null) AS EST_Analf_Homem,
     coalesce(st.mulher_pnad_t_analf25m,   null) AS EST_Analf_Mulher

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS UF_Media_Freq
}

WITH sch, m, st,
     MUNI_Freq_Liq, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     coalesce(MUNI_Freq_Liq, UF_Media_Freq) AS Freq_Ref,
     EST_IDEB_AF, EST_Aprendizado_AF, EST_Taxa_Reprovacao, EST_Taxa_Abandono,
     EST_LP_Adequado_AF, EST_Mat_Adequado_AF, EST_LP_Insuf_AF, EST_Mat_Insuf_AF,
     EST_Distorcao_AF, EST_Distorcao_6, EST_Distorcao_7, EST_Distorcao_8, EST_Distorcao_9,
     EST_Pct_Fora_Escola, EST_Atraso_Negro, EST_Analf_Homem, EST_Analf_Mulher

// ─────────────────────────────────────────────────────────────────
// PASSO 1: coleta alunos EF2 por turma
// ─────────────────────────────────────────────────────────────────
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
  RETURN cr.name       AS Turma,
         cr.grade_level AS Grade,
         collect(DISTINCT stu) AS ListaTurma
}

WITH sch, m, st, Turma, Grade, ListaTurma,
     Freq_Ref, MUNI_Freq_Liq, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     EST_IDEB_AF, EST_Aprendizado_AF, EST_Taxa_Reprovacao, EST_Taxa_Abandono,
     EST_LP_Adequado_AF, EST_Mat_Adequado_AF, EST_LP_Insuf_AF, EST_Mat_Insuf_AF,
     EST_Distorcao_AF, EST_Distorcao_6, EST_Distorcao_7, EST_Distorcao_8, EST_Distorcao_9,
     EST_Pct_Fora_Escola, EST_Atraso_Negro, EST_Analf_Homem, EST_Analf_Mulher

WHERE size(ListaTurma) >= 10

// ─────────────────────────────────────────────────────────────────
// PASSO 2: notas por matéria + grupos de proximidade
// Cada aluno é classificado em um dos 4 grupos por nota
// grade_1 = nota inicial / final_mean = nota final → trajetória
// ─────────────────────────────────────────────────────────────────
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

  WITH sd.discipline_name AS Materia,
       // Nota final normalizada
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS NotaFinal,
       // Nota inicial normalizada (para trajetória)
       CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
            THEN sd.grade_1 / 10.0
            WHEN sd.grade_1 IS NOT NULL
            THEN sd.grade_1
            ELSE null
       END AS NotaInicial

  WHERE NotaFinal IS NOT NULL

  RETURN Materia,
         count(NotaFinal)                             AS N_Total,
         round(avg(NotaFinal), 2)                     AS Media_Turma,
         round(stDev(NotaFinal), 2)                   AS Dispersao,
         round(max(NotaFinal), 2)                     AS Nota_Max,
         round(min(NotaFinal), 2)                     AS Nota_Min,

         // ── GRUPOS DE PROXIMIDADE ──────────────────────────────────
         // Aprovado: já passou — baseline
         count(CASE WHEN NotaFinal >= 5.0 THEN 1 END)              AS N_Aprovado,
         // À beira: 4.0–4.9 — alto retorno de intervenção
         count(CASE WHEN NotaFinal >= 4.0 AND NotaFinal < 5.0 THEN 1 END) AS N_Beira,
         // Intermediário: 3.0–3.9 — recuperável com suporte
         count(CASE WHEN NotaFinal >= 3.0 AND NotaFinal < 4.0 THEN 1 END) AS N_Intermediario,
         // Crítico: <3.0 — precisa intervenção estrutural
         count(CASE WHEN NotaFinal < 3.0 THEN 1 END)               AS N_Critico,

         // ── DISTÂNCIA MÉDIA ATÉ O CORTE (só para os grupos abaixo) ──
         // Quanto falta em média para o grupo "À Beira" chegar em 5
         round(avg(CASE WHEN NotaFinal >= 4.0 AND NotaFinal < 5.0
                        THEN 5.0 - NotaFinal END), 2)               AS Distancia_Media_Beira,
         // Quanto falta para o intermediário chegar em 4 (próximo patamar)
         round(avg(CASE WHEN NotaFinal >= 3.0 AND NotaFinal < 4.0
                        THEN 4.0 - NotaFinal END), 2)               AS Distancia_Media_Intermediario,
         // Quanto falta para o crítico chegar em 3
         round(avg(CASE WHEN NotaFinal < 3.0
                        THEN 3.0 - NotaFinal END), 2)               AS Distancia_Media_Critico,

         // ── TRAJETÓRIA ────────────────────────────────────────────
         // % que melhorou: final_mean > grade_1
         count(CASE WHEN NotaInicial IS NOT NULL AND NotaFinal > NotaInicial
                    THEN 1 END)                                      AS N_Melhorou,
         // % que piorou
         count(CASE WHEN NotaInicial IS NOT NULL AND NotaFinal < NotaInicial
                    THEN 1 END)                                      AS N_Piorou,
         // Ganho médio de quem melhorou
         round(avg(CASE WHEN NotaInicial IS NOT NULL AND NotaFinal > NotaInicial
                        THEN NotaFinal - NotaInicial END), 2)        AS Ganho_Medio_Melhora,
         // Perda média de quem piorou
         round(avg(CASE WHEN NotaInicial IS NOT NULL AND NotaFinal < NotaInicial
                        THEN NotaInicial - NotaFinal END), 2)        AS Perda_Media_Piora,
         // Quantos têm nota inicial registrada (cobertura de trajetória)
         count(CASE WHEN NotaInicial IS NOT NULL THEN 1 END)         AS N_Com_Nota_Inicial
}

// ─────────────────────────────────────────────────────────────────
// PASSO 3: faltas da turma (contexto de engajamento)
// ─────────────────────────────────────────────────────────────────
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))           AS TotalFaltas,
    sum(coalesce(sc.scheduled_student_class_days, 200)) AS TotalDias,
    count(DISTINCT CASE WHEN sc IS NOT NULL
                         AND sc.scheduled_student_class_days > 0
                         AND toFloat(sc.total_faults_per_day) /
                             sc.scheduled_student_class_days > 0.10  THEN stu END) AS N_FaltaCritica
}

WITH sch, m, st, Turma, Grade, ListaTurma, Materia,
     N_Total, Media_Turma, Dispersao, Nota_Max, Nota_Min,
     N_Aprovado, N_Beira, N_Intermediario, N_Critico,
     Distancia_Media_Beira, Distancia_Media_Intermediario, Distancia_Media_Critico,
     N_Melhorou, N_Piorou, Ganho_Medio_Melhora, Perda_Media_Piora, N_Com_Nota_Inicial,
     TotalFaltas, TotalDias, N_FaltaCritica,
     Freq_Ref, MUNI_Freq_Liq, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     EST_IDEB_AF, EST_Aprendizado_AF, EST_Taxa_Reprovacao, EST_Taxa_Abandono,
     EST_LP_Adequado_AF, EST_Mat_Adequado_AF, EST_LP_Insuf_AF, EST_Mat_Insuf_AF,
     EST_Distorcao_AF, EST_Distorcao_6, EST_Distorcao_7, EST_Distorcao_8, EST_Distorcao_9,
     EST_Pct_Fora_Escola, EST_Atraso_Negro, EST_Analf_Homem, EST_Analf_Mulher,

     // Perfil social da turma
     size([s IN ListaTurma WHERE coalesce(s.bolsa_familia, false) = true])           AS N_BF,
     size([s IN ListaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS N_PCD

WHERE Materia IS NOT NULL AND N_Total >= 5

WITH *,
     size(ListaTurma) AS N_Alunos,
     // Taxa ausência da turma
     CASE WHEN TotalDias > 0
          THEN round(toFloat(TotalFaltas) / TotalDias * 100, 2) ELSE null
     END AS Taxa_Ausencia_Pct,
     // Distorção específica do ano
     CASE Grade
          WHEN 'NO 6* ANO' THEN EST_Distorcao_6
          WHEN 'NO 7* ANO' THEN EST_Distorcao_7
          WHEN 'NO 8* ANO' THEN EST_Distorcao_8
          WHEN 'NO 9* ANO' THEN EST_Distorcao_9
          ELSE EST_Distorcao_AF
     END AS EST_Distorcao_Grade

// ─────────────────────────────────────────────────────────────────
// RESULTADO FINAL
// ─────────────────────────────────────────────────────────────────
RETURN
  // ── Identificação ────────────────────────────────────────────
  sch.name AS Escola,
  m.name   AS Municipio,
  st.sigla AS UF,
  Turma,
  Grade    AS Ano_Escolar,
  Materia,
  N_Alunos,
  N_Total  AS N_Alunos_Com_Nota,

  // ── Média e Distribuição ─────────────────────────────────────
  Media_Turma,
  Dispersao,
  Nota_Min,
  Nota_Max,
  round(Nota_Max - Nota_Min, 2) AS Amplitude_Notas,

  // ── Grupos de Proximidade (quem está onde) ────────────────────
  N_Aprovado,
  round(toFloat(N_Aprovado)     / N_Total * 100, 1) AS Pct_Aprovado,
  N_Beira,
  round(toFloat(N_Beira)        / N_Total * 100, 1) AS Pct_Beira_Aprovacao,
  N_Intermediario,
  round(toFloat(N_Intermediario)/ N_Total * 100, 1) AS Pct_Intermediario,
  N_Critico,
  round(toFloat(N_Critico)      / N_Total * 100, 1) AS Pct_Critico,

  // ── Distância Até o Próximo Corte ────────────────────────────
  // Quanto falta, em média, para cada grupo atingir o próximo nível
  Distancia_Media_Beira          AS Faltam_Pontos_Beira_Para_Passar,
  Distancia_Media_Intermediario  AS Faltam_Pontos_Intermediario_Para_Beira,
  Distancia_Media_Critico        AS Faltam_Pontos_Critico_Para_Intermediario,

  // ── Trajetória ────────────────────────────────────────────────
  N_Com_Nota_Inicial,
  N_Melhorou,
  N_Piorou,
  round(toFloat(N_Melhorou) / CASE WHEN N_Com_Nota_Inicial > 0 THEN N_Com_Nota_Inicial ELSE 1 END * 100, 1) AS Pct_Melhorou,
  round(toFloat(N_Piorou)   / CASE WHEN N_Com_Nota_Inicial > 0 THEN N_Com_Nota_Inicial ELSE 1 END * 100, 1) AS Pct_Piorou,
  Ganho_Medio_Melhora,
  Perda_Media_Piora,

  // ── Frequência (contexto de engajamento) ─────────────────────
  CASE WHEN N_FaltaCritica = 0 AND TotalFaltas = 0 THEN 'Sem Diário'
       ELSE toString(Taxa_Ausencia_Pct) + '%'
  END AS Taxa_Ausencia_Turma,
  round(toFloat(N_FaltaCritica) / N_Alunos * 100, 1) AS Pct_Falta_Critica_10pct,

  // ── Perfil Social ─────────────────────────────────────────────
  round(toFloat(N_BF)  / N_Alunos * 100, 1) AS Pct_Bolsa_Familia,
  round(toFloat(N_PCD) / N_Alunos * 100, 1) AS Pct_PCD,

  // ── Indicador de Potencial de Impacto ────────────────────────
  // Qual grupo, se recuperado, traria mais aprovados?
  CASE
    WHEN N_Beira >= N_Intermediario AND N_Beira >= N_Critico
      THEN '🎯 Focar no grupo À Beira — ' + toString(N_Beira) + ' alunos a ' +
           toString(Distancia_Media_Beira) + ' pontos da aprovação'
    WHEN N_Intermediario >= N_Critico
      THEN '📈 Focar no Intermediário — ' + toString(N_Intermediario) + ' alunos a recuperar'
    ELSE '🚨 Focar no Crítico — ' + toString(N_Critico) + ' alunos em situação grave'
  END AS Potencial_Impacto,

  // ── Sinal de Tendência ────────────────────────────────────────
  CASE
    WHEN N_Com_Nota_Inicial >= 5 AND N_Melhorou > N_Piorou THEN '📈 Turma em melhora'
    WHEN N_Com_Nota_Inicial >= 5 AND N_Piorou > N_Melhorou THEN '📉 Turma em queda'
    WHEN N_Com_Nota_Inicial >= 5                            THEN '➡️  Turma estável'
    ELSE '⚠️  Sem dados de trajetória'
  END AS Tendencia_Turma,

  // ── Contexto Municipal IBGE ───────────────────────────────────
  round(MUNI_Freq_Liq,           2) AS MUNI_Freq_Liquida_Fund,
  round(MUNI_Atraso_2Anos,       2) AS MUNI_Pct_Atraso_2Anos,
  round(MUNI_Analf_Adulto,       2) AS MUNI_Pct_Analf_Adultos,
  round(MUNI_Expectativa_Estudo, 2) AS MUNI_Expectativa_Estudo_18,

  // ── Contexto QEdu Estadual ────────────────────────────────────
  EST_IDEB_AF                       AS EST_IDEB_Anos_Finais,
  EST_Aprendizado_AF                AS EST_Nota_Aprendizado_AF,
  round(EST_Taxa_Reprovacao, 2)     AS EST_Taxa_Reprovacao,
  round(EST_Taxa_Abandono,   2)     AS EST_Taxa_Abandono_Oficial,
  round(EST_Pct_Fora_Escola * 100,1) AS EST_Pct_Fora_Escola,
  round(EST_Distorcao_Grade, 1)     AS EST_Distorcao_Ano_Especifico,
  round(EST_LP_Adequado_AF  * 100,1) AS EST_LP_Adequado_AF_Pct,
  round(EST_Mat_Adequado_AF * 100,1) AS EST_Mat_Adequado_AF_Pct,
  round(EST_LP_Insuf_AF     * 100,1) AS EST_LP_Insuficiente_AF_Pct,
  round(EST_Mat_Insuf_AF    * 100,1) AS EST_Mat_Insuficiente_AF_Pct,

  // ── Contexto PNAD ─────────────────────────────────────────────
  round(EST_Atraso_Negro, 2)        AS EST_Atraso_Escolar_Negro_Estado,
  round(EST_Analf_Homem,  2)        AS EST_Analf_Adulto_Homem_Estado,
  round(EST_Analf_Mulher, 2)        AS EST_Analf_Adulto_Mulher_Estado

ORDER BY
  // Prioriza turmas com maior gap de melhora possível:
  // muitos "à beira" + distância pequena = alto retorno
  round(toFloat(N_Beira) * (5.0 - coalesce(Distancia_Media_Beira, 0.5)) * 2
      + toFloat(N_Intermediario), 1) DESC,
  Media_Turma ASC

LIMIT 300
```

---

## Legenda das Colunas — Q_PROXIMIDADE_ALUNOS

### Grupos de Proximidade
| Grupo | Faixa de nota | Interpretação |
|---|---|---|
| **Aprovado** | ≥ 5.0 | Passou. Baseline — quanto da turma já está aprovada? |
| **À Beira** | 4.0–4.9 | Alto potencial de intervenção — poucos décimos faltam |
| **Intermediário** | 3.0–3.9 | Recuperável com suporte contínuo |
| **Crítico** | < 3.0 | Precisa de intervenção estrutural, não só reforço |

### Distâncias
| Coluna | O que mede |
|---|---|
| `Faltam_Pontos_Beira_Para_Passar` | Quanto falta, em média, para o grupo "À Beira" atingir 5.0 |
| `Faltam_Pontos_Intermediario_Para_Beira` | Quanto falta para o grupo Intermediário subir para ≥4.0 |
| `Faltam_Pontos_Critico_Para_Intermediario` | Quanto falta para o grupo Crítico subir para ≥3.0 |

### Trajetória
| Coluna | O que mede |
|---|---|
| `Pct_Melhorou` | % que teve `final_mean > grade_1` — proxy de engajamento |
| `Pct_Piorou` | % que regrediu — sinal de alerta |
| `Ganho_Medio_Melhora` | Quantos pontos em média ganharam quem melhorou |
| `Tendencia_Turma` | 📈 Melhora / 📉 Queda / ➡️ Estável / ⚠️ Sem dados |

### Priorização
| Coluna | O que mede |
|---|---|
| `Potencial_Impacto` | Qual grupo focar para máximo retorno de aprovação |
| `Tendencia_Turma` | Se a turma como um todo está evoluindo ou regredindo |

O ordenamento padrão prioriza turmas com **muitos alunos "À Beira" e pequena distância até o corte** — esse é o grupo com maior ROI de intervenção: poucos décimos faltam para muitos alunos aprovarem.
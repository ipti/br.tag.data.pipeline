# Q_RISCO_EVASAO — Turmas com Maior Risco de Evasão (Fundamental II, por Matéria)

**Objetivo:** Identificar quais turmas × matérias têm maior probabilidade de perda de frequência dos alunos, combinando sinais internos da rede (faltas, notas, perfil social) com o máximo de contexto IBGE/QEdu disponível no grafo.

---

## Arquitetura

```
School → Municipality → State          (carrega todos os IBGEs de uma vez, antes das CALLs)
CALL(sch)   → filtra EF2 por turma, collect(DISTINCT stu) por turma
CALL(lista) → dimension faltas                   — O(N)
CALL(lista) → dimension notas × matéria          — O(N × K), K = notas por aluno
CALL(lista) → dimension perfil social (BF, PCD)  — O(N) via list comprehension
```

O `Score_Risco_Evasao` (0–100) é um índice composto:
- **40%** → taxa de ausência atual da turma
- **35%** → % de alunos com nota < 5 na matéria  
- **25%** → nota média invertida (quanto menor a média, maior o risco)

Cada componente é normalizado 0–10 antes da ponderação, então o score final é escalado para 0–100. Isso permite comparação direta entre turmas de anos e matérias diferentes.

O campo `Delta_Freq_Vs_IBGE` indica se a turma está **acima** (+) ou abaixo (–) da taxa de ausência esperada pelo contexto do município — positivo = pior que o esperado.

---

## Query

```cypher
// ─────────────────────────────────────────────
// ÂNCORA: School com toda a cadeia geográfica
// Carrega TODOS os IBGEs aqui — uma vez por escola, não por aluno
// ─────────────────────────────────────────────
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// ── Contexto Municipal ──────────────────────────────────────────────────────
WITH sch, m, st,
     // Frequência líquida do município (benchmark de presença)
     coalesce(m.atl_freq_liq_fund,        null) AS MUNI_Freq_Liq_Fund,
     // % alunos com 2+ anos de atraso escolar no município
     coalesce(m.atl_atraso_2_fund,        null) AS MUNI_Atraso_2Anos,
     // Analfabetismo adulto: proxy de suporte familiar ao estudo
     coalesce(m.atl_t_analf25m,           null) AS MUNI_Analf_Adulto,
     // Expectativa de anos de estudo ao chegar nos 18: aspiraçao educacional local
     coalesce(m.atl_expectativa_estudo_18, null) AS MUNI_Expectativa_Estudo

// ── Fallback: se município não tem atl_freq_liq_fund, usa média da UF ───────
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS UF_Media_Freq_Liq
}

// ── Contexto Estadual ────────────────────────────────────────────────────────
WITH sch, m, st,
     MUNI_Freq_Liq_Fund, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     coalesce(MUNI_Freq_Liq_Fund, UF_Media_Freq_Liq) AS Freq_Ref,
     CASE WHEN MUNI_Freq_Liq_Fund IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_Freq,

     // QEdu anos finais — qualidade e fluxo do sistema estadual
     coalesce(st.qedu_ideb_af,            null) AS EST_IDEB_AF,
     coalesce(st.qedu_aprendizado_af,     null) AS EST_Nota_Aprendizado_AF,
     coalesce(st.qedu_taxa_abandono,      null) AS EST_Taxa_Abandono_Oficial,
     coalesce(st.qedu_taxa_reprovacao,    null) AS EST_Taxa_Reprovacao,
     coalesce(st.qedu_fluxo_af,          null) AS EST_Fluxo_AF,          // 0-1: quanto menor, pior retenção
     coalesce(st.qedu_distorcao_ef_af,   null) AS EST_Distorcao_EF_AF,   // distorção geral EF anos finais
     coalesce(st.qedu_pct_fora_escola,   null) AS EST_Pct_Fora_Escola,

     // Distorção por ano específico — usado depois para combinar com grade_level da turma
     coalesce(st.qedu_distorcao_ef6,     null) AS EST_Distorcao_6Ano,
     coalesce(st.qedu_distorcao_ef7,     null) AS EST_Distorcao_7Ano,
     coalesce(st.qedu_distorcao_ef8,     null) AS EST_Distorcao_8Ano,
     coalesce(st.qedu_distorcao_ef9,     null) AS EST_Distorcao_9Ano,

     // Proficiência: % com nível insuficiente → se alto, estado já é frágil
     coalesce(st.qedu_lp_insuficiente_af, null) AS EST_LP_Insuficiente_Pct,
     coalesce(st.qedu_mt_insuficiente_af, null) AS EST_Mat_Insuficiente_Pct,
     coalesce(st.qedu_lp_adequado_af,    null) AS EST_LP_Adequado_Pct,
     coalesce(st.qedu_mt_adequado_af,    null) AS EST_Mat_Adequado_Pct,

     // PNAD racial: atraso escolar por raça — equity context
     coalesce(st.negro_pnad_t_atraso_fund,  null) AS EST_Atraso_Negro,
     coalesce(st.branco_pnad_t_atraso_fund, null) AS EST_Atraso_Branco,

     // PNAD gênero: analfabetismo adulto por sexo
     coalesce(st.homem_pnad_t_analf25m,  null) AS EST_Analf_Homem,
     coalesce(st.mulher_pnad_t_analf25m, null) AS EST_Analf_Mulher

// ─────────────────────────────────────────────
// PASSO 1: coleta alunos EF2 por turma
// EF2 = anos 6-9 do Fundamental — cada turma = unidade de análise
// ─────────────────────────────────────────────
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
  RETURN cr.name       AS Turma,
         cr.grade_level AS Grade,
         collect(DISTINCT stu) AS ListaTurma
}

WITH sch, m, st,
     MUNI_Freq_Liq_Fund, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     Freq_Ref, Fonte_Freq,
     EST_IDEB_AF, EST_Nota_Aprendizado_AF, EST_Taxa_Abandono_Oficial,
     EST_Taxa_Reprovacao, EST_Fluxo_AF, EST_Distorcao_EF_AF, EST_Pct_Fora_Escola,
     EST_Distorcao_6Ano, EST_Distorcao_7Ano, EST_Distorcao_8Ano, EST_Distorcao_9Ano,
     EST_LP_Insuficiente_Pct, EST_Mat_Insuficiente_Pct,
     EST_LP_Adequado_Pct, EST_Mat_Adequado_Pct,
     EST_Atraso_Negro, EST_Atraso_Branco,
     EST_Analf_Homem, EST_Analf_Mulher,
     Turma, Grade, ListaTurma

WHERE size(ListaTurma) >= 10  // turmas com pouquíssimos alunos não são representativas

// ─────────────────────────────────────────────
// PASSO 2: dimensão FALTAS (isolada)
// ─────────────────────────────────────────────
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    // Total de faltas da turma
    sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas,
    // Total de dias previstos (base para % de ausência)
    sum(coalesce(sc.scheduled_student_class_days, 200)) AS TotalDias,
    // Quantos alunos têm alguma falta registrada (proxy de cobertura do diário)
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS N_ComFalta,
    // Alunos em falta crítica: >10% dos dias previstos ausentes
    count(DISTINCT CASE
          WHEN sc IS NOT NULL
           AND sc.scheduled_student_class_days > 0
           AND toFloat(sc.total_faults_per_day) / sc.scheduled_student_class_days > 0.10
          THEN stu END) AS N_FaltaCritica
}

// ─────────────────────────────────────────────
// PASSO 3: dimensão NOTAS por matéria (isolada de faltas)
// EF2 → cada matéria é um registro separado
// ─────────────────────────────────────────────
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH sd.discipline_name AS Materia,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN Materia,
         count(Nota)             AS N_Notas,
         round(avg(Nota), 2)     AS Media_Nota,
         round(stDev(Nota), 2)   AS Dispersao_Nota,
         // % com nota abaixo de 5 — risco de reprovação → desengajamento → evasão
         round(
           toFloat(count(CASE WHEN Nota < 5.0 THEN 1 END)) / count(Nota) * 100,
           1
         ) AS Pct_Abaixo5,
         // % com nota abaixo de 3 — risco crítico
         round(
           toFloat(count(CASE WHEN Nota < 3.0 THEN 1 END)) / count(Nota) * 100,
           1
         ) AS Pct_Abaixo3
}

// ─────────────────────────────────────────────
// PASSO 4: perfil social da turma (via list comprehension — sem UNWIND extra)
// ─────────────────────────────────────────────
WITH sch, m, st, Turma, Grade, ListaTurma, Materia,
     TotalFaltas, TotalDias, N_ComFalta, N_FaltaCritica,
     N_Notas, Media_Nota, Dispersao_Nota, Pct_Abaixo5, Pct_Abaixo3,
     MUNI_Freq_Liq_Fund, MUNI_Atraso_2Anos, MUNI_Analf_Adulto, MUNI_Expectativa_Estudo,
     Freq_Ref, Fonte_Freq,
     EST_IDEB_AF, EST_Nota_Aprendizado_AF, EST_Taxa_Abandono_Oficial,
     EST_Taxa_Reprovacao, EST_Fluxo_AF, EST_Distorcao_EF_AF, EST_Pct_Fora_Escola,
     EST_Distorcao_6Ano, EST_Distorcao_7Ano, EST_Distorcao_8Ano, EST_Distorcao_9Ano,
     EST_LP_Insuficiente_Pct, EST_Mat_Insuficiente_Pct,
     EST_LP_Adequado_Pct, EST_Mat_Adequado_Pct,
     EST_Atraso_Negro, EST_Atraso_Branco, EST_Analf_Homem, EST_Analf_Mulher,

     // Perfil social via list comprehension (O(N) sem abrir novos MATCH)
     size([s IN ListaTurma WHERE coalesce(s.bolsa_familia, false) = true]) AS N_BolsaFamilia,
     size([s IN ListaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS N_PCD

WHERE Materia IS NOT NULL AND N_Notas >= 5

// ─────────────────────────────────────────────
// CÁLCULO DAS MÉTRICAS DERIVADAS
// ─────────────────────────────────────────────
WITH *,
     size(ListaTurma) AS N_Alunos,

     // Taxa de ausência real da turma (%)
     CASE WHEN TotalDias > 0
          THEN round(toFloat(TotalFaltas) / TotalDias * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Pct,

     // Distorção específica do ano da turma (busca o campo correto por grade_level)
     CASE Grade
          WHEN 'NO 6* ANO' THEN EST_Distorcao_6Ano
          WHEN 'NO 7* ANO' THEN EST_Distorcao_7Ano
          WHEN 'NO 8* ANO' THEN EST_Distorcao_8Ano
          WHEN 'NO 9* ANO' THEN EST_Distorcao_9Ano
          ELSE EST_Distorcao_EF_AF   // fallback para séries antigas
     END AS EST_Distorcao_Grade_Especifica

WITH *,
     // Delta: turma acima/abaixo do benchmark municipal de ausência
     // Positivo = turma perde mais dias que o esperado pelo contexto
     CASE WHEN Taxa_Ausencia_Pct IS NOT NULL AND Freq_Ref IS NOT NULL
          THEN round(Taxa_Ausencia_Pct - (100.0 - Freq_Ref), 2)
          ELSE null
     END AS Delta_Vs_Benchmark_Freq,

     // ── SCORE DE RISCO DE EVASÃO (0–100) ────────────────────────────────
     // Componente 1 (40%): taxa de ausência normalizada (0–10)
     //   assume que 25%+ de ausência = máximo risco
     CASE WHEN Taxa_Ausencia_Pct IS NOT NULL
          THEN round(
            (CASE WHEN Taxa_Ausencia_Pct >= 25.0 THEN 10.0
                  ELSE Taxa_Ausencia_Pct / 25.0 * 10.0
             END) * 0.40, 3)
          ELSE 0.0
     END AS Score_Ausencia,

     // Componente 2 (35%): % notas abaixo de 5 normalizado (0–10)
     //   assume que 60%+ abaixo de 5 = máximo risco
     round(
       (CASE WHEN Pct_Abaixo5 >= 60.0 THEN 10.0
             ELSE Pct_Abaixo5 / 60.0 * 10.0
        END) * 0.35, 3) AS Score_Nota_Critica,

     // Componente 3 (25%): média invertida normalizada (0–10)
     //   média 0 = risco máximo, média 10 = risco zero
     round(
       (CASE WHEN Media_Nota IS NOT NULL
             THEN (10.0 - Media_Nota) / 10.0 * 10.0
             ELSE 5.0   // sem nota = risco moderado por default
        END) * 0.25, 3) AS Score_Media_Inv

WITH *,
     round((Score_Ausencia + Score_Nota_Critica + Score_Media_Inv) * 10, 1) AS Score_Risco_Evasao

// ─────────────────────────────────────────────
// RESULTADO FINAL
// ─────────────────────────────────────────────
RETURN
  // ── Identificação ────────────────────────────────────────
  sch.name   AS Escola,
  m.name     AS Municipio,
  st.sigla   AS UF,
  Turma,
  Grade      AS Ano_Escolar,
  Materia,
  N_Alunos,

  // ── Score Composto ────────────────────────────────────────
  Score_Risco_Evasao,                          // 0–100, quanto maior, maior o risco
  CASE
    WHEN Score_Risco_Evasao >= 70 THEN '🔴 Crítico'
    WHEN Score_Risco_Evasao >= 45 THEN '🟡 Alerta'
    WHEN Score_Risco_Evasao >= 20 THEN '🟢 Moderado'
    ELSE                               '⚪ Baixo'
  END AS Nivel_Risco,

  // ── Sinais Internos de Evasão ────────────────────────────
  CASE WHEN N_ComFalta = 0 THEN 'Sem Diário Eletrônico'
       ELSE toString(Taxa_Ausencia_Pct) + '%'
  END AS Taxa_Ausencia_Turma,
  round(toFloat(N_ComFalta) / N_Alunos * 100, 1) AS Pct_Alunos_Com_Falta,
  round(toFloat(N_FaltaCritica) / N_Alunos * 100, 1) AS Pct_Alunos_Falta_Critica_10pct,
  N_Notas,
  Media_Nota,
  Dispersao_Nota,
  Pct_Abaixo5 AS Pct_Nota_Abaixo5,
  Pct_Abaixo3 AS Pct_Nota_Abaixo3,

  // ── Perfil Social da Turma ───────────────────────────────
  round(toFloat(N_BolsaFamilia) / N_Alunos * 100, 1) AS Pct_Bolsa_Familia,
  round(toFloat(N_PCD)          / N_Alunos * 100, 1) AS Pct_PCD,

  // ── Delta vs Benchmark ───────────────────────────────────
  Delta_Vs_Benchmark_Freq,
  Fonte_Freq,

  // ── Contexto Municipal (IBGE Atlas) ─────────────────────
  round(MUNI_Freq_Liq_Fund,        2) AS MUNI_Freq_Liquida_Fund,     // % em idade correta frequentando
  round(MUNI_Atraso_2Anos,         2) AS MUNI_Pct_Atraso_2Anos,      // % atrasados no município
  round(MUNI_Analf_Adulto,         2) AS MUNI_Pct_Analf_Adultos,     // proxy vulnerabilidade familiar
  round(MUNI_Expectativa_Estudo,   2) AS MUNI_Expectativa_Estudo_18, // aspiração educacional local

  // ── Contexto Estadual — Qualidade e Fluxo (QEdu) ────────
  EST_IDEB_AF                         AS EST_IDEB_Anos_Finais,        // IDEB do estado para EF-AF
  EST_Nota_Aprendizado_AF             AS EST_Nota_Aprendizado,        // nota média estadual
  round(EST_Taxa_Abandono_Oficial, 2) AS EST_Taxa_Abandono_Oficial,   // % abandono oficial
  round(EST_Taxa_Reprovacao,       2) AS EST_Taxa_Reprovacao,         // % reprovação oficial
  EST_Fluxo_AF                        AS EST_Fluxo_Escolar_AF,        // 0=retenção total, 1=fluxo perfeito
  round(EST_Pct_Fora_Escola * 100, 1) AS EST_Pct_Fora_Escola,        // % crianças fora da escola

  // ── Distorção Idade-Série (QEdu) ────────────────────────
  round(EST_Distorcao_Grade_Especifica, 1) AS EST_Distorcao_Ano_Especifico, // distorção do ANO da turma
  round(EST_Distorcao_EF_AF,        1) AS EST_Distorcao_EF_AF_Geral,  // distorção geral EF anos finais

  // ── Proficiência Estadual (QEdu) ─────────────────────────
  round(EST_LP_Insuficiente_Pct * 100, 1) AS EST_LP_Insuficiente_Pct, // % insuficiente em LP
  round(EST_Mat_Insuficiente_Pct * 100,1) AS EST_Mat_Insuficiente_Pct,// % insuficiente em Mat
  round(EST_LP_Adequado_Pct * 100,    1) AS EST_LP_Adequado_Pct,      // % adequado em LP
  round(EST_Mat_Adequado_Pct * 100,   1) AS EST_Mat_Adequado_Pct,     // % adequado em Mat

  // ── Equity Context (PNAD racial) ─────────────────────────
  round(EST_Atraso_Negro,  2) AS EST_Pct_Atraso_Escolar_Negro_Estado,
  round(EST_Atraso_Branco, 2) AS EST_Pct_Atraso_Escolar_Branco_Estado,

  // ── Equity Context (PNAD gênero) ─────────────────────────
  round(EST_Analf_Homem,   2) AS EST_Pct_Analf_Adulto_Homem_Estado,
  round(EST_Analf_Mulher,  2) AS EST_Pct_Analf_Adulto_Mulher_Estado,

  // ── Flags de qualidade de dado ───────────────────────────
  CASE WHEN N_ComFalta = 0  THEN 0 ELSE 1 END AS Flag_Tem_Diario_Eletronico,
  CASE WHEN N_Notas   = 0  THEN 0 ELSE 1 END AS Flag_Tem_Notas_Cadastradas

ORDER BY Score_Risco_Evasao DESC,
         Pct_Alunos_Falta_Critica_10pct DESC,
         Pct_Nota_Abaixo5 DESC

LIMIT 200
```

---

## Legenda das Colunas

### Score e Classificação
| Coluna | O que mede |
|--------|-----------|
| `Score_Risco_Evasao` | 0–100. Composto: 40% ausência + 35% notas críticas + 25% média baixa |
| `Nivel_Risco` | 🔴 Crítico ≥70 / 🟡 Alerta ≥45 / 🟢 Moderado ≥20 / ⚪ Baixo |

### Sinais Internos
| Coluna | O que mede |
|--------|-----------|
| `Taxa_Ausencia_Turma` | % faltas / dias previstos da turma |
| `Pct_Alunos_Com_Falta` | % de alunos com ao menos 1 falta registrada |
| `Pct_Alunos_Falta_Critica_10pct` | % de alunos que já perderam >10% dos dias |
| `Pct_Nota_Abaixo5` | % com nota média < 5 — risco de reprovação e desengajamento |
| `Pct_Nota_Abaixo3` | % em situação crítica — risco imediato de abandono |
| `Pct_Bolsa_Familia` | % beneficiários BF — proxy vulnerabilidade socioeconômica |

### Contexto IBGE Municipal
| Coluna | Fonte | O que mede |
|--------|-------|-----------|
| `MUNI_Freq_Liquida_Fund` | Atlas IBGE | % crianças em idade correta frequentando o fundamental no município |
| `MUNI_Pct_Atraso_2Anos` | Atlas IBGE | % com 2+ anos de atraso — estrutural |
| `MUNI_Pct_Analf_Adultos` | Atlas IBGE | % analfabetismo adulto — suporte familiar |
| `MUNI_Expectativa_Estudo_18` | Atlas IBGE | Anos esperados de estudo — aspiração educacional local |
| `Delta_Vs_Benchmark_Freq` | Calculado | Turma acima (+) ou abaixo (–) da ausência esperada pelo município |

### Contexto QEdu Estadual
| Coluna | Fonte | O que mede |
|--------|-------|-----------|
| `EST_IDEB_Anos_Finais` | QEdu | IDEB do estado para EF anos finais |
| `EST_Taxa_Abandono_Oficial` | QEdu | Taxa oficial de abandono escolar |
| `EST_Taxa_Reprovacao` | QEdu | Taxa oficial de reprovação |
| `EST_Fluxo_Escolar_AF` | QEdu | Fluxo (0=total retenção, 1=fluxo ideal) |
| `EST_Pct_Fora_Escola` | QEdu | % crianças fora da escola no estado |
| `EST_Distorcao_Ano_Especifico` | QEdu | Distorção do ANO específico da turma (6°, 7°, 8° ou 9°) |
| `EST_LP_Insuficiente_Pct` / `EST_Mat_Insuficiente_Pct` | QEdu | % com proficiência insuficiente no estado |

### Equity (PNAD)
| Coluna | Fonte | O que mede |
|--------|-------|-----------|
| `EST_Pct_Atraso_Escolar_Negro_Estado` | PNAD | Atraso escolar histórico racial — contexto equidade |
| `EST_Pct_Analf_Adulto_Homem/Mulher_Estado` | PNAD | Analfabetismo adulto por gênero — suporte familiar diferenciado |
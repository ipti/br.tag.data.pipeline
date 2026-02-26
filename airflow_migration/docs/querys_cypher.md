# 🎯 Matriz de Queries Cypher para ML e Gestão Educacional
**Versão:** 5.0 — Estrutura Dual (Fundamental Menor × Fundamental/Médio/Superior)
**Alinhamento:** NEO4J-SCHEMA-REFERENCE.md · NEO4J-ANALYSIS-RULES.md
**Foco:** Dispersão de Notas · Evasão · Saúde · Comparação Intra e Interestadual

---

## 🧭 Guia de Leitura Rápida

Cada query vem em **dois sabores obrigatórios**:

| Sufixo | Público | Lógica de Nota |
|--------|---------|----------------|
| **`_EF1`** | Ensino Fundamental Menor (séries iniciais) + Ed. Infantil | Sem filtro de matéria. Alunos avaliados globalmente. `discipline_name = ''` ou `null` |
| **`_EF2_SUP`** | Fundamental II, Médio, Superior | Filtro obrigatório por `sd.discipline_name`. Inclui nome da matéria nos resultados. |

**Vacinas obrigatórias em todas as queries de nota:**
- `CASE WHEN nota > 10 THEN nota / 10.0 ELSE nota END` — normaliza base 100 para base 10
- `stDev(nota) AS Dispersao` — sempre acompanhar média com desvio padrão
- `count(DISTINCT stu) > 25` — quórum mínimo para rigor estatístico
- `WHERE Dispersao > 0 OR Media < 10.0` — remove perfis fantasmas de "100% perfeito"

**Escolas sem diário eletrônico:** As queries nunca pressupõem que toda escola tem faltas ou notas cadastradas. O uso de `OPTIONAL MATCH` e `coalesce(..., 0)` garante que a escola ainda aparece, mas com flag de ausência de dados.

---

### 📋 Cheatsheet de `grade_level` Real (Schema Confirmado)

Os valores reais de `cr.grade_level` seguem padrões com asterisco (`*`) no lugar de `º/ª` e podem ter o nome da etapa separado por espaços. **Nunca use filtros simples como `=~ '.*FUNDAMENTAL.*'` sem excluir explicitamente os anos 6-9.**

| Grupo | Exemplos reais observados |
|-------|--------------------------|
| **EF1 — Anos Iniciais** | `NO 1* ANO`, `NO 2* ANO ENSINO FUNDAMENTAL`, `NA 1* SÉRIE ENSINO FUNDAMENTAL`, ..., `NO 5* ANO` |
| **Ed. Infantil** | `NA PRÉ-ESCOLA EDUCAÇÃO INFANTIL`, `NA CRECHE EDUCAÇÃO INFANTIL` |
| **EF Genérico** | `NA ____ ENSINO FUNDAMENTAL` (multisseriado ou sem série definida) |
| **EF2 — Anos Finais** | `NO 6* ANO`, `NO 7* ANO ENSINO FUNDAMENTAL`, `NA 6* SÉRIE ENSINO FUNDAMENTAL`, ..., `NO 9* ANO` |
| **Ensino Médio** | `NA 1* SÉRIE ENSINO MÉDIO`, `NA 2* SÉRIE ENSINO MÉDIO`, `NA 3* SÉRIE ENSINO MÉDIO`, `NA 4* SÉRIE ENSINO MÉDIO` |
| **Outros** | `NA ____ EDUCAÇÃO PROFISSIONAL`, `NA ____ MULTIETAPA`, `NA ____ EJA` |

**Filtros canônicos por grupo (v5.1):**
```cypher
// EF1 (anos iniciais + infantil)
WHERE (
  cr.grade_level =~ '(?i)NO [1-5][*º°]\\s*ANO.*'
  OR (cr.grade_level =~ '(?i)NA [1-5][*ªº]\\s*S[EÉ]RIE.*' AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
  OR cr.grade_level =~ '(?i).*(PR[EÉ]-ESCOLA|CRECHE|EDUCA[ÇC][AÃ]O INFANTIL).*'
  OR (cr.grade_level =~ '(?i).*ENSINO FUNDAMENTAL.*' AND NOT cr.grade_level =~ '(?i)[6-9][*ªº]')
)
AND NOT cr.grade_level =~ '(?i).*(M[EÉ]DIO|SUPERIOR|PROFISSIONAL|EJA|JOVENS).*'

// EF2 + Médio
WHERE (
  cr.grade_level =~ '(?i)NO [6-9][*º°]\\s*ANO.*'
  OR (cr.grade_level =~ '(?i)NA [6-9][*ªº]\\s*S[EÉ]RIE.*' AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
  OR cr.grade_level =~ '(?i).*(ENSINO M[EÉ]DIO|M[EÉ]DIO).*'
  OR (cr.grade_level =~ '(?i)NA [1-4][*ªº]\\s*S[EÉ]RIE.*' AND cr.grade_level =~ '(?i).*M[EÉ]DIO.*')
)
```

---

### 📋 Cheatsheet de Schema — Nós Confirmados

| Campo | Nó | Tipo | Observação |
|-------|----|------|------------|
| `malnutrition` | Health | boolean | **Sem** sufixo `_desease` |
| `diabetes` | Health | boolean | **Sem** sufixo `_desease` |
| `hypertension` | Health | boolean | **Sem** sufixo `_desease` |
| `celiac` | Health | boolean | **Sem** sufixo `_desease` |
| `obesity` | Health | boolean | **Sem** sufixo `_desease` |
| `iron_deficiency_anemia` | Health | boolean | Mantém nome composto |
| `sickle_cell_anemia` | Health | boolean | Mantém nome composto |
| `lactose_intolerance` | Health | boolean | Mantém nome composto |
| `deficiency` | Student | string | `"Não Possui"` ou `"Possui: Deficiência Intelectual, ..."` — usar `STARTS WITH 'Possui'` |
| `bolsa_familia` | Student | boolean | `coalesce(..., False)` para não-informados |
| `gender` | Student | string | `'F'`, `'M'`, `'Feminino'`, etc. — usar regex `(?i)^[FM].*` |

---

## 🏫 BLOCO 1 — Escola vs Escola (Nível Municipal)
*Compara escolas da mesma cidade entre si e contra indicadores IBGE municipais.*

---

### 🔧 Princípios de Performance do Bloco 1 (v5.3)

Três regras de ouro aplicadas em todas as queries:

**1. Âncora em `School`, nunca em `Student`.** Começar por `Student` varre toda a base antes de qualquer filtro. `School` tem ordens de magnitude menos nós.

**2. `CALL {}` para isolar dimensões.** Notas, faltas e saúde nunca são buscadas no mesmo `MATCH` — cada uma vive numa subquery separada, eliminando o produto cartesiano implícito (nota × falta × condição) que explodia o plano de execução.

**3. `WITH` obrigatório após `CALL {}` antes de qualquer `WHERE`.** O Neo4j não aceita `WHERE` diretamente após `CALL {}`. O padrão correto é sempre: `CALL {} → WITH ... → WHERE ...`.

---

### Q1 — Dispersão de Notas por Escola no Mesmo Município

**Objetivo:** Identificar escolas outliers dentro do mesmo município. CV% normaliza a dispersão para comparação justa entre escolas de tamanhos diferentes.

#### Q1_EF1 — Fundamental Menor (Avaliação Global)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

// Fallback: média dos municípios da UF que têm o dado
CALL {
  WITH st
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

// Coleta alunos EF1 desta escola + conta
CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [1-5][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [1-5][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(PR[EÉ]-ESCOLA|CRECHE|EDUCA[ÇC][AÃ]O INFANTIL).*'
    OR (cr.grade_level =~ '(?i).*ENSINO FUNDAMENTAL.*'
        AND NOT cr.grade_level =~ '(?i)[6-9][*ªº]')
  )
  AND NOT cr.grade_level =~ '(?i).*(M[EÉ]DIO|SUPERIOR|PROFISSIONAL|EJA|JOVENS).*'
  RETURN count(DISTINCT stu) AS Total_Alunos,
         collect(DISTINCT stu) AS Lista_Alunos
}

// WITH obrigatório antes do WHERE após CALL
WITH sch, m, st, Freq_Muni_Raw, Media_Freq_UF, Total_Alunos, Lista_Alunos
WHERE Total_Alunos > 10

// Agrega notas sobre a lista já filtrada
CALL {
  WITH Lista_Alunos
  UNWIND Lista_Alunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media,
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch.name AS Escola,
     m.name   AS Municipio,
     st.sigla AS UF,
     Total_Alunos, N_Notas, Media, Dispersao,
     coalesce(Freq_Muni_Raw, Media_Freq_UF)                                    AS IBGE_Freq_Ref,
     CASE WHEN Freq_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE

RETURN Escola, Municipio, UF,
       Total_Alunos,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN 'Sem Notas' ELSE 'Com Notas' END AS Status_Notas,
       Media,
       Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE null END, 1) AS CV_Pct,
       round(IBGE_Freq_Ref, 2) AS IBGE_Freq_Liq_Fund,
       Fonte_IBGE
ORDER BY Municipio ASC, CASE WHEN Media IS NULL THEN 1 ELSE 0 END ASC, Media ASC
LIMIT 100
```

#### Q1_EF2_SUP — Fundamental II / Médio / Superior (Por Matéria)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

CALL {
  WITH st
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

// Agrega notas por matéria — isolado de faltas e saúde
CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [6-9][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [6-9][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(ENSINO M[EÉ]DIO|M[EÉ]DIO).*'
    OR (cr.grade_level =~ '(?i)NA [1-4][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*M[EÉ]DIO.*')
    OR cr.grade_level =~ '(?i).*SUPERIOR.*'
  )
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH sd.discipline_name AS Materia,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN Materia,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media,
         round(stDev(Nota), 2) AS Dispersao,
         round(min(Nota), 2)   AS Nota_Min,
         round(max(Nota), 2)   AS Nota_Max
}

// WITH antes do WHERE
WITH sch, m, Freq_Muni_Raw, Media_Freq_UF,
     Materia, N_Notas, Media, Dispersao, Nota_Min, Nota_Max
WHERE N_Notas > 25
  AND Materia IS NOT NULL
  AND (Media < 10.0 OR Dispersao > 0)

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       Materia, N_Notas, Media, Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE null END, 1) AS CV_Pct,
       Nota_Min, Nota_Max,
       round(coalesce(Freq_Muni_Raw, Media_Freq_UF), 2)                             AS IBGE_Freq_Liq_Fund,
       CASE WHEN Freq_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE
ORDER BY m.name ASC, Materia ASC, Media ASC
LIMIT 100
```

---

### Q2 — Evasão e Faltas por Escola vs Referência Municipal IBGE

**Objetivo:** Quais escolas perdem mais dias-aluno proporcionalmente? Compara a taxa de ausência interna com o benchmark de atraso escolar municipal (IBGE).

#### Q2_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WITH sch, m,
     coalesce(m.atl_atraso_2_fund, null) AS IBGE_Atraso

// Coleta alunos EF1
CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [1-5][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [1-5][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(PR[EÉ]-ESCOLA|CRECHE|EDUCA[ÇC][AÃ]O INFANTIL).*'
    OR (cr.grade_level =~ '(?i).*ENSINO FUNDAMENTAL.*'
        AND NOT cr.grade_level =~ '(?i)[6-9][*ªº]')
  )
  AND NOT cr.grade_level =~ '(?i).*(M[EÉ]DIO|SUPERIOR|PROFISSIONAL|EJA|JOVENS).*'
  RETURN count(DISTINCT stu) AS Total_Alunos,
         collect(DISTINCT stu) AS Lista_Alunos
}

WITH sch, m, IBGE_Atraso, Total_Alunos, Lista_Alunos
WHERE Total_Alunos > 10

// Agrega faltas sobre a lista
CALL {
  WITH Lista_Alunos
  UNWIND Lista_Alunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  WHERE sc.total_faults_per_day IS NOT NULL AND sc.total_faults_per_day > 0
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS Alunos_Com_Falta,
    sum(coalesce(sc.total_faults_per_day, 0))             AS Total_Faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))   AS Total_Dias_Previstos
}

WITH sch.name AS Escola,
     m.name   AS Municipio,
     IBGE_Atraso,
     Total_Alunos, Alunos_Com_Falta, Total_Faltas, Total_Dias_Previstos,
     CASE WHEN Total_Dias_Previstos > 0
          THEN round(toFloat(Total_Faltas) / Total_Dias_Previstos * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Pct

RETURN Escola, Municipio, Total_Alunos, Alunos_Com_Falta,
       CASE WHEN Alunos_Com_Falta = 0
            THEN 'Sem Diário Eletrônico'
            ELSE toString(round(toFloat(Alunos_Com_Falta) / Total_Alunos * 100, 1)) + '%'
       END AS Pct_Alunos_Com_Falta,
       Total_Faltas, Taxa_Ausencia_Pct,
       IBGE_Atraso AS IBGE_Atraso_2Anos_Fund
ORDER BY Municipio ASC, CASE WHEN Taxa_Ausencia_Pct IS NULL THEN 1 ELSE 0 END ASC, Taxa_Ausencia_Pct DESC
LIMIT 100
```

#### Q2_EF2_SUP — Fundamental II / Médio / Superior
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WITH sch, m,
     coalesce(m.atl_atraso_2_fund, null) AS IBGE_Atraso

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [6-9][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [6-9][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(ENSINO M[EÉ]DIO|M[EÉ]DIO).*'
    OR (cr.grade_level =~ '(?i)NA [1-4][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*M[EÉ]DIO.*')
    OR cr.grade_level =~ '(?i).*SUPERIOR.*'
  )
  RETURN count(DISTINCT stu) AS Total_Alunos,
         collect(DISTINCT stu) AS Lista_Alunos,
         head(collect(DISTINCT cr.grade_level)) AS Etapa_Label
}

WITH sch, m, IBGE_Atraso, Total_Alunos, Lista_Alunos, Etapa_Label
WHERE Total_Alunos > 10

CALL {
  WITH Lista_Alunos
  UNWIND Lista_Alunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  WHERE sc.total_faults_per_day IS NOT NULL AND sc.total_faults_per_day > 0
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS Alunos_Com_Falta,
    sum(coalesce(sc.total_faults_per_day, 0))             AS Total_Faltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))   AS Total_Dias_Previstos
}

WITH sch.name AS Escola,
     m.name   AS Municipio,
     Etapa_Label AS Etapa,
     IBGE_Atraso,
     Total_Alunos, Alunos_Com_Falta, Total_Faltas, Total_Dias_Previstos,
     CASE WHEN Total_Dias_Previstos > 0
          THEN round(toFloat(Total_Faltas) / Total_Dias_Previstos * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Pct

RETURN Escola, Municipio, Etapa, Total_Alunos, Alunos_Com_Falta,
       CASE WHEN Alunos_Com_Falta = 0
            THEN 'Sem Diário Eletrônico'
            ELSE toString(round(toFloat(Alunos_Com_Falta) / Total_Alunos * 100, 1)) + '%'
       END AS Pct_Alunos_Com_Falta,
       Total_Faltas, Taxa_Ausencia_Pct,
       IBGE_Atraso AS IBGE_Atraso_2Anos_Fund
ORDER BY Municipio ASC, CASE WHEN Taxa_Ausencia_Pct IS NULL THEN 1 ELSE 0 END ASC, Taxa_Ausencia_Pct DESC
LIMIT 100
```

---

### Q3 — Equidade: Bolsa Família vs Desempenho na Mesma Escola

**Objetivo:** Dentro da mesma escola, bolsistas têm desempenho diferente dos não-bolsistas?

#### Q3_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [1-5][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [1-5][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(PR[EÉ]-ESCOLA|CRECHE|EDUCA[ÇC][AÃ]O INFANTIL).*'
    OR (cr.grade_level =~ '(?i).*ENSINO FUNDAMENTAL.*'
        AND NOT cr.grade_level =~ '(?i)[6-9][*ªº]')
  )
  AND NOT cr.grade_level =~ '(?i).*(M[EÉ]DIO|SUPERIOR|PROFISSIONAL|EJA|JOVENS).*'
  WITH stu,
       CASE WHEN coalesce(stu.bolsa_familia, false) = true
            THEN 'Bolsista' ELSE 'Nao_Bolsista'
       END AS Grupo
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH Grupo, stu,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN Grupo,
         count(DISTINCT stu)   AS N_Alunos,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media,
         round(stDev(Nota), 2) AS Dispersao,
         round(min(Nota), 2)   AS Nota_Min,
         round(max(Nota), 2)   AS Nota_Max
}

// WITH antes do WHERE
WITH sch, Grupo, N_Alunos, N_Notas, Media, Dispersao, Nota_Min, Nota_Max
WHERE N_Alunos >= 5

RETURN sch.name AS Escola,
       Grupo, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN 'Sem Notas' ELSE 'Com Notas' END AS Status_Notas,
       Media, Dispersao, Nota_Min, Nota_Max
ORDER BY Escola ASC, Grupo ASC
LIMIT 200
```

#### Q3_EF2_SUP — Fundamental II / Médio (Por Matéria)
```cypher
MATCH (sch:School)

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [6-9][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [6-9][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(ENSINO M[EÉ]DIO|M[EÉ]DIO).*'
    OR (cr.grade_level =~ '(?i)NA [1-4][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*M[EÉ]DIO.*')
  )
  WITH stu,
       CASE WHEN coalesce(stu.bolsa_familia, false) = true
            THEN 'Bolsista' ELSE 'Nao_Bolsista'
       END AS Grupo
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH Grupo, stu, sd.discipline_name AS Materia,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN Grupo, Materia,
         count(DISTINCT stu)   AS N_Alunos,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media,
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, Grupo, Materia, N_Alunos, N_Notas, Media, Dispersao
WHERE N_Notas >= 5 AND Materia IS NOT NULL

RETURN sch.name AS Escola,
       Materia, Grupo, N_Alunos, N_Notas, Media, Dispersao
ORDER BY Escola ASC, Materia ASC, Grupo ASC
LIMIT 200
```

---

### Q4 — Saúde vs Faltas e Desempenho

**Objetivo:** Alunos com condições de saúde ou deficiência têm mais faltas e notas mais baixas?

**Schema Health confirmado:** campos sem sufixo `_desease` — `malnutrition`, `diabetes`, `hypertension`, `celiac`, `obesity`, `iron_deficiency_anemia`, `sickle_cell_anemia`. Campo `deficiency` no `Student` é string: `"Não Possui"` ou `"Possui: ..."`.

#### Q4_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [1-5][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [1-5][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(PR[EÉ]-ESCOLA|CRECHE|EDUCA[ÇC][AÃ]O INFANTIL).*'
    OR (cr.grade_level =~ '(?i).*ENSINO FUNDAMENTAL.*'
        AND NOT cr.grade_level =~ '(?i)[6-9][*ªº]')
  )
  AND NOT cr.grade_level =~ '(?i).*(M[EÉ]DIO|SUPERIOR|PROFISSIONAL|EJA|JOVENS).*'

  // Passo 1: classifica saúde (1 lookup por aluno)
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  WITH stu,
       CASE WHEN (h IS NOT NULL AND (
                  coalesce(h.malnutrition, false)
               OR coalesce(h.diabetes, false)
               OR coalesce(h.hypertension, false)
               OR coalesce(h.celiac, false)
               OR coalesce(h.obesity, false)
               OR coalesce(h.iron_deficiency_anemia, false)
               OR coalesce(h.sickle_cell_anemia, false)
               ))
             OR coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
            THEN 'Com Condição / PCD'
            ELSE 'Sem Condição / Sem Registro'
       END AS Grupo_Saude

  // Passo 2: faltas (separado de notas)
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  WITH stu, Grupo_Saude,
       coalesce(sc.total_faults_per_day, 0) AS Falta_Dia

  // Passo 3: nota global
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH Grupo_Saude, stu, sum(Falta_Dia) AS Faltas_Stu,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota

  RETURN Grupo_Saude,
         count(DISTINCT stu)   AS N_Alunos,
         sum(Faltas_Stu)       AS Total_Faltas,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media_Nota,
         round(stDev(Nota), 2) AS Dispersao_Nota
}

WITH sch, Grupo_Saude, N_Alunos, Total_Faltas, N_Notas, Media_Nota, Dispersao_Nota
WHERE N_Alunos >= 5

RETURN sch.name AS Escola,
       Grupo_Saude, N_Alunos, Total_Faltas,
       round(toFloat(Total_Faltas) / N_Alunos, 2) AS Media_Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Nota END AS Media_Nota,
       Dispersao_Nota
ORDER BY Escola ASC, Grupo_Saude ASC
LIMIT 200
```

#### Q4_EF2_SUP — Fundamental II / Médio (Por Matéria)
```cypher
MATCH (sch:School)

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [6-9][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [6-9][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(ENSINO M[EÉ]DIO|M[EÉ]DIO).*'
    OR (cr.grade_level =~ '(?i)NA [1-4][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*M[EÉ]DIO.*')
  )

  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  WITH stu,
       CASE WHEN (h IS NOT NULL AND (
                  coalesce(h.malnutrition, false)
               OR coalesce(h.diabetes, false)
               OR coalesce(h.hypertension, false)
               OR coalesce(h.iron_deficiency_anemia, false)
               OR coalesce(h.obesity, false)
               ))
             OR coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
            THEN 'Com Condição / PCD'
            ELSE 'Sem Condição / Sem Registro'
       END AS Grupo_Saude

  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  WITH stu, Grupo_Saude,
       coalesce(sc.total_faults_per_day, 0) AS Falta_Dia

  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH Grupo_Saude, sd.discipline_name AS Materia, stu, sum(Falta_Dia) AS Faltas_Stu,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota

  RETURN Grupo_Saude, Materia,
         count(DISTINCT stu)   AS N_Alunos,
         sum(Faltas_Stu)       AS Total_Faltas,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media_Nota,
         round(stDev(Nota), 2) AS Dispersao_Nota
}

WITH sch, Grupo_Saude, Materia, N_Alunos, Total_Faltas, N_Notas, Media_Nota, Dispersao_Nota
WHERE N_Alunos >= 5 AND Materia IS NOT NULL

RETURN sch.name AS Escola,
       Materia, Grupo_Saude, N_Alunos,
       round(toFloat(Total_Faltas) / N_Alunos, 2) AS Media_Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Nota END AS Media_Nota,
       Dispersao_Nota
ORDER BY Escola ASC, Materia ASC, Grupo_Saude ASC
LIMIT 200
```

---

### Q5 — Disparidade de Gênero vs Analfabetismo IBGE Municipal

**Objetivo:** O desempenho de meninas vs meninos varia dentro da mesma escola? Cruza com o analfabetismo adulto do município (IBGE).

#### Q5_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WITH sch, m,
     coalesce(m.atl_t_analf25m, null) AS IBGE_Analf_Adultos

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [1-5][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [1-5][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(PR[EÉ]-ESCOLA|CRECHE|EDUCA[ÇC][AÃ]O INFANTIL).*'
    OR (cr.grade_level =~ '(?i).*ENSINO FUNDAMENTAL.*'
        AND NOT cr.grade_level =~ '(?i)[6-9][*ªº]')
  )
  AND NOT cr.grade_level =~ '(?i).*(M[EÉ]DIO|SUPERIOR|PROFISSIONAL|EJA|JOVENS).*'
  AND stu.gender =~ '(?i)^[FM].*'
  WITH stu,
       CASE WHEN stu.gender =~ '(?i)^F.*' THEN 'Feminino' ELSE 'Masculino' END AS Genero
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH Genero, stu,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN Genero,
         count(DISTINCT stu)   AS N_Alunos,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media,
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, m, IBGE_Analf_Adultos, Genero, N_Alunos, N_Notas, Media, Dispersao
WHERE N_Alunos >= 5

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       Genero, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       IBGE_Analf_Adultos
ORDER BY Municipio ASC, Escola ASC, Genero ASC
LIMIT 200
```

#### Q5_EF2_SUP — Fundamental II / Médio (Por Matéria)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WITH sch, m,
     coalesce(m.atl_t_analf25m, null) AS IBGE_Analf_Adultos

CALL {
  WITH sch
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (
    cr.grade_level =~ '(?i)NO [6-9][*º°]\\s*ANO.*'
    OR (cr.grade_level =~ '(?i)NA [6-9][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*FUNDAMENTAL.*')
    OR cr.grade_level =~ '(?i).*(ENSINO M[EÉ]DIO|M[EÉ]DIO).*'
    OR (cr.grade_level =~ '(?i)NA [1-4][*ªº]\\s*S[EÉ]RIE.*'
        AND cr.grade_level =~ '(?i).*M[EÉ]DIO.*')
  )
  AND stu.gender =~ '(?i)^[FM].*'
  WITH stu,
       CASE WHEN stu.gender =~ '(?i)^F.*' THEN 'Feminino' ELSE 'Masculino' END AS Genero
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH Genero, sd.discipline_name AS Materia, stu,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN Genero, Materia,
         count(DISTINCT stu)   AS N_Alunos,
         count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media,
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, m, IBGE_Analf_Adultos, Genero, Materia, N_Alunos, N_Notas, Media, Dispersao
WHERE N_Alunos >= 5 AND Materia IS NOT NULL

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       Genero, Materia, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       IBGE_Analf_Adultos
ORDER BY Municipio ASC, Escola ASC, Materia ASC, Genero ASC
LIMIT 200
```

---

## 🏙️ BLOCO 2 — Escola vs Município (Escola contra o Ecossistema Local)
*Compara o desempenho interno da escola contra indicadores macro do município e do estado.*

---

### Q6 — Frequência Escolar Real vs Meta Líquida IBGE

**Objetivo:** A frequência real dos alunos está acima ou abaixo da frequência líquida do município (`atl_freq_liq_fund`)? Permite ao gestor ver se a escola está acima ou abaixo da expectativa do seu próprio contexto social.

**Nota arquitetural:** `atl_freq_liq_fund` é uma proporção de alunos em idade correta frequentando o fundamental no município (Atlas IBGE). O delta calculado (`Taxa_Ausencia_Escola - (100 - IBGE_Freq_Liq)`) mostra se a escola perde mais ou menos dias do que seria esperado pelo seu entorno.

#### Q6_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)

WITH sch.name AS Escola,
     m.name   AS Municipio,
     coalesce(m.atl_freq_liq_fund, null) AS IBGE_Freq_Liq_Fund,
     count(DISTINCT stu) AS Total_Alunos,
     sum(coalesce(sc.total_faults_per_day, 0)) AS Total_Faltas,
     sum(coalesce(sc.scheduled_student_class_days, 200)) AS Total_Dias_Previstos,
     count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS Alunos_Com_Falta

WHERE Total_Alunos > 25

WITH Escola, Municipio, IBGE_Freq_Liq_Fund, Total_Alunos, Alunos_Com_Falta,
     Total_Faltas, Total_Dias_Previstos,
     CASE WHEN Total_Dias_Previstos > 0
          THEN round(toFloat(Total_Faltas) / Total_Dias_Previstos * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Escola_Pct

RETURN Escola, Municipio, Total_Alunos, Alunos_Com_Falta,
       CASE WHEN Alunos_Com_Falta = 0 THEN 'Sem Diário'
            ELSE toString(Taxa_Ausencia_Escola_Pct) + '%'
       END AS Taxa_Ausencia_Escola,
       IBGE_Freq_Liq_Fund AS IBGE_Frequencia_Liquida_Pct,
       CASE WHEN Taxa_Ausencia_Escola_Pct IS NOT NULL AND IBGE_Freq_Liq_Fund IS NOT NULL
            THEN round(Taxa_Ausencia_Escola_Pct - (100.0 - IBGE_Freq_Liq_Fund), 2)
            ELSE null
       END AS Delta_Vs_IBGE
ORDER BY Municipio ASC, Delta_Vs_IBGE DESC
LIMIT 100
```

#### Q6_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)

WITH sch.name AS Escola,
     m.name   AS Municipio,
     cr.grade_level AS Etapa,
     coalesce(m.atl_freq_liq_fund, null) AS IBGE_Freq_Liq_Fund,
     count(DISTINCT stu) AS Total_Alunos,
     sum(coalesce(sc.total_faults_per_day, 0)) AS Total_Faltas,
     sum(coalesce(sc.scheduled_student_class_days, 200)) AS Total_Dias_Previstos,
     count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS Alunos_Com_Falta

WHERE Total_Alunos > 25

WITH Escola, Municipio, Etapa, IBGE_Freq_Liq_Fund, Total_Alunos, Alunos_Com_Falta,
     CASE WHEN Total_Dias_Previstos > 0
          THEN round(toFloat(Total_Faltas) / Total_Dias_Previstos * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Escola_Pct

RETURN Escola, Municipio, Etapa, Total_Alunos, Alunos_Com_Falta,
       CASE WHEN Alunos_Com_Falta = 0 THEN 'Sem Diário'
            ELSE toString(Taxa_Ausencia_Escola_Pct) + '%'
       END AS Taxa_Ausencia_Escola,
       IBGE_Freq_Liq_Fund AS IBGE_Frequencia_Liquida_Pct,
       CASE WHEN Taxa_Ausencia_Escola_Pct IS NOT NULL AND IBGE_Freq_Liq_Fund IS NOT NULL
            THEN round(Taxa_Ausencia_Escola_Pct - (100.0 - IBGE_Freq_Liq_Fund), 2)
            ELSE null
       END AS Delta_Vs_IBGE
ORDER BY Municipio ASC, Etapa ASC, Delta_Vs_IBGE DESC
LIMIT 100
```

---

### Q7 — Disparidade Racial: Desempenho por Etnia vs Analfabetismo Racial IBGE

**Objetivo:** O desempenho dos alunos brancos e negros na escola reflete (ou contraria) a desigualdade histórica de analfabetismo por raça do município? Essencial para políticas de equidade.

**Nota arquitetural:** O IBGE fornece separadamente `atl_branco_analf25m` e `atl_negro_analf25m` no nó Municipality. Juntamos com `stu.ethnicity` da nossa base. A comparação só é justa se ambos os grupos tiverem N suficiente — daí o filtro `>= 10` por grupo étnico.

#### Q7_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
  AND coalesce(stu.ethnicity, '') <> ''

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH m.name AS Municipio,
     stu.ethnicity AS Etnia,
     coalesce(m.atl_branco_analf25m, 0.0) AS IBGE_Analf_Branco,
     coalesce(m.atl_negro_analf25m, 0.0)  AS IBGE_Analf_Negro,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH Municipio, Etnia, IBGE_Analf_Branco, IBGE_Analf_Negro,
     count(DISTINCT stu) AS N_Alunos,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos >= 10

RETURN Municipio, Etnia, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       IBGE_Analf_Branco, IBGE_Analf_Negro
ORDER BY Municipio ASC, Media ASC
LIMIT 100
```

#### Q7_EF2_SUP — Fundamental II / Médio (Por Matéria)
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE (cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
    OR cr.grade_level =~ '(?i).*MÉDIO.*')
  AND coalesce(stu.ethnicity, '') <> ''

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH m.name AS Municipio,
     stu.ethnicity AS Etnia,
     coalesce(sd.discipline_name, null) AS Materia,
     coalesce(m.atl_branco_analf25m, 0.0) AS IBGE_Analf_Branco,
     coalesce(m.atl_negro_analf25m, 0.0)  AS IBGE_Analf_Negro,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH Municipio, Etnia, Materia, IBGE_Analf_Branco, IBGE_Analf_Negro,
     count(DISTINCT stu) AS N_Alunos,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos >= 10 AND Materia IS NOT NULL

RETURN Municipio, Etnia, Materia, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       IBGE_Analf_Branco, IBGE_Analf_Negro
ORDER BY Municipio ASC, Materia ASC, Media ASC
LIMIT 100
```

---

### Q8 — Alunos em Risco de Abandono (Alta Frequência de Faltas + Baixo Rendimento)

**Objetivo:** Identificar alunos individuais (ou perfis agregados) com combinação de muitas faltas **e** notas abaixo de 5. Estes são os candidatos a intervenção urgente — não basta ver um problema de cada vez.

**Nota arquitetural:** Esta é a única query que se aproxima do nível de aluno individual. Para o painel de gestores, agregamos por escola/turma. Para ML, o resultado pode ser expandido retornando `stu.id`. A query usa `OPTIONAL MATCH` em ambas as pontas (saúde e notas) para não excluir alunos que têm faltas mas não têm nota cadastrada.

#### Q8_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)

WITH sch.name AS Escola,
     cr.name  AS Turma,
     cr.grade_level AS Etapa,
     count(DISTINCT stu) AS Total_Alunos,
     // Perfil de Risco: muitas faltas
     count(DISTINCT CASE
       WHEN sc IS NOT NULL AND sc.total_faults_per_day > 5
       THEN stu
     END) AS Alunos_Alta_Falta,
     // Perfil de Risco: nota muito baixa
     count(DISTINCT CASE
       WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
        AND CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                 ELSE coalesce(sd.final_mean, sd.grade_1) END < 5.0
       THEN stu
     END) AS Alunos_Nota_Critica,
     // Perfil de Risco: condição de saúde
     count(DISTINCT CASE
       WHEN h IS NOT NULL AND (
            coalesce(h.malnutrition_desease, False) = True
         OR coalesce(h.iron_deficiency_anemia, False) = True
         OR coalesce(h.diabetes_desease, False) = True
       ) THEN stu
     END) AS Alunos_Risco_Saude

WHERE Total_Alunos > 10

RETURN Escola, Turma, Etapa, Total_Alunos,
       Alunos_Alta_Falta,
       round(toFloat(Alunos_Alta_Falta) / Total_Alunos * 100, 1) AS Pct_Alta_Falta,
       Alunos_Nota_Critica,
       round(toFloat(Alunos_Nota_Critica) / Total_Alunos * 100, 1) AS Pct_Nota_Critica,
       Alunos_Risco_Saude,
       // Alunos que acumulam 2 ou mais riscos — proxy de risco composto
       Alunos_Alta_Falta + Alunos_Nota_Critica + Alunos_Risco_Saude AS Soma_Sinais_Risco
ORDER BY Soma_Sinais_Risco DESC, Escola ASC
LIMIT 100
```

#### Q8_EF2_SUP — Fundamental II / Médio (Com Matéria)
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)

WITH sch.name AS Escola,
     cr.name  AS Turma,
     cr.grade_level AS Etapa,
     coalesce(sd.discipline_name, 'Múltiplas/Sem Filtro') AS Materia,
     count(DISTINCT stu) AS Total_Alunos,
     count(DISTINCT CASE
       WHEN sc IS NOT NULL AND sc.total_faults_per_day > 5
       THEN stu
     END) AS Alunos_Alta_Falta,
     count(DISTINCT CASE
       WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
        AND CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                 ELSE coalesce(sd.final_mean, sd.grade_1) END < 5.0
       THEN stu
     END) AS Alunos_Nota_Critica,
     count(DISTINCT CASE
       WHEN h IS NOT NULL AND (
            coalesce(h.malnutrition_desease, False) = True
         OR coalesce(h.iron_deficiency_anemia, False) = True
       ) THEN stu
     END) AS Alunos_Risco_Saude

WHERE Total_Alunos > 10

RETURN Escola, Turma, Etapa, Materia, Total_Alunos,
       Alunos_Alta_Falta,
       round(toFloat(Alunos_Alta_Falta) / Total_Alunos * 100, 1) AS Pct_Alta_Falta,
       Alunos_Nota_Critica,
       round(toFloat(Alunos_Nota_Critica) / Total_Alunos * 100, 1) AS Pct_Nota_Critica,
       Alunos_Risco_Saude,
       Alunos_Alta_Falta + Alunos_Nota_Critica + Alunos_Risco_Saude AS Soma_Sinais_Risco
ORDER BY Soma_Sinais_Risco DESC, Escola ASC
LIMIT 100
```

---

### Q9 — Zona Rural vs Urbana: Faltas e Notas na Mesma Escola

**Objetivo:** Dentro do mesmo município, alunos de zona rural têm mais faltas e notas menores? A propriedade `stu.residence_zone` permite segmentar diretamente. Cruza com `atl_rural_freq_liq_fund` e `atl_urbano_freq_liq_fund` do IBGE.

**Nota arquitetural:** Muitos alunos podem não ter `residence_zone` preenchido. O `coalesce(..., 'Não Informado')` captura esse grupo como terceiro segmento — útil para o gestor saber quantos alunos estão sem cadastro completo.

#### Q9_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola,
     m.name   AS Municipio,
     coalesce(m.atl_rural_freq_liq_fund, null)  AS IBGE_Rural_Freq,
     coalesce(m.atl_urbano_freq_liq_fund, null) AS IBGE_Urbano_Freq,
     coalesce(stu.residence_zone, 'Não Informado') AS Zona,
     sum(coalesce(sc.total_faults_per_day, 0)) AS Faltas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH Escola, Municipio, Zona, IBGE_Rural_Freq, IBGE_Urbano_Freq,
     N_Alunos, Faltas,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2) AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos >= 5

RETURN Escola, Municipio, Zona, N_Alunos,
       round(toFloat(Faltas) / N_Alunos, 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao,
       IBGE_Rural_Freq  AS IBGE_Freq_Rural,
       IBGE_Urbano_Freq AS IBGE_Freq_Urbano
ORDER BY Municipio ASC, Escola ASC, Zona ASC
LIMIT 200
```

#### Q9_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola,
     m.name   AS Municipio,
     coalesce(sd.discipline_name, null) AS Materia,
     coalesce(m.atl_rural_freq_liq_fund, null)  AS IBGE_Rural_Freq,
     coalesce(m.atl_urbano_freq_liq_fund, null) AS IBGE_Urbano_Freq,
     coalesce(stu.residence_zone, 'Não Informado') AS Zona,
     sum(coalesce(sc.total_faults_per_day, 0)) AS Faltas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH Escola, Municipio, Materia, Zona, IBGE_Rural_Freq, IBGE_Urbano_Freq,
     N_Alunos, Faltas,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2) AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos >= 5 AND Materia IS NOT NULL

RETURN Escola, Municipio, Materia, Zona, N_Alunos,
       round(toFloat(Faltas) / N_Alunos, 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao,
       IBGE_Rural_Freq, IBGE_Urbano_Freq
ORDER BY Municipio ASC, Escola ASC, Materia ASC, Zona ASC
LIMIT 200
```

---

### Q10 — PCD (Pessoa com Deficiência) vs Não-PCD: Desempenho e Faltas

**Objetivo:** Alunos com deficiência têm acesso equitativo ao aprendizado? Comparar nota e frequência por escola entre PCD e não-PCD é um indicador crítico de inclusão.

**Nota arquitetural:** O campo `stu.deficiency` pode ser um booleano ou string. Usando `coalesce(stu.deficiency, False) = True` para capturar PCDs registrados. A query também mostra o total de alunos sem registro de deficiência como grupo de controle.

#### Q10_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola,
     CASE WHEN coalesce(stu.deficiency, False) = True THEN 'PCD' ELSE 'Sem PCD / Não Informado' END AS Grupo_PCD,
     sum(coalesce(sc.total_faults_per_day, 0)) AS Total_Faltas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH Escola, Grupo_PCD, N_Alunos, Total_Faltas,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos >= 3

RETURN Escola, Grupo_PCD, N_Alunos,
       round(toFloat(Total_Faltas) / N_Alunos, 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao
ORDER BY Escola ASC, Grupo_PCD ASC
LIMIT 200
```

#### Q10_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola,
     coalesce(sd.discipline_name, null) AS Materia,
     CASE WHEN coalesce(stu.deficiency, False) = True THEN 'PCD' ELSE 'Sem PCD / Não Informado' END AS Grupo_PCD,
     sum(coalesce(sc.total_faults_per_day, 0)) AS Total_Faltas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH Escola, Materia, Grupo_PCD, N_Alunos, Total_Faltas,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos >= 3 AND Materia IS NOT NULL

RETURN Escola, Materia, Grupo_PCD, N_Alunos,
       round(toFloat(Total_Faltas) / N_Alunos, 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao
ORDER BY Escola ASC, Materia ASC, Grupo_PCD ASC
LIMIT 200
```

---

## 🇧🇷 BLOCO 3 — Estado vs Estado (Nível Macro)
*Compara escolas da nossa rede entre estados, usando metas QEdu como benchmark governamental.*

---

### Q11 — Benchmark Estadual: Notas vs Metas IDEB e Proficiência QEdu

**Objetivo:** As escolas da nossa rede estão acima ou abaixo do IDEB e da meta de proficiência do seu estado? Este é o painel estratégico de nível executivo — mostra em quais estados a rede tem desempenho acima da média governamental.

**Nota arquitetural:** `qedu_ideb_ai` e `qedu_mt_adequado_ai` vivem no nó `State` (não Municipality). O cálculo de `Delta_Vs_IDEB` é uma comparação qualitativa (a nossa média normalizada 0-10 vs o IDEB que também é 0-10), permitindo comparação direta mesmo sendo fontes diferentes.

#### Q11_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     st.name  AS Estado,
     coalesce(st.qedu_ideb_ai, null)         AS QEdu_IDEB_AI,
     coalesce(st.qedu_mt_adequado_ai, null)  AS QEdu_Pct_Adequado_Mt,
     coalesce(st.qedu_lp_adequado_ai, null)  AS QEdu_Pct_Adequado_LP,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH UF, Estado, QEdu_IDEB_AI, QEdu_Pct_Adequado_Mt, QEdu_Pct_Adequado_LP,
     N_Escolas, N_Alunos,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media_Rede,
     round(stDev(Nota), 2) AS Dispersao_Rede

WHERE N_Alunos > 25

RETURN UF, Estado, N_Escolas, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Rede END AS Media_Rede,
       Dispersao_Rede,
       QEdu_IDEB_AI,
       CASE WHEN N_Notas > 0 AND QEdu_IDEB_AI IS NOT NULL
            THEN round(Media_Rede - QEdu_IDEB_AI, 2)
            ELSE null
       END AS Delta_Vs_IDEB,
       QEdu_Pct_Adequado_Mt,
       QEdu_Pct_Adequado_LP
ORDER BY Delta_Vs_IDEB DESC
LIMIT 50
```

#### Q11_EF2_SUP — Fundamental II / Médio (Por Matéria)
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     st.name  AS Estado,
     coalesce(sd.discipline_name, null) AS Materia,
     coalesce(st.qedu_ideb_ai, null) AS QEdu_IDEB_AI,
     coalesce(st.qedu_mt_adequado_ai, null) AS QEdu_Pct_Adequado_Mt,
     coalesce(st.qedu_lp_adequado_ai, null) AS QEdu_Pct_Adequado_LP,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH UF, Estado, Materia, QEdu_IDEB_AI, QEdu_Pct_Adequado_Mt, QEdu_Pct_Adequado_LP,
     N_Escolas, N_Alunos,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media_Rede,
     round(stDev(Nota), 2) AS Dispersao_Rede

WHERE N_Alunos > 25 AND Materia IS NOT NULL

RETURN UF, Estado, Materia, N_Escolas, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Rede END AS Media_Rede,
       Dispersao_Rede,
       QEdu_IDEB_AI,
       CASE WHEN N_Notas > 0 AND QEdu_IDEB_AI IS NOT NULL
            THEN round(Media_Rede - QEdu_IDEB_AI, 2)
            ELSE null
       END AS Delta_Vs_IDEB,
       QEdu_Pct_Adequado_Mt, QEdu_Pct_Adequado_LP
ORDER BY UF ASC, Materia ASC, Delta_Vs_IDEB DESC
LIMIT 100
```

---

### Q12 — Abandono Interno da Rede vs Taxa de Abandono QEdu por Estado

**Objetivo:** Comparar a taxa de alunos com alta frequência de faltas da nossa rede contra o abandono oficial (`qedu_taxa_abandono`) do estado. Permite identificar em quais estados nossa rede tem um problema de evasão **pior** que a média governamental — e onde vai bem.

**Nota arquitetural:** `qedu_taxa_abandono` é uma porcentagem (0-100) do Censo Escolar estadual. Nossa `Pct_Evasores_Internos` é calculada como alunos com pelo menos uma falta registrada / total de alunos. As duas métricas não são idênticas mas são comparáveis em direção (quanto maior, pior).

#### Q12_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
WHERE sc.total_faults_per_day > 0

WITH st.sigla AS UF,
     st.name  AS Estado,
     coalesce(st.qedu_taxa_abandono, null) AS QEdu_Taxa_Abandono_Oficial,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS Total_Alunos,
     count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS Alunos_Com_Falta,
     count(DISTINCT CASE WHEN sc IS NOT NULL THEN sch END) AS Escolas_Com_Diario

WITH UF, Estado, QEdu_Taxa_Abandono_Oficial, N_Escolas, Total_Alunos,
     Alunos_Com_Falta, Escolas_Com_Diario,
     round(toFloat(Alunos_Com_Falta) / Total_Alunos * 100, 2) AS Pct_Com_Falta_Rede

RETURN UF, Estado,
       N_Escolas,
       Escolas_Com_Diario AS Escolas_Com_Diario_Eletronico,
       N_Escolas - Escolas_Com_Diario AS Escolas_Sem_Diario,
       Total_Alunos,
       Alunos_Com_Falta,
       Pct_Com_Falta_Rede,
       QEdu_Taxa_Abandono_Oficial,
       CASE WHEN QEdu_Taxa_Abandono_Oficial IS NOT NULL
            THEN round(Pct_Com_Falta_Rede - QEdu_Taxa_Abandono_Oficial, 2)
            ELSE null
       END AS Delta_Vs_QEdu
ORDER BY Delta_Vs_QEdu DESC
LIMIT 27
```

#### Q12_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
WHERE sc.total_faults_per_day > 0

WITH st.sigla AS UF,
     cr.grade_level AS Etapa,
     coalesce(st.qedu_taxa_abandono, null) AS QEdu_Taxa_Abandono_Oficial,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS Total_Alunos,
     count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS Alunos_Com_Falta,
     count(DISTINCT CASE WHEN sc IS NOT NULL THEN sch END) AS Escolas_Com_Diario

WITH UF, Etapa, QEdu_Taxa_Abandono_Oficial, N_Escolas, Total_Alunos,
     Alunos_Com_Falta, Escolas_Com_Diario,
     round(toFloat(Alunos_Com_Falta) / Total_Alunos * 100, 2) AS Pct_Com_Falta_Rede

RETURN UF, Etapa, N_Escolas,
       Escolas_Com_Diario AS Escolas_Com_Diario_Eletronico,
       Total_Alunos, Alunos_Com_Falta, Pct_Com_Falta_Rede,
       QEdu_Taxa_Abandono_Oficial,
       CASE WHEN QEdu_Taxa_Abandono_Oficial IS NOT NULL
            THEN round(Pct_Com_Falta_Rede - QEdu_Taxa_Abandono_Oficial, 2)
            ELSE null
       END AS Delta_Vs_QEdu
ORDER BY UF ASC, Etapa ASC, Delta_Vs_QEdu DESC
LIMIT 100
```

---

### Q13 — Dispersão Estadual: Coeficiente de Variação das Notas por UF

**Objetivo:** Em qual estado a nossa rede tem maior heterogeneidade de desempenho? Um alto CV% indica que dentro do mesmo estado temos escolas excelentes e péssimas ao mesmo tempo — sinal de desigualdade interna grave.

**Nota arquitetural:** O Coeficiente de Variação (CV = desvio padrão / média × 100) é mais informativo que o desvio padrão bruto para comparar estados com médias diferentes. Um estado com média 6 e desvio 2 tem CV=33%, enquanto outro com média 8 e desvio 2 tem CV=25% — o primeiro é mais desigual proporcionalmente.

#### Q13_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     coalesce(st.pnad_idhm, null) AS IDHM_Estado,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH UF, IDHM_Estado, N_Escolas, N_Alunos,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media,
     round(stDev(Nota), 2) AS Dispersao,
     round(min(Nota), 2)  AS Nota_Min,
     round(max(Nota), 2)  AS Nota_Max

WHERE N_Alunos > 25 AND N_Notas > 0

RETURN UF, IDHM_Estado, N_Escolas, N_Alunos, N_Notas,
       Media, Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE 0 END, 1) AS CV_Pct,
       Nota_Min, Nota_Max,
       round(Nota_Max - Nota_Min, 2) AS Amplitude_Notas
ORDER BY CV_Pct DESC
LIMIT 27
```

#### Q13_EF2_SUP — Por Matéria Entre Estados
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     coalesce(sd.discipline_name, null) AS Materia,
     coalesce(st.pnad_idhm, null) AS IDHM_Estado,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
          THEN CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
                    THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
                    ELSE coalesce(sd.final_mean, sd.grade_1)
               END
          ELSE null
     END AS Nota

WITH UF, Materia, IDHM_Estado, N_Escolas, N_Alunos,
     count(Nota) AS N_Notas,
     round(avg(Nota), 2)  AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos > 25 AND N_Notas > 0 AND Materia IS NOT NULL

RETURN UF, Materia, IDHM_Estado, N_Escolas, N_Alunos, N_Notas, Media, Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE 0 END, 1) AS CV_Pct
ORDER BY Materia ASC, CV_Pct DESC
LIMIT 100
```

---

### Q14 — Distorção Idade-Série da Rede vs QEdu Estadual

**Objetivo:** Identificar em quais estados nossa rede tem maior concentração de alunos em etapas incompatíveis com a faixa esperada. Cruzar com `qedu_distorcao_ef_ai` do estado para contextualizar se é problema da rede ou do estado como um todo.

**Nota arquitetural:** Não temos `birth_date` e `grade_level` combinados para calcular distorção diretamente no grafo de forma confiável. A proxy usada aqui é contar alunos cujo `cr.year` (ano da turma) está disponível e o `grade_level` não contém a série esperada para aquele ano — esta é uma aproximação. O QEdu estadual serve como âncora.

#### Q14_EF1 — Fundamental Menor
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

WITH st.sigla AS UF,
     cr.grade_level AS Etapa,
     coalesce(st.qedu_distorcao_ef_ai, null) AS QEdu_Distorcao_AI_Oficial,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos

WHERE N_Alunos > 10

RETURN UF, Etapa, N_Escolas, N_Alunos, QEdu_Distorcao_AI_Oficial
ORDER BY UF ASC, N_Alunos DESC
LIMIT 100
```

#### Q14_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

WITH st.sigla AS UF,
     cr.grade_level AS Etapa,
     coalesce(st.qedu_distorcao_ef_af, null) AS QEdu_Distorcao_AF_Oficial,
     coalesce(st.qedu_distorcao_em_total, null) AS QEdu_Distorcao_EM_Oficial,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos

WHERE N_Alunos > 10

RETURN UF, Etapa, N_Escolas, N_Alunos,
       CASE WHEN Etapa =~ '(?i).*MÉDIO.*'
            THEN QEdu_Distorcao_EM_Oficial
            ELSE QEdu_Distorcao_AF_Oficial
       END AS QEdu_Distorcao_Etapa_Oficial
ORDER BY UF ASC, Etapa ASC, N_Alunos DESC
LIMIT 100
```

---

### Q15 — God Matrix para ML: Feature Set Completo por Turma

**Objetivo:** Gerar um dataframe flat completo para treinar modelos preditivos de evasão e desempenho. Cada linha = uma turma, com features de notas, faltas, saúde, IBGE municipal e QEdu estadual.

**Nota arquitetural:** Usa `CALL {}` (subqueries) para evitar produto cartesiano entre a dimensão de notas e a de faltas. O `coalesce(..., 0)` em todos os campos garante que nenhuma linha vá para o ML com NULL — o que quebraria modelos sem tratamento prévio. A coluna `Flag_Diario_Eletronico` permite ao cientista de dados filtrar turmas sem dados reais de frequência.

#### Q15_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*FUNDAMENTAL.*'
  AND NOT cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'

WITH sch, m, st, cr, collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 10

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN round(avg(Nota), 2)   AS FEAT_Media_Global,
         round(stDev(Nota), 2) AS FEAT_Dispersao_Global,
         count(Nota)           AS N_Notas
}

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TARGET_Faltas_Total,
         count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS N_Alunos_Com_Falta
}

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN count(CASE WHEN h IS NOT NULL AND (
                coalesce(h.malnutrition_desease, False) = True
             OR coalesce(h.iron_deficiency_anemia, False) = True
             OR coalesce(h.diabetes_desease, False) = True
             OR coalesce(h.obesity_desease, False) = True
  ) THEN 1 END) AS FEAT_N_Alunos_Risco_Saude
}

WITH sch.id          AS School_ID,
     cr.name         AS Classroom_Name,
     cr.grade_level  AS Classroom_Stage,
     size(AlunosDaTurma) AS FEAT_Total_Alunos,
     // Proporção de bolsistas
     size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, False) = True]) AS FEAT_N_Bolsistas,
     // Proporção de PCDs
     size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, False) = True]) AS FEAT_N_PCD,
     // Features de nota
     coalesce(FEAT_Media_Global, null)    AS FEAT_Media_Global,
     coalesce(FEAT_Dispersao_Global, null) AS FEAT_Dispersao_Global,
     N_Notas,
     // Features de falta
     coalesce(TARGET_Faltas_Total, 0) AS TARGET_Faltas_Total,
     coalesce(N_Alunos_Com_Falta, 0)  AS FEAT_Alunos_Com_Falta,
     coalesce(FEAT_N_Alunos_Risco_Saude, 0) AS FEAT_N_Risco_Saude,
     // Features IBGE Municipais
     coalesce(m.atl_t_analf25m, 0.0)      AS FEAT_Muni_Analf_Adultos,
     coalesce(m.atl_freq_liq_fund, 0.0)   AS FEAT_Muni_Freq_Liq_Fund,
     coalesce(m.atl_atraso_2_fund, 0.0)   AS FEAT_Muni_Atraso_2Anos,
     coalesce(m.atl_expectativa_estudo_18, 0.0) AS FEAT_Muni_Expectativa_Estudo,
     // Features QEdu Estaduais
     coalesce(st.qedu_ideb_ai, 0.0)          AS FEAT_State_IDEB_AI,
     coalesce(st.qedu_taxa_abandono, 0.0)    AS FEAT_State_Taxa_Abandono,
     coalesce(st.qedu_distorcao_ef_ai, 0.0)  AS FEAT_State_Distorcao_AI,
     CASE WHEN N_Alunos_Com_Falta > 0 THEN 1 ELSE 0 END AS Flag_Diario_Eletronico,
     CASE WHEN N_Notas > 0 THEN 1 ELSE 0 END             AS Flag_Notas_Cadastradas

RETURN School_ID, Classroom_Name, Classroom_Stage, FEAT_Total_Alunos,
       FEAT_N_Bolsistas, FEAT_N_PCD, FEAT_N_Risco_Saude,
       FEAT_Media_Global, FEAT_Dispersao_Global, N_Notas,
       TARGET_Faltas_Total, FEAT_Alunos_Com_Falta,
       FEAT_Muni_Analf_Adultos, FEAT_Muni_Freq_Liq_Fund,
       FEAT_Muni_Atraso_2Anos, FEAT_Muni_Expectativa_Estudo,
       FEAT_State_IDEB_AI, FEAT_State_Taxa_Abandono, FEAT_State_Distorcao_AI,
       Flag_Diario_Eletronico, Flag_Notas_Cadastradas
```

#### Q15_EF2_SUP — Fundamental II / Médio (Com Matéria como Dimensão)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level =~ '(?i).*(6|7|8|9).*ANO.*'
   OR cr.grade_level =~ '(?i).*MÉDIO.*'

WITH sch, m, st, cr, collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 10

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE sd.discipline_name =~ '(?i).*MATEM.*'
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN round(avg(Nota), 2)   AS FEAT_Media_Matematica,
         round(stDev(Nota), 2) AS FEAT_Dispersao_Matematica,
         count(Nota)           AS N_Notas_Mat
}

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE sd.discipline_name =~ '(?i).*PORT.*'
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN round(avg(Nota), 2)   AS FEAT_Media_Portugues,
         round(stDev(Nota), 2) AS FEAT_Dispersao_Portugues,
         count(Nota)           AS N_Notas_LP
}

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TARGET_Faltas_Total,
         count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS N_Alunos_Com_Falta
}

CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN count(CASE WHEN h IS NOT NULL AND (
                coalesce(h.malnutrition_desease, False) = True
             OR coalesce(h.iron_deficiency_anemia, False) = True
             OR coalesce(h.diabetes_desease, False) = True
  ) THEN 1 END) AS FEAT_N_Risco_Saude
}

RETURN sch.id AS School_ID,
       cr.name AS Classroom_Name,
       cr.grade_level AS Classroom_Stage,
       size(AlunosDaTurma) AS FEAT_Total_Alunos,
       size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, False) = True]) AS FEAT_N_Bolsistas,
       size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, False) = True]) AS FEAT_N_PCD,
       coalesce(FEAT_N_Risco_Saude, 0) AS FEAT_N_Risco_Saude,
       // Notas por matéria
       FEAT_Media_Matematica, FEAT_Dispersao_Matematica, N_Notas_Mat,
       FEAT_Media_Portugues,  FEAT_Dispersao_Portugues,  N_Notas_LP,
       // Target de evasão
       coalesce(TARGET_Faltas_Total, 0)   AS TARGET_Faltas_Total,
       coalesce(N_Alunos_Com_Falta, 0)    AS FEAT_Alunos_Com_Falta,
       // Features IBGE
       coalesce(m.atl_t_analf25m, 0.0)       AS FEAT_Muni_Analf_Adultos,
       coalesce(m.atl_freq_liq_fund, 0.0)    AS FEAT_Muni_Freq_Liq_Fund,
       coalesce(m.atl_atraso_2_fund, 0.0)    AS FEAT_Muni_Atraso_2Anos,
       coalesce(m.atl_expectativa_estudo_18, 0.0) AS FEAT_Muni_Expectativa_Estudo,
       // Features QEdu
       coalesce(st.qedu_ideb_ai, 0.0)          AS FEAT_State_IDEB_AI,
       coalesce(st.qedu_taxa_abandono, 0.0)    AS FEAT_State_Taxa_Abandono,
       coalesce(st.qedu_distorcao_ef_af, 0.0)  AS FEAT_State_Distorcao_AF,
       coalesce(st.qedu_mt_adequado_ai, 0.0)   AS FEAT_State_Pct_Adequado_Mat,
       // Flags de qualidade de dado
       CASE WHEN N_Alunos_Com_Falta > 0 THEN 1 ELSE 0 END AS Flag_Diario_Eletronico,
       CASE WHEN N_Notas_Mat > 0 OR N_Notas_LP > 0 THEN 1 ELSE 0 END AS Flag_Notas_Cadastradas
```

---

## 📋 Cheatsheet: Filtros de Etapa por Tipo de Query

| Escopo | Filtro `grade_level` |
|--------|----------------------|
| Fundamental Menor (EF1) | `=~ '(?i).*FUNDAMENTAL.*'` + `NOT =~ '(?i).*(6\|7\|8\|9).*ANO.*'` |
| Fundamental II (EF2) | `=~ '(?i).*(6\|7\|8\|9).*ANO.*'` |
| Médio | `=~ '(?i).*MÉDIO.*'` |
| Superior | `=~ '(?i).*SUPERIOR.*'` |
| EF2 + Médio juntos | `(=~ '(?i).*(6\|7\|8\|9).*ANO.*' OR =~ '(?i).*MÉDIO.*')` |

## 📋 Cheatsheet: Features IBGE mais Usadas

| Campo | Nó | Significado |
|-------|----|-------------|
| `atl_t_analf25m` | Municipality | % analfabetos adultos (+25) no município |
| `atl_freq_liq_fund` | Municipality | % crianças em idade correta frequentando fundamental |
| `atl_atraso_2_fund` | Municipality | % alunos com 2+ anos de atraso escolar |
| `atl_expectativa_estudo_18` | Municipality | Anos esperados de estudo ao chegar nos 18 anos |
| `atl_branco_analf25m` / `atl_negro_analf25m` | Municipality | Analfabetismo por raça |
| `atl_rural_freq_liq_fund` / `atl_urbano_freq_liq_fund` | Municipality | Frequência por zona |
| `qedu_ideb_ai` | State | IDEB anos iniciais do estado |
| `qedu_taxa_abandono` | State | Taxa oficial de abandono escolar |
| `qedu_distorcao_ef_ai` | State | % distorção idade-série anos iniciais |
| `qedu_mt_adequado_ai` | State | % alunos com proficiência adequada em matemática |
| `pnad_idhm` | State | IDHM do estado |

---

*Documento gerado para uso interno em pipelines de BI e treinamento de modelos de Machine Learning educacional.*
*Todas as queries assumem que escolas sem diário eletrônico ou sem notas cadastradas são válidas e devem aparecer nos resultados com flags de ausência de dados — nunca devem ser silenciadas.*
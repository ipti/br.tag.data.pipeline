# 🎯 Matriz de Queries Cypher para ML e Gestão Educacional
**Versão:** 5.4 — Schema Real Confirmado + Performance + Fallback IBGE Universal
**Alinhamento:** D_CLASSROOM schema confirmado · NEO4J-SCHEMA-REFERENCE.md
**Foco:** Dispersão de Notas · Evasão · Saúde · Comparação Intra e Interestadual

---

## 🧭 Guia de Leitura Rápida

| Sufixo | Público | Lógica |
|--------|---------|--------|
| **`_EF1`** | Fundamental Menor + Ed. Infantil | `grade_level IN ['NO 1* ANO'...'NO 5* ANO']` |
| **`_EF2_SUP`** | Fundamental II, Médio, Superior | `grade_level IN ['NO 6* ANO'...'NO 9* ANO']` ou `stage = 'ENSINO MÉDIO'` |

**Regras obrigatórias em todas as queries:**
- `CASE WHEN nota > 10 THEN nota/10.0 ELSE nota END` — normaliza base 100
- `CALL (var) { ... }` — sintaxe nova do Neo4j (sem escopo implícito)
- `WITH ... WHERE ...` — nunca `WHERE` diretamente após `CALL {}`
- `CALL {}` por dimensão — notas, faltas e saúde nunca no mesmo MATCH

---

### 📋 Filtros de `grade_level` Confirmados (D_CLASSROOM schema)

`grade_level = row.serie` (apenas a coluna serie, não inclui o stage)

| Grupo | Valores exatos em Neo4j |
|-------|------------------------|
| **EF1** | `'NO 1* ANO'`, `'NO 2* ANO'`, `'NO 3* ANO'`, `'NO 4* ANO'`, `'NO 5* ANO'` |
| **EF2** | `'NO 6* ANO'`, `'NO 7* ANO'`, `'NO 8* ANO'`, `'NO 9* ANO'` |
| **EM** | `cr.stage = 'ENSINO MÉDIO'` (grade_level = `'NA ____________________'` ou `'NA 1* SÉRIE'` etc, ambíguo — usar `stage`) |
| **EI** | `'NA PRÉ-ESCOLA'`, `'NA CRECHE'`, `'NA EDUCAÇÃO INFANTIL'` |
| **Série antiga EF** | `'NA 1* SÉRIE'`..`'NA 9* SÉRIE'` + `cr.stage = 'ENSINO FUNDAMENTAL'` |

**Filtros canônicos:**
```cypher
// EF1
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')

// EF2 + EM
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR','EDUCAÇÃO PROFISSIONAL']
```

---

### 📋 Schema de Nós Confirmado

| Campo | Nó | Tipo | Valor |
|-------|----|------|-------|
| `grade_level` | Classroom | string | `'NO 1* ANO'` etc (= coluna `serie`) |
| `stage` | Classroom | string | `'ENSINO FUNDAMENTAL'`, `'ENSINO MÉDIO'`, `'EDUCAÇÃO INFANTIL'` etc |
| `malnutrition` | Health | boolean | **Sem** `_desease` |
| `diabetes` | Health | boolean | **Sem** `_desease` |
| `hypertension` | Health | boolean | **Sem** `_desease` |
| `celiac` | Health | boolean | **Sem** `_desease` |
| `obesity` | Health | boolean | **Sem** `_desease` |
| `iron_deficiency_anemia` | Health | boolean | Nome composto |
| `sickle_cell_anemia` | Health | boolean | Nome composto |
| `deficiency` | Student | string | `'Não Possui'` ou `'Possui: Deficiência Intelectual...'` — usar `STARTS WITH 'Possui'` |
| `bolsa_familia` | Student | boolean | `coalesce(..., false)` |
| `gender` | Student | string | `'F'`/`'M'`/`'Feminino'` — regex `(?i)^[FM].*` |
| `atl_freq_liq_fund` | Municipality | float | Frequência líquida fundamental |
| `atl_atraso_2_fund` | Municipality | float | % atraso 2+ anos |
| `atl_t_analf25m` | Municipality | float | % analfabetismo adulto |
| `atl_branco_analf25m` / `atl_negro_analf25m` | Municipality | float | Analfabetismo por raça |
| `qedu_ideb_ai` | State | float | IDEB anos iniciais |
| `qedu_taxa_abandono` | State | float | Taxa abandono oficial |
| `qedu_distorcao_ef_ai` / `qedu_distorcao_ef_af` | State | float | Distorção idade-série |
| `qedu_mt_adequado_ai` / `qedu_lp_adequado_ai` | State | float | % proficiência adequada |

**Propriedades que NÃO existem (corrigidas nesta versão):**
- ~~`malnutrition_desease`~~ → `malnutrition`
- ~~`diabetes_desease`~~ → `diabetes`
- ~~`atl_rural_freq_liq_fund`~~ → não existe; use `atl_freq_liq_fund` com filtro de `stu.residence_zone`
- ~~`atl_urbano_freq_liq_fund`~~ → não existe
- ~~`pnad_idhm`~~ → não existe no State; removido das queries

---

## 🏫 BLOCO 1 — Escola vs Escola (Nível Municipal)

---

### Q1 — Dispersão de Notas por Escola no Mesmo Município

**Objetivo:** Identificar escolas outliers dentro do mesmo município. CV% normaliza a dispersão para comparação justa.

**Fallback IBGE:** Quando `atl_freq_liq_fund` está nulo no município, usa a média dos outros municípios da mesma UF. Coluna `Fonte_IBGE` indica a origem.

#### Q1_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

// Fallback IBGE: média UF (nova sintaxe CALL com escopo explícito)
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  RETURN count(DISTINCT stu) AS Total_Alunos,
         collect(DISTINCT stu) AS Lista_Alunos
}

WITH sch, m, st, Freq_Muni_Raw, Media_Freq_UF, Total_Alunos, Lista_Alunos
WHERE Total_Alunos > 10

CALL (Lista_Alunos) {
  UNWIND Lista_Alunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN count(Nota) AS N_Notas,
         round(avg(Nota), 2) AS Media,
         round(stDev(Nota), 2) AS Dispersao
}

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       st.sigla AS UF,
       Total_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN 'Sem Notas' ELSE 'Com Notas' END AS Status_Notas,
       Media, Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE null END, 1) AS CV_Pct,
       round(coalesce(Freq_Muni_Raw, Media_Freq_UF), 2) AS IBGE_Freq_Liq_Fund,
       CASE WHEN Freq_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE
ORDER BY Municipio ASC,
         CASE WHEN Media IS NULL THEN 1 ELSE 0 END ASC,
         Media ASC
LIMIT 100
```

#### Q1_EF2_SUP — Fundamental II / Médio / Superior
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR','EDUCAÇÃO PROFISSIONAL']
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH sd.discipline_name AS Materia,
       CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  RETURN Materia,
         count(Nota) AS N_Notas,
         round(avg(Nota), 2) AS Media,
         round(stDev(Nota), 2) AS Dispersao,
         round(min(Nota), 2) AS Nota_Min,
         round(max(Nota), 2) AS Nota_Max
}

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
       round(coalesce(Freq_Muni_Raw, Media_Freq_UF), 2) AS IBGE_Freq_Liq_Fund,
       CASE WHEN Freq_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE
ORDER BY m.name ASC, Materia ASC, Media ASC
LIMIT 100
```

---

### Q2 — Evasão e Faltas por Escola vs Referência Municipal IBGE

**Objetivo:** Quais escolas perdem mais dias-aluno? Compara taxa de ausência interna com benchmark IBGE.

**Fallback IBGE:** Se `atl_atraso_2_fund` do município for nulo, usa média dos municípios da mesma UF.

#### Q2_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_atraso_2_fund, null) AS Atraso_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_atraso_2_fund IS NOT NULL AND m2.atl_atraso_2_fund > 0
  RETURN avg(m2.atl_atraso_2_fund) AS Media_Atraso_UF
}

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  RETURN count(DISTINCT stu) AS Total_Alunos,
         collect(DISTINCT stu) AS Lista_Alunos
}

WITH sch, m, Atraso_Muni_Raw, Media_Atraso_UF, Total_Alunos, Lista_Alunos
WHERE Total_Alunos > 10

CALL (Lista_Alunos) {
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
     coalesce(Atraso_Muni_Raw, Media_Atraso_UF) AS IBGE_Atraso_Ref,
     CASE WHEN Atraso_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE,
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
       round(IBGE_Atraso_Ref, 2) AS IBGE_Atraso_2Anos_Fund,
       Fonte_IBGE
ORDER BY Municipio ASC,
         CASE WHEN Taxa_Ausencia_Pct IS NULL THEN 1 ELSE 0 END ASC,
         Taxa_Ausencia_Pct DESC
LIMIT 100
```

#### Q2_EF2_SUP — Fundamental II / Médio / Superior
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_atraso_2_fund, null) AS Atraso_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_atraso_2_fund IS NOT NULL AND m2.atl_atraso_2_fund > 0
  RETURN avg(m2.atl_atraso_2_fund) AS Media_Atraso_UF
}

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR','EDUCAÇÃO PROFISSIONAL']
  RETURN count(DISTINCT stu) AS Total_Alunos,
         collect(DISTINCT stu) AS Lista_Alunos,
         head(collect(DISTINCT cr.stage)) AS Etapa_Label
}

WITH sch, m, Atraso_Muni_Raw, Media_Atraso_UF,
     Total_Alunos, Lista_Alunos, Etapa_Label
WHERE Total_Alunos > 10

CALL (Lista_Alunos) {
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
     coalesce(Atraso_Muni_Raw, Media_Atraso_UF) AS IBGE_Atraso_Ref,
     CASE WHEN Atraso_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE,
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
       round(IBGE_Atraso_Ref, 2) AS IBGE_Atraso_2Anos_Fund,
       Fonte_IBGE
ORDER BY Municipio ASC,
         CASE WHEN Taxa_Ausencia_Pct IS NULL THEN 1 ELSE 0 END ASC,
         Taxa_Ausencia_Pct DESC
LIMIT 100
```

---

### Q3 — Equidade: Bolsa Família vs Desempenho na Mesma Escola

#### Q3_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
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

WITH sch, Grupo, N_Alunos, N_Notas, Media, Dispersao, Nota_Min, Nota_Max
WHERE N_Alunos >= 5

RETURN sch.name AS Escola,
       Grupo, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN 'Sem Notas' ELSE 'Com Notas' END AS Status_Notas,
       Media, Dispersao, Nota_Min, Nota_Max
ORDER BY Escola ASC, Grupo ASC
LIMIT 200
```

#### Q3_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
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

**Objetivo:** Alunos com condições de saúde têm mais faltas e notas menores?

**Correlação:** Condições como desnutrição, anemia e diabetes reduzem energia, concentração e presença. O gestor vê se existe gap real de desempenho entre o grupo "Com Condição / PCD" e o restante — o que justifica protocolos de acompanhamento diferenciado. O campo `deficiency` do aluno também entra aqui pois PCDs tendem a ter dinâmica de frequência distinta.

**Performance v5.5 — padrão coletar→isolar→agregar:**
O anti-padrão anterior encadeava 3 `OPTIONAL MATCH` sequenciais dentro de um único `CALL(sch)`, criando um produto cartesiano `N_alunos × N_faltas × N_notas × N_health` antes de qualquer agregação. A solução é um pipeline em 4 passos isolados:
```
CALL(sch)   → filtra por etapa, classifica saúde, retorna Map<stu → GrupoSaude>
CALL(mapa)  → UNWIND, busca faltas, agrega por grupo  (O(N))
CALL(mapa)  → UNWIND, busca notas, agrega por grupo  (O(N×K), K=notas por aluno)
```
Cada `CALL` opera sobre a lista já reduzida, sem cruzar com as outras dimensões.

#### Q4_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)

// Passo 1: filtra alunos EF1, classifica saúde no mesmo passo
// collect() segrega por grupo — evita cross com faltas/notas
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  WITH DISTINCT stu
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
            ELSE 'Sem Condição'
       END AS GrupoSaude
  RETURN GrupoSaude, collect(stu) AS ListaAlunos
}

WITH sch, GrupoSaude, ListaAlunos
WHERE size(ListaAlunos) >= 5

// Passo 2: faltas (dimensão isolada)
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas
}

// Passo 3: notas globais (dimensão isolada)
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN count(Nota)           AS N_Notas,
         round(avg(Nota), 2)   AS Media_Nota,
         round(stDev(Nota), 2) AS Dispersao_Nota
}

RETURN sch.name AS Escola,
       GrupoSaude,
       size(ListaAlunos) AS N_Alunos,
       TotalFaltas,
       round(toFloat(TotalFaltas) / size(ListaAlunos), 2) AS Media_Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Nota END AS Media_Nota,
       Dispersao_Nota
ORDER BY Escola ASC, GrupoSaude ASC
LIMIT 200
```

#### Q4_EF2_SUP — Fundamental II / Médio (por matéria)
```cypher
MATCH (sch:School)

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
  WITH DISTINCT stu
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
            ELSE 'Sem Condição'
       END AS GrupoSaude
  RETURN GrupoSaude, collect(stu) AS ListaAlunos
}

WITH sch, GrupoSaude, ListaAlunos
WHERE size(ListaAlunos) >= 5

CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas
}

CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
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
         round(avg(Nota), 2)   AS Media_Nota,
         round(stDev(Nota), 2) AS Dispersao_Nota
}

WITH sch, GrupoSaude, ListaAlunos, TotalFaltas,
     Materia, N_Notas, Media_Nota, Dispersao_Nota
WHERE Materia IS NOT NULL

RETURN sch.name AS Escola,
       Materia, GrupoSaude,
       size(ListaAlunos) AS N_Alunos,
       round(toFloat(TotalFaltas) / size(ListaAlunos), 2) AS Media_Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Nota END AS Media_Nota,
       Dispersao_Nota
ORDER BY Escola ASC, Materia ASC, GrupoSaude ASC
LIMIT 200
```

---

### Q5 — Disparidade de Gênero vs Contexto Educacional do Estado

**Objetivo:** O gap de desempenho entre meninas e meninos na escola reproduz (ou contraria) a desigualdade educacional estrutural do estado?

**Por que analfabetismo adulto por gênero e não outra métrica?** O PNAD mede `homem_pnad_t_analf25m` e `mulher_pnad_t_analf25m` — a taxa de analfabetismo de adultos +25 por sexo no estado. Isso é o espelho geracional do que a escola está tentando superar: se o estado tem historicamente 4% de analfabetismo feminino contra 2% masculino, e a escola mostra desempenho inverso, ela está **rompendo** o ciclo. Se reproduz o mesmo padrão, está perpetuando. Essa é a correlação relevante.

**Fix v5.5 — dados iguais EF1 e EF2:** O problema estava no escopo da lista. O `CALL(sch)` anterior retornava `collect(stu)` sem separar por gênero, e a separação acontecia fora do escopo filtrado. Resultado: o mesmo conjunto de alunos da escola entrava em ambas as queries. Fix: a separação por gênero e a filtragem por etapa acontecem **dentro do mesmo `CALL`**, retornando listas já segregadas.

#### Q5_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(st.homem_pnad_t_analf25m, null)  AS PNAD_Analf_Homem_Estado,
     coalesce(st.mulher_pnad_t_analf25m, null) AS PNAD_Analf_Mulher_Estado

// Filtra por EF1 e segrega por gênero no mesmo CALL
// → garante que a lista de cada gênero só contém alunos dessa etapa
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL'])
    AND stu.gender =~ '(?i)^[FM].*'
  WITH DISTINCT stu,
       CASE WHEN stu.gender =~ '(?i)^F.*' THEN 'Feminino' ELSE 'Masculino' END AS Genero
  RETURN Genero, collect(stu) AS ListaGenero
}

WITH sch, m, st, PNAD_Analf_Homem_Estado, PNAD_Analf_Mulher_Estado,
     Genero, ListaGenero
WHERE size(ListaGenero) >= 5

// Notas globais para esse grupo de gênero dessa etapa
CALL (ListaGenero) {
  UNWIND ListaGenero AS stu
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

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       st.sigla AS UF,
       Genero,
       size(ListaGenero)  AS N_Alunos,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       // Referência estrutural: qual o analfabetismo adulto do mesmo gênero no estado?
       CASE WHEN Genero = 'Feminino'  THEN PNAD_Analf_Mulher_Estado
            ELSE                           PNAD_Analf_Homem_Estado
       END AS PNAD_Analf_Adulto_Genero_Estado_Pct
ORDER BY Municipio ASC, Escola ASC, Genero ASC
LIMIT 200
```

#### Q5_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(st.homem_pnad_t_analf25m, null)  AS PNAD_Analf_Homem_Estado,
     coalesce(st.mulher_pnad_t_analf25m, null) AS PNAD_Analf_Mulher_Estado

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR'])
    AND stu.gender =~ '(?i)^[FM].*'
  WITH DISTINCT stu,
       CASE WHEN stu.gender =~ '(?i)^F.*' THEN 'Feminino' ELSE 'Masculino' END AS Genero
  RETURN Genero, collect(stu) AS ListaGenero
}

WITH sch, m, st, PNAD_Analf_Homem_Estado, PNAD_Analf_Mulher_Estado,
     Genero, ListaGenero
WHERE size(ListaGenero) >= 5

CALL (ListaGenero) {
  UNWIND ListaGenero AS stu
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
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, m, st, PNAD_Analf_Homem_Estado, PNAD_Analf_Mulher_Estado,
     Genero, ListaGenero, Materia, N_Notas, Media, Dispersao
WHERE Materia IS NOT NULL

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       st.sigla AS UF,
       Genero, Materia,
       size(ListaGenero) AS N_Alunos,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       CASE WHEN Genero = 'Feminino'  THEN PNAD_Analf_Mulher_Estado
            ELSE                           PNAD_Analf_Homem_Estado
       END AS PNAD_Analf_Adulto_Genero_Estado_Pct
ORDER BY Municipio ASC, Escola ASC, Materia ASC, Genero ASC
LIMIT 200
```

---

### Q6 — Frequência Escolar Real vs Meta Líquida IBGE

**Objetivo:** A escola perde mais ou menos dias-aluno do que seria esperado pelo contexto do município?

**Fix v5.5 — mesmos dados EF1 e EF2:** O `StudentClass → Student` não depende de qual classroom o aluno está — ele conta faltas gerais do aluno. Quando a query coletava `Lista_Alunos` filtrada por etapa mas depois contava faltas sobre esses alunos, o resultado era idêntico para ambas as etapas em escolas mistas. Fix: o CALL de faltas opera sobre a lista já filtrada por etapa, e o `Etapa_Label` é derivado do `cr.stage` **dentro** do mesmo CALL de coleta.

#### Q6_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  RETURN collect(DISTINCT stu) AS ListaAlunos
}

WITH sch, m, Freq_Muni_Raw, Media_Freq_UF, ListaAlunos
WHERE size(ListaAlunos) > 10

CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS Alunos_Com_Falta,
    sum(coalesce(sc.total_faults_per_day, 0))           AS TotalFaltas,
    sum(coalesce(sc.scheduled_student_class_days, 200)) AS TotalDias
}

WITH sch.name AS Escola,
     m.name   AS Municipio,
     size(ListaAlunos) AS Total_Alunos,
     coalesce(Freq_Muni_Raw, Media_Freq_UF) AS IBGE_Freq_Ref,
     CASE WHEN Freq_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE,
     Alunos_Com_Falta,
     CASE WHEN TotalDias > 0
          THEN round(toFloat(TotalFaltas) / TotalDias * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Pct

RETURN Escola, Municipio, Total_Alunos,
       Alunos_Com_Falta,
       CASE WHEN Alunos_Com_Falta = 0 THEN 'Sem Diário'
            ELSE toString(Taxa_Ausencia_Pct) + '%'
       END AS Taxa_Ausencia_Escola,
       round(IBGE_Freq_Ref, 2) AS IBGE_Frequencia_Liquida_Pct,
       Fonte_IBGE,
       CASE WHEN Taxa_Ausencia_Pct IS NOT NULL AND IBGE_Freq_Ref IS NOT NULL
            THEN round(Taxa_Ausencia_Pct - (100.0 - IBGE_Freq_Ref), 2)
            ELSE null
       END AS Delta_Vs_IBGE
ORDER BY Municipio ASC, Delta_Vs_IBGE DESC
LIMIT 100
```

#### Q6_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

// Coleta separada por stage para que EF2 e EF1 nunca se sobreponham
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
  WITH DISTINCT stu, cr.stage AS Etapa
  RETURN Etapa, collect(stu) AS ListaAlunos
}

WITH sch, m, Freq_Muni_Raw, Media_Freq_UF, Etapa, ListaAlunos
WHERE size(ListaAlunos) > 10

CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS Alunos_Com_Falta,
    sum(coalesce(sc.total_faults_per_day, 0))           AS TotalFaltas,
    sum(coalesce(sc.scheduled_student_class_days, 200)) AS TotalDias
}

WITH sch.name AS Escola,
     m.name   AS Municipio,
     Etapa,
     size(ListaAlunos) AS Total_Alunos,
     coalesce(Freq_Muni_Raw, Media_Freq_UF) AS IBGE_Freq_Ref,
     CASE WHEN Freq_Muni_Raw IS NOT NULL THEN 'Municipal' ELSE 'Media_UF_Proxy' END AS Fonte_IBGE,
     Alunos_Com_Falta,
     CASE WHEN TotalDias > 0
          THEN round(toFloat(TotalFaltas) / TotalDias * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Pct

RETURN Escola, Municipio, Etapa, Total_Alunos,
       Alunos_Com_Falta,
       CASE WHEN Alunos_Com_Falta = 0 THEN 'Sem Diário'
            ELSE toString(Taxa_Ausencia_Pct) + '%'
       END AS Taxa_Ausencia_Escola,
       round(IBGE_Freq_Ref, 2) AS IBGE_Frequencia_Liquida_Pct,
       Fonte_IBGE,
       CASE WHEN Taxa_Ausencia_Pct IS NOT NULL AND IBGE_Freq_Ref IS NOT NULL
            THEN round(Taxa_Ausencia_Pct - (100.0 - IBGE_Freq_Ref), 2)
            ELSE null
       END AS Delta_Vs_IBGE
ORDER BY Municipio ASC, Etapa ASC, Delta_Vs_IBGE DESC
LIMIT 100
```

---

### Q7 — Disparidade Racial: Desempenho por Etnia vs PNAD Racial do Estado

**Objetivo:** O desempenho de alunos brancos e negros na rede reproduz (ou contraria) a desigualdade histórica de analfabetismo racial do estado?

**Fix v5.5 — IBGE racial saía nulo:** O schema real do nó `Municipality` tem apenas métricas de **acesso a infraestrutura escolar** por raça (`atl_branco_mat_pub_fund`, `atl_negro_internet_fund` etc.), **não analfabetismo**. O analfabetismo racial está confirmado no nó **`State`**: `branco_pnad_t_analf25m` e `negro_pnad_t_analf25m`. Todas as queries agora buscam do nó correto.

#### Q7_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     // CONFIRMADO no nó State — não Municipality
     coalesce(st.branco_pnad_t_analf25m, null) AS PNAD_Analf_Branco,
     coalesce(st.negro_pnad_t_analf25m, null)  AS PNAD_Analf_Negro

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL'])
    AND coalesce(stu.ethnicity, '') <> ''
  WITH DISTINCT stu, stu.ethnicity AS Etnia
  RETURN Etnia, collect(stu) AS ListaEtnia
}

WITH sch, m, st, PNAD_Analf_Branco, PNAD_Analf_Negro,
     Etnia, ListaEtnia
WHERE size(ListaEtnia) >= 10

CALL (ListaEtnia) {
  UNWIND ListaEtnia AS stu
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

RETURN m.name   AS Municipio,
       st.sigla AS UF,
       Etnia,
       size(ListaEtnia) AS N_Alunos,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       PNAD_Analf_Branco AS PNAD_Analf_Branco_Estado_Pct,
       PNAD_Analf_Negro  AS PNAD_Analf_Negro_Estado_Pct
ORDER BY Municipio ASC, Media ASC
LIMIT 100
```

#### Q7_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(st.branco_pnad_t_analf25m, null) AS PNAD_Analf_Branco,
     coalesce(st.negro_pnad_t_analf25m, null)  AS PNAD_Analf_Negro

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE (cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR'])
    AND coalesce(stu.ethnicity, '') <> ''
  WITH DISTINCT stu, stu.ethnicity AS Etnia
  RETURN Etnia, collect(stu) AS ListaEtnia
}

WITH sch, m, st, PNAD_Analf_Branco, PNAD_Analf_Negro,
     Etnia, ListaEtnia
WHERE size(ListaEtnia) >= 10

CALL (ListaEtnia) {
  UNWIND ListaEtnia AS stu
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
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, m, st, PNAD_Analf_Branco, PNAD_Analf_Negro,
     Etnia, ListaEtnia, Materia, N_Notas, Media, Dispersao
WHERE Materia IS NOT NULL

RETURN m.name   AS Municipio,
       st.sigla AS UF,
       Etnia, Materia,
       size(ListaEtnia) AS N_Alunos,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media,
       Dispersao,
       PNAD_Analf_Branco AS PNAD_Analf_Branco_Estado_Pct,
       PNAD_Analf_Negro  AS PNAD_Analf_Negro_Estado_Pct
ORDER BY Municipio ASC, Materia ASC, Media ASC
LIMIT 100
```

---

### Q8 — Alunos em Risco de Abandono (Alta Falta + Nota Crítica + Saúde)

**Performance v5.5:** Coleta alunos da turma, depois 3 CALL independentes para faltas, notas e saúde. Nenhum cross entre dimensões.

#### Q8_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)

// Coleta por turma — granularidade é turma, não escola
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  RETURN cr.name AS Turma, collect(DISTINCT stu) AS ListaTurma
}

WITH sch, Turma, ListaTurma
WHERE size(ListaTurma) > 10

// Dimensão 1: faltas
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN stu,
         sum(coalesce(sc.total_faults_per_day, 0)) AS FaltasStu
}

// Dimensão 2: nota global
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
  RETURN stu,
         CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
              THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
              ELSE coalesce(sd.final_mean, sd.grade_1)
         END AS NotaStu
}

// Dimensão 3: saúde
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN stu,
         CASE WHEN (h IS NOT NULL AND (
                    coalesce(h.malnutrition, false)
                 OR coalesce(h.iron_deficiency_anemia, false)
                 OR coalesce(h.diabetes, false)
                 OR coalesce(h.obesity, false)
                 ))
               OR coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
              THEN 1 ELSE 0
         END AS RiscoSaudeStu
}

// Agrega os 3 sinais por turma
WITH sch.name AS Escola, Turma,
     size(ListaTurma) AS Total_Alunos,
     count(DISTINCT CASE WHEN FaltasStu > 5                             THEN stu END) AS Alunos_Alta_Falta,
     count(DISTINCT CASE WHEN NotaStu IS NOT NULL AND NotaStu < 5.0     THEN stu END) AS Alunos_Nota_Critica,
     count(DISTINCT CASE WHEN RiscoSaudeStu = 1                         THEN stu END) AS Alunos_Risco_Saude

RETURN Escola, Turma, Total_Alunos,
       Alunos_Alta_Falta,
       round(toFloat(Alunos_Alta_Falta)   / Total_Alunos * 100, 1) AS Pct_Alta_Falta,
       Alunos_Nota_Critica,
       round(toFloat(Alunos_Nota_Critica) / Total_Alunos * 100, 1) AS Pct_Nota_Critica,
       Alunos_Risco_Saude,
       Alunos_Alta_Falta + Alunos_Nota_Critica + Alunos_Risco_Saude AS Soma_Sinais_Risco
ORDER BY Soma_Sinais_Risco DESC, Escola ASC
LIMIT 100
```

#### Q8_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
  RETURN cr.name AS Turma, cr.stage AS Etapa, collect(DISTINCT stu) AS ListaTurma
}

WITH sch, Turma, Etapa, ListaTurma
WHERE size(ListaTurma) > 10

CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN stu, sum(coalesce(sc.total_faults_per_day, 0)) AS FaltasStu
}

// Nota de Matemática como proxy de risco cognitivo
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE sd.discipline_name =~ '(?i).*MATEM.*'
  RETURN stu,
         CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
              THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
              ELSE coalesce(sd.final_mean, sd.grade_1)
         END AS NotaStu
}

CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN stu,
         CASE WHEN (h IS NOT NULL AND (
                    coalesce(h.malnutrition, false)
                 OR coalesce(h.iron_deficiency_anemia, false)
                 OR coalesce(h.diabetes, false)
                 ))
               OR coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
              THEN 1 ELSE 0
         END AS RiscoSaudeStu
}

WITH sch.name AS Escola, Turma, Etapa,
     size(ListaTurma) AS Total_Alunos,
     count(DISTINCT CASE WHEN FaltasStu > 5                             THEN stu END) AS Alunos_Alta_Falta,
     count(DISTINCT CASE WHEN NotaStu IS NOT NULL AND NotaStu < 5.0     THEN stu END) AS Alunos_Nota_Critica,
     count(DISTINCT CASE WHEN RiscoSaudeStu = 1                         THEN stu END) AS Alunos_Risco_Saude

RETURN Escola, Turma, Etapa, Total_Alunos,
       Alunos_Alta_Falta,
       round(toFloat(Alunos_Alta_Falta)   / Total_Alunos * 100, 1) AS Pct_Alta_Falta,
       Alunos_Nota_Critica,
       round(toFloat(Alunos_Nota_Critica) / Total_Alunos * 100, 1) AS Pct_Nota_Critica,
       Alunos_Risco_Saude,
       Alunos_Alta_Falta + Alunos_Nota_Critica + Alunos_Risco_Saude AS Soma_Sinais_Risco
ORDER BY Soma_Sinais_Risco DESC, Escola ASC
LIMIT 100
```

---

### Q9 — Zona Rural vs Urbana: Faltas e Notas

**Performance v5.5:** Coleta por zona dentro do CALL de filtragem. Faltas e notas em CALLs separados sobre a lista pré-segregada.

#### Q9_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

// Segrega por zona já no CALL de filtragem
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  WITH DISTINCT stu, coalesce(stu.residence_zone, 'Não Informado') AS Zona
  RETURN Zona, collect(stu) AS ListaZona
}

WITH sch, m, Freq_Muni_Raw, Media_Freq_UF, Zona, ListaZona
WHERE size(ListaZona) >= 5

CALL (ListaZona) {
  UNWIND ListaZona AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas
}

CALL (ListaZona) {
  UNWIND ListaZona AS stu
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

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       Zona,
       size(ListaZona) AS N_Alunos,
       round(toFloat(TotalFaltas) / size(ListaZona), 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao,
       round(coalesce(Freq_Muni_Raw, Media_Freq_UF), 2) AS IBGE_Freq_Liq_Fund
ORDER BY Municipio ASC, Escola ASC, Zona ASC
LIMIT 200
```

#### Q9_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

WITH sch, m, st,
     coalesce(m.atl_freq_liq_fund, null) AS Freq_Muni_Raw

CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Media_Freq_UF
}

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
  WITH DISTINCT stu, coalesce(stu.residence_zone, 'Não Informado') AS Zona
  RETURN Zona, collect(stu) AS ListaZona
}

WITH sch, m, Freq_Muni_Raw, Media_Freq_UF, Zona, ListaZona
WHERE size(ListaZona) >= 5

CALL (ListaZona) {
  UNWIND ListaZona AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas
}

CALL (ListaZona) {
  UNWIND ListaZona AS stu
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
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, m, Freq_Muni_Raw, Media_Freq_UF, Zona, ListaZona, TotalFaltas,
     Materia, N_Notas, Media, Dispersao
WHERE Materia IS NOT NULL

RETURN sch.name AS Escola,
       m.name   AS Municipio,
       Materia, Zona,
       size(ListaZona) AS N_Alunos,
       round(toFloat(TotalFaltas) / size(ListaZona), 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao,
       round(coalesce(Freq_Muni_Raw, Media_Freq_UF), 2) AS IBGE_Freq_Liq_Fund
ORDER BY Municipio ASC, Escola ASC, Materia ASC, Zona ASC
LIMIT 200
```

---

### Q10 — PCD vs Não-PCD: Desempenho e Faltas

**Performance v5.5:** Segrega por grupo PCD dentro do CALL de filtragem, depois 2 CALLs independentes.

#### Q10_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
     OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
  WITH DISTINCT stu,
       CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
            THEN 'PCD' ELSE 'Sem PCD / Não Informado'
       END AS GrupoPCD
  RETURN GrupoPCD, collect(stu) AS ListaPCD
}

WITH sch, GrupoPCD, ListaPCD
WHERE size(ListaPCD) >= 3

CALL (ListaPCD) {
  UNWIND ListaPCD AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas
}

CALL (ListaPCD) {
  UNWIND ListaPCD AS stu
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

RETURN sch.name AS Escola,
       GrupoPCD,
       size(ListaPCD) AS N_Alunos,
       round(toFloat(TotalFaltas) / size(ListaPCD), 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao
ORDER BY Escola ASC, GrupoPCD ASC
LIMIT 200
```

#### Q10_EF2_SUP — Fundamental II / Médio
```cypher
MATCH (sch:School)

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
     OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
  WITH DISTINCT stu,
       CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
            THEN 'PCD' ELSE 'Sem PCD / Não Informado'
       END AS GrupoPCD
  RETURN GrupoPCD, collect(stu) AS ListaPCD
}

WITH sch, GrupoPCD, ListaPCD
WHERE size(ListaPCD) >= 3

CALL (ListaPCD) {
  UNWIND ListaPCD AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TotalFaltas
}

CALL (ListaPCD) {
  UNWIND ListaPCD AS stu
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
         round(stDev(Nota), 2) AS Dispersao
}

WITH sch, GrupoPCD, ListaPCD, TotalFaltas, Materia, N_Notas, Media, Dispersao
WHERE Materia IS NOT NULL

RETURN sch.name AS Escola,
       Materia, GrupoPCD,
       size(ListaPCD) AS N_Alunos,
       round(toFloat(TotalFaltas) / size(ListaPCD), 2) AS Faltas_Por_Aluno,
       N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media END AS Media_Nota,
       Dispersao
ORDER BY Escola ASC, Materia ASC, GrupoPCD ASC
LIMIT 200
```

---
### Q11 — Benchmark Estadual: Notas vs Metas IDEB e Proficiência QEdu

#### Q11_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     st.name  AS Estado,
     coalesce(st.qedu_ideb_ai, null)        AS QEdu_IDEB_AI,
     coalesce(st.qedu_mt_adequado_ai, null) AS QEdu_Pct_Adequado_Mt,
     coalesce(st.qedu_lp_adequado_ai, null) AS QEdu_Pct_Adequado_LP,
     sch, stu,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
          THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
          ELSE coalesce(sd.final_mean, sd.grade_1)
     END AS Nota

WITH UF, Estado, QEdu_IDEB_AI, QEdu_Pct_Adequado_Mt, QEdu_Pct_Adequado_LP,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     count(Nota)         AS N_Notas,
     round(avg(Nota), 2)   AS Media_Rede,
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
       QEdu_Pct_Adequado_Mt, QEdu_Pct_Adequado_LP
ORDER BY Delta_Vs_IDEB DESC
LIMIT 50
```

#### Q11_EF2_SUP — Fundamental II / Médio (Por Matéria)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']

MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     st.name  AS Estado,
     sd.discipline_name AS Materia,
     coalesce(st.qedu_ideb_ai, null)        AS QEdu_IDEB_AI,
     coalesce(st.qedu_mt_adequado_ai, null) AS QEdu_Pct_Adequado_Mt,
     coalesce(st.qedu_lp_adequado_ai, null) AS QEdu_Pct_Adequado_LP,
     sch, stu,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
          THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
          ELSE coalesce(sd.final_mean, sd.grade_1)
     END AS Nota

WITH UF, Estado, Materia, QEdu_IDEB_AI, QEdu_Pct_Adequado_Mt, QEdu_Pct_Adequado_LP,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     count(Nota)         AS N_Notas,
     round(avg(Nota), 2)   AS Media_Rede,
     round(stDev(Nota), 2) AS Dispersao_Rede

WHERE N_Alunos > 25 AND Materia IS NOT NULL

RETURN UF, Estado, Materia, N_Escolas, N_Alunos, N_Notas,
       CASE WHEN N_Notas = 0 THEN null ELSE Media_Rede END AS Media_Rede,
       Dispersao_Rede, QEdu_IDEB_AI,
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

#### Q12_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

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

RETURN UF, Estado, N_Escolas,
       Escolas_Com_Diario AS Escolas_Com_Diario_Eletronico,
       N_Escolas - Escolas_Com_Diario AS Escolas_Sem_Diario,
       Total_Alunos, Alunos_Com_Falta, Pct_Com_Falta_Rede,
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
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']

OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
WHERE sc.total_faults_per_day > 0

WITH st.sigla AS UF,
     cr.stage AS Etapa,
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

**Fix v5.4:** `pnad_idhm` não existe no schema. Removido. Mantido UF + N_Escolas como contexto.

#### Q13_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     sch, stu,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
          THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
          ELSE coalesce(sd.final_mean, sd.grade_1)
     END AS Nota

WITH UF,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     count(Nota)         AS N_Notas,
     round(avg(Nota), 2)   AS Media,
     round(stDev(Nota), 2) AS Dispersao,
     round(min(Nota), 2)   AS Nota_Min,
     round(max(Nota), 2)   AS Nota_Max

WHERE N_Alunos > 25 AND N_Notas > 0

RETURN UF, N_Escolas, N_Alunos, N_Notas,
       Media, Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE 0 END, 1) AS CV_Pct,
       Nota_Min, Nota_Max,
       round(Nota_Max - Nota_Min, 2) AS Amplitude_Notas
ORDER BY CV_Pct DESC
LIMIT 27
```

#### Q13_EF2_SUP — Fundamental II / Médio (Por Matéria Entre Estados)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']

MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH st.sigla AS UF,
     sd.discipline_name AS Materia,
     sch, stu,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
          THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
          ELSE coalesce(sd.final_mean, sd.grade_1)
     END AS Nota

WITH UF, Materia,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos,
     count(Nota)         AS N_Notas,
     round(avg(Nota), 2)   AS Media,
     round(stDev(Nota), 2) AS Dispersao

WHERE N_Alunos > 25 AND N_Notas > 0 AND Materia IS NOT NULL

RETURN UF, Materia, N_Escolas, N_Alunos, N_Notas, Media, Dispersao,
       round(CASE WHEN Media > 0 THEN (Dispersao / Media) * 100 ELSE 0 END, 1) AS CV_Pct
ORDER BY Materia ASC, CV_Pct DESC
LIMIT 100
```

---

### Q14 — Distribuição de Alunos por Etapa e Estado vs Distorção QEdu

#### Q14_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

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
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']

WITH st.sigla AS UF,
     cr.stage AS Etapa,
     coalesce(st.qedu_distorcao_ef_af, null)    AS QEdu_Distorcao_AF_Oficial,
     coalesce(st.qedu_distorcao_em_total, null) AS QEdu_Distorcao_EM_Oficial,
     count(DISTINCT sch) AS N_Escolas,
     count(DISTINCT stu) AS N_Alunos

WHERE N_Alunos > 10

RETURN UF, Etapa, N_Escolas, N_Alunos,
       CASE WHEN Etapa = 'ENSINO MÉDIO'
            THEN QEdu_Distorcao_EM_Oficial
            ELSE QEdu_Distorcao_AF_Oficial
       END AS QEdu_Distorcao_Etapa_Oficial
ORDER BY UF ASC, Etapa ASC, N_Alunos DESC
LIMIT 100
```

---

### Q15 — God Matrix para ML: Feature Set Completo por Turma

#### Q15_EF1 — Fundamental Menor
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

WITH sch, m, st, cr, collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 10

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
  RETURN round(avg(Nota), 2)   AS FEAT_Media_Global,
         round(stDev(Nota), 2) AS FEAT_Dispersao_Global,
         count(Nota)           AS N_Notas
}

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TARGET_Faltas_Total,
         count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS N_Alunos_Com_Falta
}

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN count(CASE WHEN h IS NOT NULL AND (
                coalesce(h.malnutrition, false)
             OR coalesce(h.iron_deficiency_anemia, false)
             OR coalesce(h.diabetes, false)
             OR coalesce(h.obesity, false)
  ) THEN 1 END) AS FEAT_N_Alunos_Risco_Saude
}

RETURN sch.id AS School_ID,
       cr.name AS Classroom_Name,
       cr.grade_level AS Classroom_Grade,
       cr.stage AS Classroom_Stage,
       size(AlunosDaTurma) AS FEAT_Total_Alunos,
       size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, false) = true]) AS FEAT_N_Bolsistas,
       size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS FEAT_N_PCD,
       coalesce(FEAT_N_Alunos_Risco_Saude, 0) AS FEAT_N_Risco_Saude,
       FEAT_Media_Global, FEAT_Dispersao_Global, N_Notas,
       coalesce(TARGET_Faltas_Total, 0)  AS TARGET_Faltas_Total,
       coalesce(N_Alunos_Com_Falta, 0)   AS FEAT_Alunos_Com_Falta,
       coalesce(m.atl_t_analf25m, 0.0)         AS FEAT_Muni_Analf_Adultos,
       coalesce(m.atl_freq_liq_fund, 0.0)       AS FEAT_Muni_Freq_Liq_Fund,
       coalesce(m.atl_atraso_2_fund, 0.0)        AS FEAT_Muni_Atraso_2Anos,
       coalesce(m.atl_expectativa_estudo_18, 0.0) AS FEAT_Muni_Expectativa_Estudo,
       coalesce(st.qedu_ideb_ai, 0.0)           AS FEAT_State_IDEB_AI,
       coalesce(st.qedu_taxa_abandono, 0.0)     AS FEAT_State_Taxa_Abandono,
       coalesce(st.qedu_distorcao_ef_ai, 0.0)   AS FEAT_State_Distorcao_AI,
       CASE WHEN N_Alunos_Com_Falta > 0 THEN 1 ELSE 0 END AS Flag_Diario_Eletronico,
       CASE WHEN N_Notas > 0 THEN 1 ELSE 0 END            AS Flag_Notas_Cadastradas
LIMIT 5000
```

#### Q15_EF2_SUP — Fundamental II / Médio (Mat + Port por Turma)
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']

WITH sch, m, st, cr, collect(DISTINCT stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 10

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE sd.discipline_name =~ '(?i).*MATEM.*'
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN round(avg(Nota), 2)   AS FEAT_Media_Mat,
         round(stDev(Nota), 2) AS FEAT_Dispersao_Mat,
         count(Nota)           AS N_Notas_Mat
}

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE sd.discipline_name =~ '(?i).*PORT.*'
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota
  WHERE Nota IS NOT NULL
  RETURN round(avg(Nota), 2)   AS FEAT_Media_LP,
         round(stDev(Nota), 2) AS FEAT_Dispersao_LP,
         count(Nota)           AS N_Notas_LP
}

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS TARGET_Faltas_Total,
         count(DISTINCT CASE WHEN sc IS NOT NULL AND sc.total_faults_per_day > 0 THEN stu END) AS N_Alunos_Com_Falta
}

CALL (AlunosDaTurma) {
  UNWIND AlunosDaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN count(CASE WHEN h IS NOT NULL AND (
                coalesce(h.malnutrition, false)
             OR coalesce(h.iron_deficiency_anemia, false)
             OR coalesce(h.diabetes, false)
  ) THEN 1 END) AS FEAT_N_Risco_Saude
}

RETURN sch.id AS School_ID,
       cr.name AS Classroom_Name,
       cr.grade_level AS Classroom_Grade,
       cr.stage AS Classroom_Stage,
       size(AlunosDaTurma) AS FEAT_Total_Alunos,
       size([s IN AlunosDaTurma WHERE coalesce(s.bolsa_familia, false) = true]) AS FEAT_N_Bolsistas,
       size([s IN AlunosDaTurma WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS FEAT_N_PCD,
       coalesce(FEAT_N_Risco_Saude, 0) AS FEAT_N_Risco_Saude,
       FEAT_Media_Mat, FEAT_Dispersao_Mat, N_Notas_Mat,
       FEAT_Media_LP,  FEAT_Dispersao_LP,  N_Notas_LP,
       coalesce(TARGET_Faltas_Total, 0)  AS TARGET_Faltas_Total,
       coalesce(N_Alunos_Com_Falta, 0)   AS FEAT_Alunos_Com_Falta,
       coalesce(m.atl_t_analf25m, 0.0)          AS FEAT_Muni_Analf_Adultos,
       coalesce(m.atl_freq_liq_fund, 0.0)        AS FEAT_Muni_Freq_Liq_Fund,
       coalesce(m.atl_atraso_2_fund, 0.0)         AS FEAT_Muni_Atraso_2Anos,
       coalesce(m.atl_expectativa_estudo_18, 0.0)  AS FEAT_Muni_Expectativa_Estudo,
       coalesce(st.qedu_ideb_ai, 0.0)            AS FEAT_State_IDEB_AI,
       coalesce(st.qedu_taxa_abandono, 0.0)      AS FEAT_State_Taxa_Abandono,
       coalesce(st.qedu_distorcao_ef_af, 0.0)    AS FEAT_State_Distorcao_AF,
       coalesce(st.qedu_mt_adequado_ai, 0.0)     AS FEAT_State_Pct_Adequado_Mat,
       CASE WHEN N_Alunos_Com_Falta > 0 THEN 1 ELSE 0 END AS Flag_Diario_Eletronico,
       CASE WHEN N_Notas_Mat > 0 OR N_Notas_LP > 0 THEN 1 ELSE 0 END AS Flag_Notas_Cadastradas
LIMIT 5000
```

---

## 📋 Referência Rápida

### Filtros de Etapa (canônicos v5.4)
```cypher
// EF1 — Fundamental Menor + Educação Infantil
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

// EF2 + EM + Superior
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
   OR cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR','EDUCAÇÃO PROFISSIONAL']
```

### Fallback IBGE Municipal (v5.4 — nova sintaxe CALL)
```cypher
WITH sch, m, st, coalesce(m.atl_freq_liq_fund, null) AS Val_Municipal
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS Val_UF_Proxy
}
// Uso: coalesce(Val_Municipal, Val_UF_Proxy)
```

### Propriedades IBGE disponíveis
| Campo | Nó | Descrição |
|-------|----|-----------|
| `atl_t_analf25m` | Municipality | % analfabetismo adultos (+25) |
| `atl_freq_liq_fund` | Municipality | % frequência líquida fundamental |
| `atl_atraso_2_fund` | Municipality | % atraso 2+ anos |
| `atl_expectativa_estudo_18` | Municipality | Anos esperados de estudo |
| `atl_branco_analf25m` / `atl_negro_analf25m` | Municipality | Analfabetismo por raça |
| `qedu_ideb_ai` | State | IDEB anos iniciais |
| `qedu_taxa_abandono` | State | Taxa abandono oficial |
| `qedu_distorcao_ef_ai` / `qedu_distorcao_ef_af` | State | Distorção idade-série |
| `qedu_mt_adequado_ai` / `qedu_lp_adequado_ai` | State | % proficiência adequada |

---
*v5.4 — Schema confirmado via D_CLASSROOM. grade_level = serie (não stage). CALL (var) {} sintaxe nova. Health sem _desease. deficiency = string.*
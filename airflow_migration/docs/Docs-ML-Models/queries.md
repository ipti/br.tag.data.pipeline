# Cypher Queries — Referência Completa
**Schema:** v5.5 · Neo4j 5.x · Padrão coletar→isolar→agregar

---

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
---

## BLOCO 4 — Scores Compostos

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
---

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
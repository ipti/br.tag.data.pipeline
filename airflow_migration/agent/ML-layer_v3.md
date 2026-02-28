# PLAN: ML Layer — Predição de Evasão & Análise Pedagógica

> **Slug:** `ml-neo4j-school`
> **Tipo:** BACKEND / DATA SCIENCE / MLOps
> **Status:** IMPLEMENTAÇÃO
> **Schema base:** Neo4j confirmado v5.5 (D_CLASSROOM_202602252356 + nós State/Municipality verificados)

---

## 1. Schema Neo4j Confirmado

> Toda query aqui usa exclusivamente propriedades validadas contra os dados reais. Propriedades que **não existem** estão listadas ao final de cada nó para evitar regressões.

### 1.1 Nós e Propriedades

#### `Classroom` (cr)

| Propriedade | Tipo | Valores reais confirmados |
|---|---|---|
| `grade_level` | string | **= coluna `serie` — NUNCA contém a palavra "FUNDAMENTAL"** |
| `stage` | string | `'ENSINO FUNDAMENTAL'`, `'ENSINO MÉDIO'`, `'EDUCAÇÃO INFANTIL'`, `'ENSINO SUPERIOR'` |
| `name` | string | nome da turma |
| `year` | integer | ano letivo |
| `status` | string | status da turma |

**Valores de `grade_level` por segmento:**

```
EF1 (Fundamental Menor):
  'NO 1* ANO', 'NO 2* ANO', 'NO 3* ANO', 'NO 4* ANO', 'NO 5* ANO'
  'NA PRÉ-ESCOLA', 'NA CRECHE', 'NA EDUCAÇÃO INFANTIL'
  'NA 1* SÉRIE' .. 'NA 5* SÉRIE'  ← AMBÍGUO: requer cr.stage = 'ENSINO FUNDAMENTAL'

EF2 (Fundamental Maior):
  'NO 6* ANO', 'NO 7* ANO', 'NO 8* ANO', 'NO 9* ANO'
  'NA 6* SÉRIE' .. 'NA 9* SÉRIE'  ← AMBÍGUO: requer cr.stage = 'ENSINO FUNDAMENTAL'

Ensino Médio:
  cr.stage = 'ENSINO MÉDIO'  ← discriminador principal
  grade_level: 'NA 1* SÉRIE', 'NA 2* SÉRIE', 'NA 3* SÉRIE', 'NA ____________________'

Educação Infantil:
  'NA PRÉ-ESCOLA', 'NA CRECHE', 'NA EDUCAÇÃO INFANTIL'
  'NA ____________________' com cr.stage = 'EDUCAÇÃO INFANTIL'
```

**Filtros Cypher canônicos (usar em todas as queries):**

```cypher
// EF1
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

// EF2
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')

// EM / Superior
WHERE cr.stage IN ['ENSINO MÉDIO','ENSINO SUPERIOR']
```

---

#### `Student` (stu)

| Propriedade | Tipo | Observação |
|---|---|---|
| `gender` | string | Verificar com `=~ '(?i)^[FM].*'`. Codificar: F→1, M→0 |
| `ethnicity` | string | Pode estar vazio. Valores: Branca, Parda, Preta, Amarela, Indígena, Não Declarada |
| `deficiency` | **string** | `'Não Possui'` ou `'Possui: Deficiência Intelectual...'`. **NÃO é boolean.** Check: `STARTS WITH 'Possui'` |
| `bolsa_familia` | boolean | `true`/`false` |
| `residence_zone` | string | Zona rural/urbana. Pode ser nulo → coalesce para `'Não Informado'` |

---

#### `Health` (h) — via `(stu)-[:HAS_HEALTH]->(h)`

| Propriedade | Tipo | Observação |
|---|---|---|
| `malnutrition` | boolean | ⚠️ **NÃO** `malnutrition_desease` |
| `diabetes` | boolean | ⚠️ **NÃO** `diabetes_desease` |
| `hypertension` | boolean | |
| `celiac` | boolean | |
| `obesity` | boolean | |
| `iron_deficiency_anemia` | boolean | nome composto, sem `_desease` |
| `sickle_cell_anemia` | boolean | nome composto, sem `_desease` |

**Acesso correto:**
```cypher
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
WITH stu,
     coalesce(h.malnutrition, false)            AS has_malnutrition,
     coalesce(h.diabetes, false)                AS has_diabetes,
     coalesce(h.iron_deficiency_anemia, false)  AS has_anemia,
     coalesce(h.obesity, false)                 AS has_obesity,
     CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END  AS has_health_record
```

---

#### `StudentDiscipline` (sd) — via `(stu)-[:HAS_DISCIPLINE]->(sd)`

| Propriedade | Tipo | Observação |
|---|---|---|
| `discipline_name` | string | **`''` (vazio) = nota global EF1. Preenchido = nota por matéria EF2** |
| `final_mean` | float | Pode ser em escala 0–100. Normalizar: `CASE WHEN val > 10 THEN val/10.0 ELSE val END` |
| `grade_1` | float | Nota do 1º bimestre/período. Mesma normalização. |
| `grade_2` | float | |
| `grade_3` | float | |
| `grade_4` | float | |

**Distinção crítica EF1 vs EF2:**
```cypher
// EF1 — nota global (um registro por aluno)
WHERE coalesce(sd.discipline_name, '') = ''

// EF2 — nota por matéria (N registros por aluno)
WHERE coalesce(sd.discipline_name, '') <> ''
```

---

#### `StudentClass` (sc) — via `(sc:StudentClass)-[:ATTENDED]->(stu)`

| Propriedade | Tipo | Observação |
|---|---|---|
| `total_faults_per_day` | integer | Total de dias de falta do aluno |
| `scheduled_student_class_days` | integer | Dias previstos. `coalesce(val, 200)` se nulo |

**Taxa de ausência:**
```cypher
toFloat(sc.total_faults_per_day) / coalesce(sc.scheduled_student_class_days, 200)
```

---

#### `Municipality` (m) — via `School→SchoolGeograph→Municipality`

| Propriedade confirmada | O que mede |
|---|---|
| `atl_freq_liq_fund` | % frequência líquida fundamental |
| `atl_atraso_2_fund` | % alunos com 2+ anos de atraso |
| `atl_t_analf25m` | % analfabetismo adulto +25 |
| `atl_expectativa_estudo_18` | Anos esperados de estudo aos 18 |
| `atl_branco_mat_pub_fund` | % brancos em escola pública |
| `atl_negro_mat_pub_fund` | % negros em escola pública |
| `atl_branco_internet_fund` | % escolas fund c/ internet para brancos |
| `atl_negro_internet_fund` | % escolas fund c/ internet para negros |

**⚠️ Propriedades que NÃO existem em Municipality:**
```
atl_branco_analf25m        ← não existe (analfabetismo racial está no State)
atl_negro_analf25m         ← não existe
atl_rural_freq_liq_fund    ← não existe (usar atl_freq_liq_fund + filtro por stu.residence_zone)
atl_urbano_freq_liq_fund   ← não existe
```

---

#### `State` (st) — via `Municipality→State`

**PNAD por raça:**

| Propriedade | O que mede |
|---|---|
| `branco_pnad_t_analf25m` | % analfabetismo adulto branco +25 |
| `negro_pnad_t_analf25m` | % analfabetismo adulto negro +25 |
| `branco_pnad_t_atraso_fund` | % atraso escolar brancos |
| `negro_pnad_t_atraso_fund` | % atraso escolar negros |
| `branco_pnad_idhm_e` | IDHM educação brancos |
| `negro_pnad_idhm_e` | IDHM educação negros |
| `branco_pnad_rdpc` | Renda per capita brancos |
| `negro_pnad_rdpc` | Renda per capita negros |
| `branco_pnad_ppob` | % pobreza brancos |
| `negro_pnad_ppob` | % pobreza negros |

**PNAD por gênero:**

| Propriedade | O que mede |
|---|---|
| `homem_pnad_t_analf25m` | % analfabetismo adulto masculino +25 |
| `mulher_pnad_t_analf25m` | % analfabetismo adulto feminino +25 |
| `homem_pnad_idhm_e` | IDHM educação homens |
| `mulher_pnad_idhm_e` | IDHM educação mulheres |
| `homem_pnad_rdpc` | Renda per capita homens |
| `mulher_pnad_rdpc` | Renda per capita mulheres |
| `homem_pnad_t_fund18m` | % fundamental completo +18 homens |
| `mulher_pnad_t_fund18m` | % fundamental completo +18 mulheres |

**QEdu — Qualidade e Fluxo:**

| Propriedade | O que mede |
|---|---|
| `qedu_ideb_ai` / `qedu_ideb_af` / `qedu_ideb_em` | IDEB por segmento |
| `qedu_taxa_abandono` | Taxa de abandono oficial |
| `qedu_taxa_reprovacao` | Taxa de reprovação |
| `qedu_taxa_aprovacao` | Taxa de aprovação |
| `qedu_fluxo_ai` / `qedu_fluxo_af` / `qedu_fluxo_em` | Fluxo escolar (0=retenção total, 1=ideal) |
| `qedu_pct_fora_escola` | % crianças fora da escola |
| `qedu_aprendizado_ai` / `qedu_aprendizado_af` / `qedu_aprendizado_em` | Nota de aprendizado |
| `qedu_distorcao_ef1` .. `qedu_distorcao_ef9` | Distorção por ano escolar específico |
| `qedu_distorcao_ef_ai` / `qedu_distorcao_ef_af` / `qedu_distorcao_em_total` | Distorção agregada |
| `qedu_lp_adequado_ai/af/em` | % proficiência adequada LP |
| `qedu_mt_adequado_ai/af/em` | % proficiência adequada Matemática |
| `qedu_lp_insuficiente_ai/af/em` | % proficiência insuficiente LP |
| `qedu_mt_insuficiente_ai/af/em` | % proficiência insuficiente Matemática |

**⚠️ Propriedades que NÃO existem em State:**
```
pnad_idhm           ← não existe sem prefixo racial/gênero
st.idhm             ← não existe
```

---

### 1.2 Relacionamentos Confirmados

```
School         <-[:ENROLLED_AT_SCHOOL]-  Student
Student         -[:ENROLLED_IN]->        Classroom
Student         -[:HAS_HEALTH]->         Health
Student         -[:HAS_DISCIPLINE]->     StudentDiscipline
StudentClass    -[:ATTENDED]->           Student
School          -[:HAS_GEOGRAPHY]->      SchoolGeograph
SchoolGeograph  -[:LOCATED_IN_MUNICIPALITY]-> Municipality
Municipality    -[:BELONGS_TO_STATE]->   State
```

---

### 1.3 Padrão de Performance Cypher Obrigatório

Toda query que acessa múltiplas dimensões por aluno (faltas, notas, saúde) **deve** usar o padrão coletar→isolar→agregar. O anti-padrão com OPTIONAL MATCH encadeados cria produto cartesiano N×M×K e causa timeout.

```cypher
// ✅ CORRETO — cada dimensão em CALL isolada
MATCH (sch:School)
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE <filtro_grade>
  WITH DISTINCT stu
  RETURN collect(stu) AS Lista
}
CALL (Lista) { UNWIND Lista AS stu; OPTIONAL MATCH saude;     RETURN agg_saude  }
CALL (Lista) { UNWIND Lista AS stu; OPTIONAL MATCH faltas;    RETURN agg_faltas }
CALL (Lista) { UNWIND Lista AS stu; OPTIONAL MATCH notas;     RETURN agg_notas  }
// BF/PCD: list comprehension sem UNWIND
size([s IN Lista WHERE coalesce(s.bolsa_familia, false) = true]) AS N_BF

// ❌ ERRADO — encadeado causa timeout
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu)-[:ENROLLED_IN]->(cr)
  WHERE <filtro>
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h)
  OPTIONAL MATCH (sc)-[:ATTENDED]->(stu)      // ← produto cartesiano aqui
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd) // ← explode N×M×K
  RETURN ...
}

// ⚠️ SINTAXE — sempre CALL (var) {}, nunca CALL { WITH var }
CALL (sch) { ... }   // ✅
CALL { WITH sch ... } // ❌ deprecated
```

---

## 2. Feature Engineering — Mapeamento Explícito

### 2.1 Targets

| Target | Tipo | Derivação |
|---|---|---|
| `evasao` | binário 0/1 | `taxa_ausencia > 0.25` OR `enrollment_status` indica inativo |
| `nota_final_norm` | float 0.0–10.0 | `sd.final_mean` normalizado: `IF > 10 THEN /10.0 ELSE keep` |
| `risco_reprovacao` | binário 0/1 | `nota_final_norm < 5.0` |
| `trajetoria` | float, pode ser negativo | `nota_final_norm - nota_g1_norm` |

### 2.2 Feature Set Completo (~51 features)

#### Demográficas — `Student`
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `gender_bin` | `1 se gender =~ '^F.*' else 0` | `stu.gender` |
| `ethnicity_enc` | label-encode 0–5 | `stu.ethnicity` |
| `has_deficiency` | `1 se deficiency STARTS WITH 'Possui' else 0` | `stu.deficiency` (string, não boolean) |
| `bolsa_familia` | `boolean → 0/1` | `stu.bolsa_familia` |
| `residence_zone_enc` | label-encode: Urbana=1, Rural=0, NI=2 | `stu.residence_zone` |

#### Saúde — `Health` (OPTIONAL MATCH via HAS_HEALTH)
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `has_health_record` | `1 se nó existe, 0 se OPTIONAL sem match` | presença do nó |
| `has_malnutrition` | `coalesce(h.malnutrition, false)` | `h.malnutrition` (**não** `h.malnutrition_desease`) |
| `has_diabetes` | `coalesce(h.diabetes, false)` | `h.diabetes` (**não** `h.diabetes_desease`) |
| `has_hypertension` | `coalesce(h.hypertension, false)` | `h.hypertension` |
| `has_obesity` | `coalesce(h.obesity, false)` | `h.obesity` |
| `has_anemia` | `coalesce(h.iron_deficiency_anemia, false) OR coalesce(h.sickle_cell_anemia, false)` | ambas sem `_desease` |
| `n_health_conditions` | soma de todos os booleanos acima | calculado |

#### Frequência — `StudentClass` (OPTIONAL MATCH via ATTENDED)
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `taxa_ausencia` | `total_faults / coalesce(scheduled_days, 200)` | `sc.total_faults_per_day`, `sc.scheduled_student_class_days` |
| `falta_critica` | `1 se taxa_ausencia > 0.10` | calculado |
| `total_faltas_abs` | `sum(sc.total_faults_per_day)` | `sc.total_faults_per_day` |
| `tem_diario_eletronico` | `1 se StudentClass existe, 0 caso contrário` | presença do nó |

#### Notas EF1 — `StudentDiscipline WHERE discipline_name = ''`
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `nota_final_norm` | `CASE WHEN sd.final_mean > 10 THEN sd.final_mean/10.0 ELSE sd.final_mean END` | `sd.final_mean` |
| `nota_g1_norm` | mesma normalização | `sd.grade_1` |
| `nota_g2_norm` | mesma normalização | `sd.grade_2` |
| `trajetoria_nota` | `nota_final_norm - nota_g1_norm` | calculado |
| `em_recuperacao` | `1 se nota_final_norm < 5.0` | calculado |

#### Notas EF2 — `StudentDiscipline WHERE discipline_name <> ''` (pivot por matéria)
| Feature | Derivação |
|---|---|
| `nota_mat_norm` | `final_mean` normalizado onde `discipline_name =~ '(?i).*MATEM.*'` |
| `nota_lp_norm` | `final_mean` normalizado onde `discipline_name =~ '(?i).*PORTUGU.*'` |
| `nota_media_geral` | `avg(final_mean_norm)` across all disciplines |
| `n_disciplinas_abaixo5` | `count(sd WHERE final_mean_norm < 5.0)` |
| `n_disciplinas_total` | `count(sd)` |
| `pct_disciplinas_abaixo5` | `n_abaixo5 / n_total` |
| `trajetoria_media` | `avg(final_mean_norm) - avg(grade_1_norm)` |

#### Contexto da Turma — `Classroom`
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `stage_enc` | label-encode: EI=0, EF1=1, EF2=2, EM=3, ES=4 | `cr.stage` |
| `grade_level_enc` | ordinal: PRÉ-ESCOLA=0, NO 1* ANO=1 .. NO 9* ANO=9, EM=10 | `cr.grade_level` |
| `ano_letivo` | inteiro | `cr.year` |

#### Contexto Municipal — `Municipality` (OPTIONAL via School→SchoolGeograph→Municipality)
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `muni_freq_liq_fund` | direto, com UF fallback se nulo | `m.atl_freq_liq_fund` |
| `muni_atraso_2anos` | direto | `m.atl_atraso_2_fund` |
| `muni_analf_adulto` | direto | `m.atl_t_analf25m` |
| `muni_expectativa_estudo` | direto | `m.atl_expectativa_estudo_18` |
| `muni_pct_negro_pub` | direto | `m.atl_negro_mat_pub_fund` |
| `muni_delta_freq` | `taxa_ausencia - (100 - muni_freq_liq_fund)` | calculado |

#### Contexto Estadual — `State` (QEdu)
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `est_ideb_ai` | direto | `st.qedu_ideb_ai` |
| `est_ideb_af` | direto | `st.qedu_ideb_af` |
| `est_taxa_abandono` | direto | `st.qedu_taxa_abandono` |
| `est_taxa_reprovacao` | direto | `st.qedu_taxa_reprovacao` |
| `est_fluxo_af` | direto | `st.qedu_fluxo_af` |
| `est_distorcao_serie` | `qedu_distorcao_ef{N}` matching `grade_level_enc` | ex.: `qedu_distorcao_ef6` para 6º ano |
| `est_pct_fora_escola` | direto | `st.qedu_pct_fora_escola` |
| `est_lp_insuf_af` | direto | `st.qedu_lp_insuficiente_af` |
| `est_mat_insuf_af` | direto | `st.qedu_mt_insuficiente_af` |

#### Contexto Estadual — `State` (PNAD)
| Feature | Derivação | Propriedade Neo4j |
|---|---|---|
| `est_analf_negro` | direto | `st.negro_pnad_t_analf25m` |
| `est_analf_branco` | direto | `st.branco_pnad_t_analf25m` |
| `est_atraso_negro` | direto | `st.negro_pnad_t_atraso_fund` |
| `est_analf_homem` | direto | `st.homem_pnad_t_analf25m` |
| `est_analf_mulher` | direto | `st.mulher_pnad_t_analf25m` |

---

## 3. Cypher de Extração de Features (para Pandas)

### 3.1 Query de Extração — EF1

```cypher
// Extrai 1 linha por aluno EF1 com todas as features
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// Fallback UF para freq municipal nula
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS uf_freq_media
}

MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']

WITH DISTINCT stu, cr, sch, m, st, uf_freq_media

OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
WITH stu, cr, sch, m, st, uf_freq_media, h

CALL (stu) {
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN sum(coalesce(sc.total_faults_per_day, 0)) AS total_faltas,
         sum(coalesce(sc.scheduled_student_class_days, 200)) AS total_dias,
         CASE WHEN sc IS NOT NULL THEN 1 ELSE 0 END AS tem_diario
}

CALL (stu) {
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS nota_final,
       CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
            THEN sd.grade_1 / 10.0 ELSE sd.grade_1 END AS nota_g1
  RETURN nota_final,
         nota_g1,
         CASE WHEN nota_final IS NOT NULL AND nota_g1 IS NOT NULL
              THEN nota_final - nota_g1 ELSE null END AS trajetoria
}

WITH stu, cr, sch, m, st, uf_freq_media, h,
     total_faltas, total_dias, tem_diario,
     nota_final, nota_g1, trajetoria,
     coalesce(m.atl_freq_liq_fund, uf_freq_media) AS freq_ref

RETURN
  // Identificação (remover antes de treinar, manter para join)
  stu.id                         AS student_id,
  sch.id                         AS school_id,
  st.sigla                       AS uf,

  // Demográficas
  CASE WHEN stu.gender =~ '(?i)^F.*' THEN 1 ELSE 0 END AS gender_bin,
  coalesce(stu.ethnicity, 'NI')  AS ethnicity_enc,
  CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN 1 ELSE 0 END AS has_deficiency,
  CASE WHEN coalesce(stu.bolsa_familia, false) THEN 1 ELSE 0 END AS bolsa_familia,
  coalesce(stu.residence_zone, 'Não Informado') AS residence_zone_enc,

  // Saúde
  CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END AS has_health_record,
  CASE WHEN coalesce(h.malnutrition, false) THEN 1 ELSE 0 END AS has_malnutrition,
  CASE WHEN coalesce(h.diabetes, false) THEN 1 ELSE 0 END AS has_diabetes,
  CASE WHEN coalesce(h.hypertension, false) THEN 1 ELSE 0 END AS has_hypertension,
  CASE WHEN coalesce(h.obesity, false) THEN 1 ELSE 0 END AS has_obesity,
  CASE WHEN coalesce(h.iron_deficiency_anemia, false)
        OR coalesce(h.sickle_cell_anemia, false) THEN 1 ELSE 0 END AS has_anemia,

  // Frequência
  tem_diario,
  CASE WHEN total_dias > 0 THEN round(toFloat(total_faltas) / total_dias, 4) ELSE null END AS taxa_ausencia,
  total_faltas                   AS total_faltas_abs,
  CASE WHEN total_dias > 0 AND toFloat(total_faltas) / total_dias > 0.10 THEN 1 ELSE 0 END AS falta_critica,

  // Notas EF1 (nota global)
  nota_final                     AS nota_final_norm,
  nota_g1                        AS nota_g1_norm,
  trajetoria                     AS trajetoria_nota,
  CASE WHEN nota_final IS NOT NULL AND nota_final < 5.0 THEN 1 ELSE 0 END AS em_recuperacao,

  // Contexto turma
  cr.stage                       AS stage,
  cr.grade_level                 AS grade_level,
  cr.year                        AS ano_letivo,

  // Contexto municipal
  round(coalesce(m.atl_freq_liq_fund, null), 4)     AS muni_freq_liq_fund,
  round(coalesce(m.atl_atraso_2_fund, null), 4)     AS muni_atraso_2anos,
  round(coalesce(m.atl_t_analf25m, null), 4)        AS muni_analf_adulto,
  round(coalesce(m.atl_expectativa_estudo_18, null), 4) AS muni_expectativa_estudo,
  round(coalesce(m.atl_negro_mat_pub_fund, null), 4) AS muni_pct_negro_pub,
  CASE WHEN total_dias > 0 AND freq_ref IS NOT NULL
       THEN round(toFloat(total_faltas)/total_dias*100 - (100.0 - freq_ref), 4)
       ELSE null END AS muni_delta_freq,

  // Contexto estadual — QEdu
  st.qedu_ideb_ai                AS est_ideb_ai,
  st.qedu_taxa_abandono          AS est_taxa_abandono,
  st.qedu_taxa_reprovacao        AS est_taxa_reprovacao,
  st.qedu_fluxo_ai               AS est_fluxo_ai,
  st.qedu_pct_fora_escola        AS est_pct_fora_escola,
  // Distorção do ano específico da turma
  CASE cr.grade_level
    WHEN 'NO 1* ANO' THEN st.qedu_distorcao_ef1
    WHEN 'NO 2* ANO' THEN st.qedu_distorcao_ef2
    WHEN 'NO 3* ANO' THEN st.qedu_distorcao_ef3
    WHEN 'NO 4* ANO' THEN st.qedu_distorcao_ef4
    WHEN 'NO 5* ANO' THEN st.qedu_distorcao_ef5
    ELSE st.qedu_distorcao_ef_ai
  END                            AS est_distorcao_serie,
  st.qedu_lp_insuficiente_ai    AS est_lp_insuf_ai,
  st.qedu_mt_insuficiente_ai    AS est_mat_insuf_ai,

  // Contexto estadual — PNAD
  st.negro_pnad_t_analf25m      AS est_analf_negro,
  st.branco_pnad_t_analf25m     AS est_analf_branco,
  st.negro_pnad_t_atraso_fund   AS est_atraso_negro,
  st.homem_pnad_t_analf25m      AS est_analf_homem,
  st.mulher_pnad_t_analf25m     AS est_analf_mulher,

  // Targets
  CASE WHEN total_dias > 0 AND toFloat(total_faltas) / total_dias > 0.25 THEN 1 ELSE 0 END AS target_evasao,
  CASE WHEN nota_final IS NOT NULL AND nota_final < 5.0 THEN 1 ELSE 0 END AS target_reprovacao,
  nota_final AS target_nota
```

### 3.2 Query de Extração — EF2 (adicional para notas por matéria)

```cypher
// Complementa a query EF1 com pivot de notas por disciplina
MATCH (sch:School)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
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
          THEN sd.grade_1 / 10.0 ELSE sd.grade_1 END AS nota_g1_norm

RETURN student_id,
       count(disciplina)                                         AS n_disciplinas,
       round(avg(nota_final_norm), 4)                           AS nota_media_geral,
       round(stDev(nota_final_norm), 4)                         AS nota_dispersao,
       count(CASE WHEN nota_final_norm < 5.0 THEN 1 END)        AS n_disc_abaixo5,
       round(avg(nota_final_norm) - avg(nota_g1_norm), 4)       AS trajetoria_media,
       // Notas por matéria (pivot manual via aggregation)
       round(avg(CASE WHEN disciplina =~ '(?i).*MATEM.*' THEN nota_final_norm END), 4) AS nota_mat,
       round(avg(CASE WHEN disciplina =~ '(?i).*PORTUGU.*' THEN nota_final_norm END), 4) AS nota_lp,
       round(avg(CASE WHEN disciplina =~ '(?i).*CIÊN.*' THEN nota_final_norm END), 4)   AS nota_ciencias,
       round(avg(CASE WHEN disciplina =~ '(?i).*HISTÓR.*' THEN nota_final_norm END), 4) AS nota_historia,
       round(avg(CASE WHEN disciplina =~ '(?i).*GEOGRAF.*' THEN nota_final_norm END), 4) AS nota_geo
```

---

## 4. Modelos ML

### 4.1 Modelo A — Predição de Evasão (`XGBoostClassifier`)

**Input:** Feature set EF1 ou EF2 (51 features)
**Target:** `target_evasao` (0/1)
**Biblioteca:** `xgboost >= 2.0.0`

**Split temporal:** Treino em anos anteriores, teste no ano mais recente (`cr.year`). Não usar split aleatório — seria data leakage.

**Hiperparâmetros base:**
```python
params = {
    "n_estimators": 500,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "scale_pos_weight": None,  # calcular: count(0)/count(1) para imbalance
    "eval_metric": "aucpr",    # AUC-PR melhor que AUC-ROC para classe desbalanceada
    "early_stopping_rounds": 50,
}
```

**Métricas alvo:** AUROC ≥ 0.82, Recall ≥ 0.75, F1 ≥ 0.70

**Tratamento de missing:**
- Demográficas nulas: fill com moda
- Notas nulas: fill com -1 (indica "sem nota" é informação, não ruído)
- Faltas nulas + `tem_diario = 0`: fill faltas com -1
- IBGE municipal nulo: fill com média estadual (já calculado no Cypher via UF fallback)

---

### 4.2 Modelo B — Regressão de Nota (`GradientBoostingRegressor`)

**Input:** Feature set EF2 com disciplinas
**Target:** `target_nota` (0.0–10.0)
**Biblioteca:** `sklearn >= 1.4.0`

**Somente EF2** — EF1 tem nota global (útil para classificação de reprovação, mas regressão por matéria só faz sentido com `discipline_name <> ''`).

**Métricas alvo:** RMSE ≤ 1.5, R² ≥ 0.60

---

### 4.3 Modelo C — Clustering de Perfis (`KMeans + DBSCAN`)

**Input:** Features numéricas normalizadas (excluindo IDs e targets)
**Output:** `risk_cluster` (label inteiro) → escrever de volta no Neo4j como `stu.risk_cluster`

**Método:**
1. Normalizar features com `StandardScaler`
2. Reduzir dimensionalidade com `PCA(n_components=0.95)` (mantém 95% da variância)
3. Determinar k com Elbow + Silhouette Score
4. Rodar KMeans com k ótimo
5. Interpretar clusters por perfil demográfico + SHAP médio por cluster

**Métrica alvo:** Silhouette Score ≥ 0.35

**Escrever resultado no Neo4j:**
```cypher
UNWIND $cluster_data AS row
MATCH (stu:Student {id: row.student_id})
SET stu.risk_cluster = row.cluster,
    stu.risk_score    = row.risk_score
```

---

### 4.4 SHAP — Explicabilidade

```python
import shap

# Global: feature importance across all predictions
explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_test)
shap.summary_plot(shap_values, X_test, feature_names=feature_names)

# Local: por aluno individual
shap.waterfall_plot(shap.Explanation(
    values=shap_values[student_idx],
    base_values=explainer.expected_value,
    data=X_test.iloc[student_idx],
    feature_names=feature_names
))
```

**Critério:** Top-5 features devem explicar ≥ 65% do SHAP global.

---

## 5. Embeddings para RAG (Neo4j Vector Index)

### 5.1 O que gerar embedding

**`Student` embedding (512d):**
- Demográficas normalizadas + saúde + frequência + notas + contexto IBGE
- Modelo: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (local, PT-BR nativo)
- Texto serializado: `"Aluno: gênero {g}, etnia {e}, bolsa_familia {bf}, zona {z}, nota {n}, faltas {f}%, condições saúde {s}"`

**`School` embedding (512d):**
- Score de saúde + médias agregadas + contexto IBGE municipal/estadual
- Texto serializado: `"Escola: UF {uf}, IDEB {ideb}, abandono {abd}%, notas médias {n}, faltas {f}%"`

### 5.2 Cypher para criar Vector Indexes

```cypher
CREATE VECTOR INDEX student_embedding IF NOT EXISTS
FOR (s:Student) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 512, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX school_embedding IF NOT EXISTS
FOR (s:School) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 512, `vector.similarity_function`: 'cosine'}};
```

### 5.3 Busca de similares

```cypher
// Top-5 alunos similares para RAG
CALL db.index.vector.queryNodes('student_embedding', 5, $query_embedding)
YIELD node AS similar_stu, score
WHERE similar_stu.id <> $student_id
RETURN similar_stu.id, similar_stu.risk_cluster, score
ORDER BY score DESC
```

---

## 6. Análise Cypher Complementar (já implementada)

As queries analíticas abaixo já existem e servem como **validação manual** dos modelos ML e como **contexto para o RAG**:

| Query | Arquivo | Uso |
|---|---|---|
| Risco de evasão por turma/matéria | `Q_RISCO_EVASAO_EF2.md` | Validação do modelo de evasão por turma |
| Score de saúde da escola | `Q_SAUDE_ESCOLA_E_PROXIMIDADE.md` | Benchmark para o score ML da escola |
| Proximidade de alunos | `Q_SAUDE_ESCOLA_E_PROXIMIDADE.md` | Grupos "à beira" = feature `n_disciplinas_abaixo5` |
| Matrix completa Q1–Q15 | `CYPHER-QUERY-MATRIX-ML.md` | Contexto para RAG e SHAP interpretation |

---

## 7. MLOps Pipeline

### 7.1 Fluxo de Retreinamento

```
Trigger Airflow (semanal)
  → extract_features_from_neo4j    (Cypher da Seção 3 → Parquet)
  → validate_features               (Great Expectations — checa nulos em target_evasao)
  → train_model                     (XGBoost + scikit-learn pipeline + MLflow run)
  → evaluate_model                  (AUROC, F1, Recall, SHAP plots)
  → compare_with_champion           (MLflow API comparison)
  → promote_if_better               (AUROC novo > AUROC champion + 0.01)
  → update_neo4j_scores             (escreve stu.risk_score + stu.risk_cluster)
```

### 7.2 Drift Detection

- **Data drift:** distribuição de `taxa_ausencia` e `nota_final_norm` vs período anterior
- **Concept drift:** distribuição de `target_evasao` previsto vs observado
- **Ferramenta:** Evidently AI (open-source)
- **Trigger:** re-treino se PSI > 0.2 em qualquer feature crítica

### 7.3 MLflow

```
Experiments:
  school-dropout-prediction/     ← Modelo A
  grade-regression/              ← Modelo B
  student-clustering/            ← Modelo C

Por run:
  params: hiperparâmetros
  metrics: auroc, f1, recall, rmse, silhouette
  artifacts: model.pkl, shap_summary.png, feature_importance.csv
  tags: {champion: true/false, segment: EF1/EF2}
```

---

## 8. API FastAPI

### 8.1 Endpoints

| Endpoint | Input | Output |
|---|---|---|
| `POST /predict/dropout/{student_id}` | student_id | `{evasao_prob, risk_level, top_5_factors}` |
| `POST /predict/grade/{student_id}` | student_id | `{nota_prevista, por_disciplina}` |
| `GET /report/school/{school_id}` | school_id | `{score_saude, clusters, top_risk_turmas}` |
| `POST /ask/student` | `{question, student_id}` | RAG response com contexto full-graph |
| `POST /ask/school` | `{question, school_id}` | RAG response com contexto escola + IBGE |

### 8.2 RAG — Contexto por Aluno

Quando um gestor pergunta sobre um aluno específico, o contexto montado inclui:

```python
context = {
    "aluno": {
        # Nó Student + Health + StudentDiscipline + StudentClass
        # Derivado da query da Seção 3.1
    },
    "escola": {
        # Score de saúde da escola (Q_SAUDE_ESCOLA)
        # Turmas de risco (Q_RISCO_EVASAO)
    },
    "similares": [
        # Top-5 via vector search (Seção 5.3)
        # O que aconteceu com eles? Evadiram? Melhoraram?
    ],
    "contexto_ibge": {
        # Municipality + State properties (Seção 1.1)
    }
}
```

---

## 9. Checklist de Implementação

### Phase 0 — Feature Engineering
- [ ] `src/ml/features/student_features.py` — implementa queries da Seção 3 → Pandas DataFrame
- [ ] `src/ml/features/school_features.py` — agrega features por escola
- [ ] Testar: `python -m pytest tests/ml/test_features.py` (zero nulos em colunas críticas)
- [ ] Verificar: `has_deficiency` usa `STARTS WITH 'Possui'` (não `= True`)
- [ ] Verificar: saúde usa `h.malnutrition` (não `h.malnutrition_desease`)
- [ ] Verificar: `tem_diario = 0` quando StudentClass não existe (OPTIONAL MATCH)
- [ ] Verificar: normalização de nota — `IF > 10 THEN /10.0`
- [ ] Verificar: filtros grade_level usam valores exatos da Seção 1.1

### Phase 1 — Modelos ML
- [ ] `src/ml/models/dropout_classifier.py` — XGBoost com split temporal por `cr.year`
- [ ] `src/ml/models/grade_regressor.py` — GBM para EF2 por disciplina
- [ ] `src/ml/models/risk_clusterer.py` — KMeans + escrita de `stu.risk_cluster` no Neo4j
- [ ] `src/ml/evaluation/explainability.py` — SHAP global + waterfall por aluno
- [ ] MLflow run logado com métricas e artefatos

### Phase 2 — Embeddings
- [ ] `src/embeddings/student_embedder.py` — sentence-transformers local
- [ ] `src/embeddings/neo4j_vector_writer.py` — escreve `stu.embedding` no Neo4j
- [ ] `CREATE VECTOR INDEX` executado com status ONLINE
- [ ] Testar: `db.index.vector.queryNodes` retorna top-5 com similarity ≥ 0.80

### Phase 3 — MLOps
- [ ] MLflow server rodando em `localhost:5001`
- [ ] `dags/dag__ml_feature_engineering.py` — Cypher → Parquet
- [ ] `dags/dag__ml_retrain.py` — pipeline completo com 6 tasks
- [ ] `src/ml/mlops/drift_detector.py` — Evidently AI
- [ ] `src/ml/mlops/champion_challenger.py` — promoção automática se AUROC melhora > 0.01

### Phase 4 — RAG + API
- [ ] `src/rag/retriever.py` — `get_student_context()` + `find_similar_students()`
- [ ] `src/rag/context_builder.py` — monta prompt com dados + IBGE + similares
- [ ] `src/api/main.py` — FastAPI endpoints da Seção 8.1
- [ ] Testar: POST `/predict/dropout/{id}` retorna JSON em < 1s
- [ ] Testar: POST `/ask/student` retorna resposta em < 15s

---

## 10. Tech Stack (apenas confirmados e necessários)

| Camada | Ferramenta | Notas |
|---|---|---|
| Graph DB | Neo4j 5.11+ | já implantado |
| Orquestração | Apache Airflow | já implantado |
| Feature extraction | Cypher → Pandas | queries da Seção 3 |
| ML | scikit-learn + XGBoost | Modelos A, B, C |
| Explicabilidade | SHAP | global + local por aluno |
| Clustering | scikit-learn KMeans/DBSCAN | + PCA preprocessing |
| Embeddings | `sentence-transformers` (local) | `paraphrase-multilingual-MiniLM-L12-v2` |
| MLOps | MLflow (self-hosted) | experiment tracking + model registry |
| Drift | Evidently AI (open-source) | PSI por feature |
| RAG LLM | Gemini Flash (free tier) ou Ollama local | sem OpenAI por padrão |
| RAG Orchestration | LangChain + langchain-neo4j | Cypher + vector queries |
| Serving | FastAPI | endpoints da Seção 8.1 |

**Dependências:**
```bash
scikit-learn>=1.4.0
xgboost>=2.0.0
shap>=0.44.0
lifelines>=0.27.0          # opcional: análise de sobrevivência
mlflow>=2.12.0
evidently>=0.4.0
langchain>=0.2.0
langchain-neo4j>=0.1.0
sentence-transformers>=2.7.0
fastapi>=0.110.0
neo4j>=5.0.0               # driver Python
pandas>=2.0.0
```
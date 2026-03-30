# Neo4j Schema — Dados Educacionais

Referência definitiva de schema Neo4j para análises educacionais, incluindo nós, propriedades, relacionamentos, filtros por segmento, padrões de agregação, nuances críticas de dados e templates de query completos.

---

## 1. Visão Geral do Grafo

```
State
  └─[:BELONGS_TO_STATE]─ Municipality
       └─[:LOCATED_IN_MUNICIPALITY]─ SchoolGeograph
            └─[:HAS_GEOGRAPHY]─ School
                 └─[:ENROLLED_AT_SCHOOL]─ Student
                      ├─[:ENROLLED_IN]──────────────── Classroom
                      ├─[:HAS_HEALTH]────────────────── Health           (OPCIONAL)
                      ├─[:HAS_DISCIPLINE]────────────── StudentDiscipline (OPCIONAL)
                      ├─[:HAS_GRADES]───────────────── Grades            (Embedding layer)
                      └──────────────── StudentClass ─[:ATTENDED]────────(OPCIONAL)
```

**Regra de ouro:** Todo caminho de `Student` até dados geográficos sempre passa por `School → SchoolGeograph → Municipality → State`. Nunca salte etapas.

---

## 2. Nós e Propriedades

### 2.1 Classroom

Representa uma turma. A combinação `(grade_level, stage)` é o único jeito seguro de identificar o segmento de ensino.

#### Propriedades confirmadas

| Propriedade | Tipo | Descrição |
|---|---|---|
| `grade_level` | string | Série/ano da turma. **Nunca contém a palavra "FUNDAMENTAL"**. Veja tabela completa abaixo. |
| `stage` | string | Modalidade de ensino. Discriminador obrigatório quando `grade_level` é ambíguo. |
| `name` | string | Nome livre da turma (ex: "7º ANO B TARDE") |
| `year` | integer | Ano letivo (ex: 2024) |
| `status` | string | Status atual da turma |

#### Distribuição real de `grade_level` × `stage` (10.219 turmas)

| grade_level | stage | Contagem | Segmento |
|---|---|---|---|
| `NO 1* ANO` | `ENSINO FUNDAMENTAL` | 519 | ✅ EF1 |
| `NO 2* ANO` | `ENSINO FUNDAMENTAL` | 464 | ✅ EF1 |
| `NO 3* ANO` | `ENSINO FUNDAMENTAL` | 473 | ✅ EF1 |
| `NO 4* ANO` | `ENSINO FUNDAMENTAL` | 472 | ✅ EF1 |
| `NO 5* ANO` | `ENSINO FUNDAMENTAL` | 463 | ✅ EF1 |
| `NO 6* ANO` | `ENSINO FUNDAMENTAL` | 487 | ✅ EF2 |
| `NO 7* ANO` | `ENSINO FUNDAMENTAL` | 436 | ✅ EF2 |
| `NO 8* ANO` | `ENSINO FUNDAMENTAL` | 376 | ✅ EF2 |
| `NO 9* ANO` | `ENSINO FUNDAMENTAL` | 338 | ✅ EF2 |
| `NA PRÉ-ESCOLA` | `EDUCAÇÃO INFANTIL` | 1.567 | ✅ EI |
| `NA CRECHE` | `EDUCAÇÃO INFANTIL` | 1.321 | ✅ EI |
| `NA EDUCAÇÃO INFANTIL` | `EDUCAÇÃO INFANTIL` | 219 | ✅ EI |
| `NA ____________________` | `ENSINO FUNDAMENTAL` | 1.493 | ⚠️ EF (sem série) |
| `NA ____________________` | `EDUCAÇÃO DE JOVENS E ADULTOS` | 987 | ⚠️ EJA |
| `NA ____________________` | `MULTIETAPA` | 207 | ⚠️ Multietapa |
| `NA ____________________` | `ENSINO MÉDIO` | 61 | ✅ EM (via stage) |
| `NA ____________________` | `EDUCAÇÃO INFANTIL` | 23 | ⚠️ EI (sem nível) |
| `NA ____________________` | `EDUCAÇÃO PROFISSIONAL` | 10 | ⚠️ Profissional |
| `NA 1* SÉRIE` | `ENSINO MÉDIO` | 19 | ⚠️ Ambíguo (ver nota) |
| `NA 2* SÉRIE` | `ENSINO MÉDIO` | 32 | ⚠️ Ambíguo |
| `NA 3* SÉRIE` | `ENSINO MÉDIO` | 24 | ⚠️ Ambíguo |
| `NA 1* SÉRIE` | `ENSINO FUNDAMENTAL` | 5 | ⚠️ Legado EF1 |
| `NA 4* SÉRIE` | `ENSINO FUNDAMENTAL` | 5 | ⚠️ Legado EF1 |
| `TURMA A/B/C/...` | variado | ~191 | ⚠️ Sem ano/série real |
| Nomes livres de turma | `NA ____________________` | ~30 | ⚠️ Dado sujo |
| `X° MULTISSERIADAS` | variado | 4 | ⚠️ Turmas mistas |

> **27,2% das turmas (2.781)** têm `grade_level = 'NA ____________________'` e precisam do `stage` para ser categorizadas. **28,8% do total** são sujos, ambíguos ou não categorizáveis com segurança sem lógica adicional.

#### Valores de `stage` confirmados

```
ENSINO FUNDAMENTAL
ENSINO MÉDIO
EDUCAÇÃO INFANTIL
EDUCAÇÃO DE JOVENS E ADULTOS
MULTIETAPA
EDUCAÇÃO PROFISSIONAL
ENSINO SUPERIOR
```

#### ⚠️ Nuance: `grade_level` invertido

Em alguns registros sujos, os campos ficam trocados — o nome da turma vai para `grade_level` e o `stage` fica em branco ou recebe o valor que deveria ser `grade_level`. Exemplos reais:

```
grade_level='TURMA A'     stage='NO 1* ANO'     ← campos invertidos
grade_level='TURMA A'     stage='NA PRÉ-ESCOLA' ← campos invertidos
grade_level='VESPERTINO'  stage='NO 6* ANO'     ← turno no lugar da série
grade_level='MATUTINO'    stage='NO 8* ANO'     ← turno no lugar da série
```

**Como tratar:** Sempre filtre pelo padrão canônico (`IN [lista]` ou regex) em ambos os campos. Se nenhum padrão bater, descarte a turma da análise.

---

### 2.2 Student

| Propriedade | Tipo | Valores / Nuances |
|---|---|---|
| `gender` | string | Começa com `F` (Feminino) ou `M` (Masculino). Verificar com `=~ '(?i)^[FM].*'`. Pode ter variações de capitalização. |
| `ethnicity` | string | `Branca`, `Parda`, `Preta`, `Amarela`, `Indígena`, `Não Declarada`, `''` (vazio). Nunca assuma preenchimento. |
| `deficiency` | **string** | **Não é boolean.** Valores: `'Não Possui'` ou `'Possui: Deficiência Intelectual'`, `'Possui: Deficiência Visual'`, etc. Verificar com `STARTS WITH 'Possui'`. |
| `bolsa_familia` | boolean | `true`/`false`. Usar `coalesce(stu.bolsa_familia, false)`. |
| `residence_zone` | string | Zona rural/urbana. Pode ser nulo — usar `coalesce(stu.residence_zone, 'Não Informado')`. |
| `embedding` | float[384] | Vetor denso 384-dimensional (L2-normalizado), gerado pela embedding layer (MiniLM). Codifica: gênero, etnia, zona, Bolsa Família, deficiência, frequência, notas, saúde, contexto IBGE e cluster de risco. |
| `embedding_hash` | string | Hash MD5 da representação textual — usado para detecção incremental de mudanças. |
| `risk_cluster` | integer | Cluster (0–7) do KMeans de risco. Agrupamento de alunos com perfis similares de vulnerabilidade. |
| `risk_score` | float | Taxa de evasão histórica do cluster (0–100). **Não é score individual**, é a taxa de dropout do grupo. |

#### Filtros corretos:

```cypher
// PCD
CASE WHEN coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui' THEN 1 ELSE 0 END

// Gênero feminino
stu.gender =~ '(?i)^F.*'

// Bolsa Família (via list comprehension — mais eficiente que UNWIND para contagem)
size([s IN ListaAlunos WHERE coalesce(s.bolsa_familia, false) = true]) AS N_BF
size([s IN ListaAlunos WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui']) AS N_PCD
```

---

### 2.3 Health

> **⚠️ OPCIONAL:** nem todo aluno tem nó `Health`. O `OPTIONAL MATCH` é obrigatório. Ausência do nó ≠ ausência de doença — significa dado não registrado.

**Relacionamento:** `(stu)-[:HAS_HEALTH]->(h:Health)`

| Propriedade | Tipo | ⚠️ Nome correto |
|---|---|---|
| `malnutrition` | boolean | **NÃO** `malnutrition_desease` |
| `diabetes` | boolean | **NÃO** `diabetes_desease` |
| `hypertension` | boolean | |
| `celiac` | boolean | |
| `obesity` | boolean | |
| `iron_deficiency_anemia` | boolean | nome composto, **sem** `_desease` |
| `sickle_cell_anemia` | boolean | nome composto, **sem** `_desease` |

**Acesso correto:**

```cypher
OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
WITH stu,
     CASE WHEN h IS NOT NULL THEN 1 ELSE 0 END       AS has_health_record,
     coalesce(h.malnutrition, false)                  AS has_malnutrition,
     coalesce(h.diabetes, false)                      AS has_diabetes,
     coalesce(h.hypertension, false)                  AS has_hypertension,
     coalesce(h.obesity, false)                       AS has_obesity,
     coalesce(h.iron_deficiency_anemia, false)
       OR coalesce(h.sickle_cell_anemia, false)       AS has_anemia,
     (CASE WHEN coalesce(h.malnutrition, false) THEN 1 ELSE 0 END
    + CASE WHEN coalesce(h.diabetes, false) THEN 1 ELSE 0 END
    + CASE WHEN coalesce(h.hypertension, false) THEN 1 ELSE 0 END
    + CASE WHEN coalesce(h.obesity, false) THEN 1 ELSE 0 END
    + CASE WHEN coalesce(h.iron_deficiency_anemia, false)
            OR coalesce(h.sickle_cell_anemia, false) THEN 1 ELSE 0 END
     )                                                AS n_health_conditions
```

---

### 2.4 StudentDiscipline

> **⚠️ OPCIONAL:** nem toda escola registra notas no sistema. O `OPTIONAL MATCH` é obrigatório. Ausência de registros ≠ notas zero — é dado ausente.

**Relacionamento:** `(stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)`

| Propriedade | Tipo | Nuances |
|---|---|---|
| `discipline_name` | string | **`''` (vazio) = nota global EF1 (um registro por aluno). Preenchido = nota por matéria EF2 (N registros por aluno).** |
| `final_mean` | float | **Pode estar em escala 0–100 (legado) ou 0–10.** Sempre normalizar. |
| `grade_1` | float | Nota do 1º bimestre. Mesma normalização. |
| `grade_2` | float | Nota do 2º bimestre. |
| `grade_3` | float | Nota do 3º bimestre. |
| `grade_4` | float | Nota do 4º bimestre. |

#### Normalização obrigatória de notas

```cypher
// Normalização universal — aplicar em TODOS os usos de nota
CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
     THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
     ELSE coalesce(sd.final_mean, sd.grade_1)
END AS nota_norm

// Para grade_1 isolado
CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
     THEN sd.grade_1 / 10.0
     ELSE sd.grade_1
END AS nota_g1_norm
```

#### EF1 vs EF2 — distinção fundamental

```cypher
// EF1 — nota global (discipline_name VAZIO)
// Um registro por aluno. Use para análise geral de desempenho.
MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') = ''

// EF2 — nota por matéria (discipline_name PREENCHIDO)
// N registros por aluno. Agregar por discipline_name.
MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE coalesce(sd.discipline_name, '') <> ''
```

#### Trajetória de desempenho

```cypher
// Detecta se aluno melhorou ou piorou no período
WITH nota_final_norm - nota_g1_norm AS trajetoria
// Positivo = melhorou, negativo = piorou, null = sem dado inicial
```

---

### 2.5 StudentClass

> **⚠️ OPCIONAL — Cobertura parcial:** Só existe para escolas que usam **diário eletrônico**. Se a escola não usa, **nenhum** `StudentClass` existe para nenhum de seus alunos. Ausência completa = escola sem diário, **não** escola sem faltas.

**Relacionamento:** `(sc:StudentClass)-[:ATTENDED]->(stu:Student)`

> **Atenção na direção:** a seta vai de `StudentClass` para `Student`, não o contrário.

| Propriedade | Tipo | Nuances |
|---|---|---|
| `total_faults_per_day` | integer | Total de dias de falta do aluno. |
| `scheduled_student_class_days` | integer | Dias previstos. **Pode ser nulo** — usar `coalesce(val, 200)`. |

#### Cálculo correto de taxa de ausência

```cypher
OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)

WITH stu,
     CASE WHEN sc IS NOT NULL THEN 1 ELSE 0 END        AS tem_diario,
     // Não inferir 0 quando sc é nulo — é dado ausente
     CASE WHEN sc IS NOT NULL
          THEN toFloat(sc.total_faults_per_day)
               / coalesce(sc.scheduled_student_class_days, 200)
          ELSE null
     END AS taxa_ausencia,
     coalesce(sc.total_faults_per_day, 0)               AS total_faltas
```

#### Detectar escolas sem diário (agregado)

```cypher
// Na agregação por turma ou escola:
count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END)  AS n_alunos_com_diario,
count(DISTINCT stu)                                    AS n_alunos_total,
CASE WHEN count(CASE WHEN sc IS NOT NULL THEN 1 END) = 0
     THEN 'Sem Diário Eletrônico'
     ELSE toString(round(
            toFloat(sum(coalesce(sc.total_faults_per_day, 0)))
            / sum(coalesce(sc.scheduled_student_class_days, 200)) * 100, 2
          )) + '%'
END AS taxa_ausencia_display
```

---

### 2.6 School

| Propriedade | Tipo | Descrição |
|---|---|---|
| `name` | string | Nome da escola |
| `id` | string | Identificador único |
| `situation` | string | Situação (ativa, inativa, etc.) |
| `embedding` | float[384] | Vetor denso 384-dimensional (L2-normalizado), gerado pela embedding layer. Codifica: localização geográfica, saúde escolar, taxa de ausência média, média de notas, % Bolsa Família, % PCD, referências IBGE, IDEB estadual, abandono estadual, qualidade dos dados. |
| `embedding_hash` | string | Hash MD5 da representação textual da escola. |
| `score_saude` | float | Score agregado de saúde (0–100), calculado a partir da saúde dos alunos. |
| `nivel_saude` | string | Nível de saúde categorizado (ex: "Moderado", "Crítico", "Adequado"). |

---

### 2.7 SchoolGeograph

Nó intermediário entre `School` e `Municipality`. Contém dados de localização.

| Propriedade | Tipo | Descrição |
|---|---|---|
| `lat` | float | Latitude |
| `lon` | float | Longitude |
| `cep` | string | CEP da escola |
| `city` | string | Cidade |
| `state` | string | UF sigla |

---

### 2.8 Municipality

> **⚠️ Esparsidade:** Muitos municípios têm campos nulos no Atlas IBGE. Sempre compute um fallback de média estadual antes de usar dados municipais.

**Caminho completo:** `School -[:HAS_GEOGRAPHY]-> SchoolGeograph -[:LOCATED_IN_MUNICIPALITY]-> Municipality`

#### Propriedades confirmadas (Atlas IBGE)

| Propriedade | O que mede | Unidade |
|---|---|---|
| `atl_freq_liq_fund` | % crianças em idade correta frequentando o fundamental | % |
| `atl_atraso_2_fund` | % alunos com 2+ anos de atraso escolar | % |
| `atl_t_analf25m` | % analfabetismo adulto (+25 anos) | % |
| `atl_expectativa_estudo_18` | Anos esperados de estudo ao chegar nos 18 | anos |
| `atl_branco_mat_pub_fund` | % brancos matriculados em escola pública fundamental | % |
| `atl_negro_mat_pub_fund` | % negros matriculados em escola pública fundamental | % |
| `atl_branco_internet_fund` | % escolas fund. com internet para alunos brancos | % |
| `atl_negro_internet_fund` | % escolas fund. com internet para alunos negros | % |
| `atl_branco_lab_info_fund` | % escolas fund. com lab de informática para brancos | % |
| `atl_negro_lab_info_fund` | % escolas fund. com lab de informática para negros | % |

#### Fallback de UF obrigatório

```cypher
// Executar UMA VEZ antes das queries principais
// Coloca no WITH para uso posterior
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS UF_Media_Freq
}

// Depois usar sempre:
coalesce(m.atl_freq_liq_fund, UF_Media_Freq) AS Freq_Ref,
CASE WHEN m.atl_freq_liq_fund IS NOT NULL
     THEN 'Municipal' ELSE 'Media_UF_Proxy'
END AS Fonte_Freq
```

---

### 2.9 State

> Analfabetismo racial e por gênero existe **apenas em State**, nunca em Municipality.

**Caminho:** `Municipality -[:BELONGS_TO_STATE]-> State`

#### PNAD por raça (prefixo `branco_` / `negro_`)

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
| `branco_pnad_ppob` | % em pobreza — brancos |
| `negro_pnad_ppob` | % em pobreza — negros |
| `branco_pnad_gini` | Gini — brancos |
| `negro_pnad_gini` | Gini — negros |
| `branco_pnad_t_flbas` | % frequência educação básica — brancos |
| `negro_pnad_t_flbas` | % frequência educação básica — negros |
| `branco_pnad_t_flfund` | % frequência fundamental — brancos |
| `negro_pnad_t_flfund` | % frequência fundamental — negros |
| `branco_pnad_t_flmed` | % frequência ensino médio — brancos |
| `negro_pnad_t_flmed` | % frequência ensino médio — negros |
| `branco_pnad_t_med18a20` | % com médio completo (18–20 anos) — brancos |
| `negro_pnad_t_med18a20` | % com médio completo (18–20 anos) — negros |
| `branco_pnad_t_super25m` | % com superior (+25 anos) — brancos |
| `negro_pnad_t_super25m` | % com superior (+25 anos) — negros |

#### PNAD por gênero (prefixo `homem_` / `mulher_`)

| Propriedade | O que mede |
|---|---|
| `homem_pnad_t_analf25m` / `mulher_pnad_t_analf25m` | % analfabetismo adulto por gênero |
| `homem_pnad_t_analf15m` / `mulher_pnad_t_analf15m` | % analfabetismo +15 por gênero |
| `homem_pnad_idhm_e` / `mulher_pnad_idhm_e` | IDHM educação por gênero |
| `homem_pnad_rdpc` / `mulher_pnad_rdpc` | Renda per capita por gênero |
| `homem_pnad_anosest` / `mulher_pnad_anosest` | Anos de estudo médio por gênero |
| `homem_pnad_t_flfund` / `mulher_pnad_t_flfund` | % frequência fundamental por gênero |
| `homem_pnad_t_flmed` / `mulher_pnad_t_flmed` | % frequência médio por gênero |
| `homem_pnad_t_flsuper` / `mulher_pnad_t_flsuper` | % frequência superior por gênero |
| `homem_pnad_t_freq6a14` / `mulher_pnad_t_freq6a14` | % frequência escolar 6–14 anos |
| `homem_pnad_t_fund18m` / `mulher_pnad_t_fund18m` | % fundamental completo (+18 anos) |
| `homem_pnad_t_med18a20` / `mulher_pnad_t_med18a20` | % médio completo (18–20 anos) |
| `homem_pnad_t_super25m` / `mulher_pnad_t_super25m` | % superior (+25 anos) |
| `homem_pnad_idhm` / `mulher_pnad_idhm` | IDHM geral por gênero |
| `homem_pnad_idhm_ajustado` / `mulher_pnad_idhm_ajustado` | IDHM ajustado por gênero |

#### QEdu por segmento (sufixo `_ai` / `_af` / `_em`)

| Propriedade | O que mede |
|---|---|
| `qedu_ideb_ai` / `_af` / `_em` | IDEB por segmento (anos iniciais, finais, médio) |
| `qedu_aprendizado_ai` / `_af` / `_em` | Nota de aprendizado QEdu |
| `qedu_taxa_abandono` | Taxa de abandono escolar oficial |
| `qedu_taxa_reprovacao` | Taxa de reprovação |
| `qedu_taxa_aprovacao` | Taxa de aprovação |
| `qedu_fluxo_ai` / `_af` / `_em` | Fluxo escolar (0 = retenção total, 1 = fluxo perfeito) |
| `qedu_pct_fora_escola` | % crianças fora da escola |
| `qedu_permanencia` | Taxa de permanência |
| `qedu_total_matriculas` | Total de matrículas no estado |
| `qedu_distorcao_ef1` .. `qedu_distorcao_ef9` | Distorção idade-série por ano específico |
| `qedu_distorcao_ef_ai` / `qedu_distorcao_ef_af` | Distorção agregada EF |
| `qedu_distorcao_em_total` | Distorção agregada EM |
| `qedu_lp_adequado_ai` / `_af` / `_em` | % proficiência adequada em Língua Portuguesa |
| `qedu_mt_adequado_ai` / `_af` / `_em` | % proficiência adequada em Matemática |
| `qedu_lp_insuficiente_ai` / `_af` / `_em` | % proficiência insuficiente em LP |
| `qedu_mt_insuficiente_ai` / `_af` / `_em` | % proficiência insuficiente em Matemática |
| `qedu_lp_proficiente_ai` / `_af` / `_em` | % proficiência proficiente em LP |
| `qedu_mt_proficiente_ai` / `_af` / `_em` | % proficiência proficiente em Matemática |
| `qedu_nota_lp_ai` / `_af` / `_em` | Nota média estadual em LP |
| `qedu_nota_mt_ai` / `_af` / `_em` | Nota média estadual em Matemática |

#### Distorção por ano — lookup correto

```cypher
// Usar CASE para pegar a distorção do ano específico da turma
CASE cr.grade_level
     WHEN 'NO 1* ANO' THEN st.qedu_distorcao_ef1
     WHEN 'NO 2* ANO' THEN st.qedu_distorcao_ef2
     WHEN 'NO 3* ANO' THEN st.qedu_distorcao_ef3
     WHEN 'NO 4* ANO' THEN st.qedu_distorcao_ef4
     WHEN 'NO 5* ANO' THEN st.qedu_distorcao_ef5
     WHEN 'NO 6* ANO' THEN st.qedu_distorcao_ef6
     WHEN 'NO 7* ANO' THEN st.qedu_distorcao_ef7
     WHEN 'NO 8* ANO' THEN st.qedu_distorcao_ef8
     WHEN 'NO 9* ANO' THEN st.qedu_distorcao_ef9
     ELSE st.qedu_distorcao_ef_af  // fallback para série legada
END AS est_distorcao_serie
```

---

### 2.10 Grades

**RAG/Embedding Layer — Separado do StudentDiscipline**

Nó dedicado para a camada de embedding, contendo apenas as propriedades necessárias para geração de embeddings de estudantes. Cada aluno tem um nó `Grades` por disciplina.

**Relacionamento:** `(stu:Student)-[:HAS_GRADES]->(g:Grades)`

| Propriedade | Tipo | Descrição |
|---|---|---|
| `subject` | string | Nome da disciplina/matéria. Vazio (`""`) para nota global EF1. |
| `grade_g1` | float | Nota do primeiro semestre/bimestre. |
| `final_grade` | float | Nota final. |

**Diferença crítica de StudentDiscipline:**
- `StudentDiscipline` contém notas detalhadas com bimestres (G1, G2, G3, G4), nomes e contexto operacional
- `Grades` é uma simplificação para embeddings: apenas disciplina, G1 e nota final
- Ambos podem coexistir no grafo; `Grades` é a fonte para vetorização

---

## 3. Relacionamentos

```
(School)     <-[:ENROLLED_AT_SCHOOL]-    (Student)
(Student)     -[:ENROLLED_IN]->          (Classroom)
(Student)     -[:HAS_HEALTH]->           (Health)              OPCIONAL
(Student)     -[:HAS_DISCIPLINE]->       (StudentDiscipline)   OPCIONAL
(Student)     -[:HAS_GRADES]->           (Grades)              Embedding layer
(StudentClass)-[:ATTENDED]->             (Student)             OPCIONAL — direção inversa
(School)      -[:HAS_GEOGRAPHY]->        (SchoolGeograph)
(SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]-> (Municipality)
(Municipality)-[:BELONGS_TO_STATE]->     (State)
```

> **Direção do ATTENDED:** `StudentClass` aponta para `Student`, não o inverso. Erro frequente: `(stu)-[:ATTENDED]->(sc)` — isso retorna vazio.

```cypher
// ✅ Correto
OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)

// ❌ Errado — retorna nulo sempre
OPTIONAL MATCH (stu)-[:ATTENDED]->(sc)
```

---

## 4. Dados Ausentes — Cobertura Real

Esta seção documenta o que é garantido versus o que é opcional no grafo. Nunca assuma presença sem checar.

### 4.1 Diário Eletrônico (StudentClass)

| Cenário | O que existe no grafo | O que NÃO inferir |
|---|---|---|
| Escola com diário eletrônico ativo | `StudentClass` para cada aluno, com `total_faults_per_day` e `scheduled_student_class_days` | — |
| Escola sem diário eletrônico | **Zero nós `StudentClass`** para qualquer aluno dessa escola | Não inferir que os alunos têm 0 faltas |
| Escola com diário parcial | Alguns alunos têm `StudentClass`, outros não | Não inferir 0 faltas para os sem registro |

**Impacto em queries:** Uma média de faltas calculada sem o flag `tem_diario` vai mostrar 0% para escolas inteiras sem diário, fazendo-as parecer as melhores da rede quando na verdade são as sem dado.

```cypher
// Sempre expor o flag de cobertura junto com qualquer métrica de frequência
CASE WHEN count(CASE WHEN sc IS NOT NULL THEN 1 END) = 0
     THEN 'Sem Diário'
     ELSE toString(round(taxa_ausencia * 100, 1)) + '%'
END AS ausencia_display,
CASE WHEN count(CASE WHEN sc IS NOT NULL THEN 1 END) = 0
     THEN 0 ELSE 1
END AS Flag_Tem_Diario
```

### 4.2 Notas (StudentDiscipline)

| Cenário | O que existe no grafo |
|---|---|
| Escola que registra notas | `StudentDiscipline` por aluno, com `final_mean` e bimestres |
| Escola que não registra | **Zero nós `StudentDiscipline`** para seus alunos |
| Aluno com saúde mas sem nota | Tem `Health`, não tem `StudentDiscipline` — legítimo |
| EF1 com nota global | `discipline_name = ''`, um registro por aluno |
| EF2 com notas por matéria | `discipline_name != ''`, múltiplos registros por aluno |
| Nota só com grade_1 | `final_mean` nulo mas `grade_1` preenchido — usar `coalesce(final_mean, grade_1)` |

### 4.3 Saúde (Health)

Aluno sem nó `Health` = dado não registrado no sistema de saúde escolar, não ausência de condições de saúde. Tratar como dado ausente, não como "sem doenças".

### 4.4 IBGE Municipal (Municipality)

Muitos municípios pequenos têm campos nulos no Atlas IBGE. Proporção estimada de nulos varia por campo: `atl_freq_liq_fund` tem cobertura relativamente boa, mas campos de equidade racial e lab info podem ter 30–50% de nulos em regiões menos estudadas. **Sempre use fallback de média estadual.**

### 4.5 Embeddings (Student e School)

Cobertura: 96.0% dos estudantes (54.290 / 56.560) e 98.8% das escolas têm embeddings gerados. Estudantes/escolas sem embedding não têm Parquet data em qualquer ano — são dados criados via outras rotas de migração.

---

## 5. Filtros Canônicos por Segmento

Use estes filtros em todas as queries sem modificação. Eles cobrem todas as variações de dado confirmadas.

### EF1 — Fundamental Menor (anos 1–5)

```cypher
WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [1-5]\\* SÉRIE')
   OR cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
```

### EF2 — Fundamental Maior (anos 6–9)

```cypher
WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
   OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
```

### EI — Educação Infantil

```cypher
WHERE cr.grade_level IN ['NA PRÉ-ESCOLA','NA CRECHE','NA EDUCAÇÃO INFANTIL']
   OR cr.stage = 'EDUCAÇÃO INFANTIL'
```

### EM — Ensino Médio

```cypher
// stage é o ÚNICO discriminador confiável para EM
// 'NA 1* SÉRIE', 'NA 2* SÉRIE', 'NA 3* SÉRIE' aparecem tanto no EF quanto no EM
WHERE cr.stage = 'ENSINO MÉDIO'
```

### EF1 + EF2 — Fundamental Completo

```cypher
WHERE cr.stage = 'ENSINO FUNDAMENTAL'
  AND (
    cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO',
                        'NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
    OR cr.grade_level =~ 'NA [1-9]\\* SÉRIE'
  )
```

### EJA — Educação de Jovens e Adultos

```cypher
WHERE cr.stage = 'EDUCAÇÃO DE JOVENS E ADULTOS'
```

### ⚠️ Turmas ambíguas — o que NÃO usar sem stage

```cypher
// Nunca filtrar só por grade_level quando o valor é 'NA ____________________'
// Esse valor aparece em EF, EJA, EI, EM, PROFISSIONAL

// ❌ Inseguro — pode pegar EJA, EI, PROFISSIONAL juntos
WHERE cr.grade_level = 'NA ____________________'

// ✅ Seguro — par com stage obrigatório
WHERE cr.grade_level = 'NA ____________________'
  AND cr.stage = 'ENSINO FUNDAMENTAL'

// ✅ Seguro — descarta ambíguos e só usa os valores certos
WHERE cr.grade_level IN ['NO 1* ANO', ... , 'NO 9* ANO']

// Como descartar turmas sujas de forma segura:
WHERE NOT cr.grade_level STARTS WITH 'TURMA'
  AND NOT cr.grade_level = 'NA ____________________'
  OR (cr.grade_level = 'NA ____________________' AND cr.stage IN ['ENSINO FUNDAMENTAL','ENSINO MÉDIO'])
```

---

## 6. Padrões de Agregação — Performance

### 6.1 O problema: produto cartesiano em OPTIONAL MATCH encadeado

O anti-padrão mais comum que causa timeout em queries com múltiplas dimensões por aluno:

```cypher
// ❌ ANTI-PADRÃO — CAUSA TIMEOUT
// Problema: cada OPTIONAL MATCH multiplica as linhas do resultado intermediário
// Com 500 alunos, 3 faltas cada, 10 notas cada:
// 500 × 3 × 10 = 15.000 linhas antes de qualquer agregação

CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE <filtro>
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h)        // 500 → 500 linhas
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu) // 500 → 1.500 linhas (3 SC por stu)
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd)   // 1.500 → 15.000 linhas (10 sd por stu)
  RETURN sum(sc.total_faults_per_day), avg(sd.final_mean)  // agrega 15.000 linhas
}
```

### 6.2 O padrão correto: coletar → isolar → agregar

```cypher
// ✅ PADRÃO CORRETO — coletar lista primeiro, depois uma dimensão por CALL

// PASSO 1: coleta alunos dentro do filtro, sem abrir OPTIONAL MATCH
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
  RETURN collect(DISTINCT stu) AS ListaAlunos
}

// PASSO 2: dimensão FALTAS — isolada, O(N)
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    sum(coalesce(sc.total_faults_per_day, 0))               AS TotalFaltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))     AS TotalDias,
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END)   AS N_Com_Diario,
    count(DISTINCT CASE WHEN sc IS NOT NULL
                         AND toFloat(sc.total_faults_per_day)
                             / coalesce(sc.scheduled_student_class_days, 200) > 0.10
                        THEN stu END)                        AS N_Falta_Critica
}

// PASSO 3: dimensão NOTAS — isolada, O(N × K_notas)
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') <> ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota,
       sd.discipline_name AS Materia
  RETURN Materia,
         count(Nota)                                        AS N_Notas,
         round(avg(Nota), 2)                                AS Media,
         count(CASE WHEN Nota < 5.0 THEN 1 END)            AS N_Abaixo5
}

// PASSO 4: dimensão SAÚDE — isolada, O(N)
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_HEALTH]->(h:Health)
  RETURN count(CASE WHEN h IS NOT NULL THEN 1 END)         AS N_Com_Health,
         count(CASE WHEN coalesce(h.malnutrition, false)
                        THEN 1 END)                         AS N_Malnutrition
}

// PASSO 5: contagens simples — list comprehension, O(N) sem UNWIND extra
WITH *,
     size(ListaAlunos) AS N_Alunos,
     size([s IN ListaAlunos WHERE coalesce(s.bolsa_familia, false) = true]) AS N_BF,
     size([s IN ListaAlunos WHERE coalesce(s.deficiency,'Não') STARTS WITH 'Possui']) AS N_PCD
```

### 6.3 Complexidade comparada

| Abordagem | Working set com 500 alunos, 3 SC, 10 disciplinas | Risco |
|---|---|---|
| OPTIONAL MATCH encadeado | 500 × 3 × 10 = **15.000 linhas** antes de agregar | ⏱️ Timeout |
| CALL isolados | 500 + 500 + (500×10) = **6.500 linhas** no total | ✅ Rápido |
| List comprehension (BF, PCD) | **500** operações, sem UNWIND | ✅ Muito rápido |

### 6.4 Quando usar cada padrão

| Situação | Padrão recomendado |
|---|---|
| Contagem simples de propriedades de Student (BF, PCD, gênero) | List comprehension sobre a lista coletada |
| Agregação de uma única dimensão (só faltas OU só notas) | CALL único com UNWIND |
| Múltiplas dimensões (faltas + notas + saúde) | Um CALL por dimensão, todos independentes |
| Escolas com >200 alunos e 3+ dimensões | Obrigatório separar em CALLs |
| Pivot de notas por matéria | CALL com GROUP BY Materia usando avg(CASE WHEN ...) |

### 6.5 Regras de sintaxe Neo4j 5.x

```cypher
// ✅ Sintaxe correta para subquery com variável
CALL (sch) { MATCH (sch)... }
CALL (ListaAlunos) { UNWIND ListaAlunos AS stu ... }

// ❌ Sintaxe antiga — deprecated no 5.x
CALL { WITH sch MATCH (sch)... }

// ✅ Ordenação com nulls — usar CASE
ORDER BY CASE WHEN x IS NULL THEN 1 ELSE 0 END ASC, x DESC

// ❌ Não suportado
ORDER BY x DESC NULLS LAST

// ✅ Filtro mínimo de N antes de agregar (evita turmas com 1 aluno distorcendo médias)
WHERE size(ListaAlunos) >= 10

// ✅ Carregar todos os IBGEs no WITH antes de qualquer CALL
// Fazer o JOIN geográfico UMA VEZ, não repetir dentro de cada CALL
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
WITH sch, m, st,
     m.atl_freq_liq_fund AS MUNI_Freq_Liq,
     st.qedu_taxa_abandono AS EST_Abandono
     // ... todos os IBGEs aqui
// Agora os CALLs de aggregation não precisam re-resolver o caminho geográfico
```

### 6.6 Segmentação dentro do CALL (evitar contaminação EF1/EF2)

Escolas que atendem múltiplos segmentos podem contaminar análises se o filtro for aplicado fora do `CALL`:

```cypher
// ❌ ERRADO — alunos EF2 da mesma escola aparecem no resultado EF1
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  RETURN collect(DISTINCT stu) AS ListaAlunos  // lista misturada
}
// Filtro por grade aqui é tarde demais — a lista já está contaminada
WITH [s IN ListaAlunos WHERE ...] AS ListaEF1  // NÃO FUNCIONA: cr não está em escopo

// ✅ CORRETO — filtro e agrupamento DENTRO do CALL
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 1* ANO','NO 2* ANO','NO 3* ANO','NO 4* ANO','NO 5* ANO']
  RETURN collect(DISTINCT stu) AS ListaEF1
}
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
  RETURN collect(DISTINCT stu) AS ListaEF2
}
```

---

## 7. Nuances Críticas de Dados

### 7.1 `grade_level` nunca contém "FUNDAMENTAL"

A coluna vem do campo `serie` do CSV de origem. Qualquer filter como `WHERE cr.grade_level CONTAINS 'FUNDAMENTAL'` sempre retorna zero resultados. O segmento de ensino está em `cr.stage`, não em `cr.grade_level`.

### 7.2 `deficiency` é string, não boolean

```cypher
// ❌ Errado — sempre false
WHERE stu.deficiency = true

// ❌ Errado — pode pegar 'Não Possui' se começar diferente
WHERE stu.deficiency IS NOT NULL

// ✅ Correto
WHERE coalesce(stu.deficiency, 'Não') STARTS WITH 'Possui'
```

### 7.3 Notas em escala dupla

O sistema foi migrado de uma escala 0–100 para 0–10 em algum momento. Registros antigos podem ter `final_mean = 75.0` querendo dizer `7.5`. **Nunca calcule média diretamente sobre `final_mean` sem normalizar primeiro.** Uma turma com metade dos alunos em escala 100 e metade em escala 10 terá uma média de ~37 que não representa nada real.

```cypher
// Normalização universal — aplicar em TODOS os usos
CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
     THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
     ELSE coalesce(sd.final_mean, sd.grade_1)
END AS nota_norm
```

### 7.4 Escolas sem diário não são as "melhores"

Se uma análise ordena escolas por menor taxa de ausência e não separa as escolas sem diário, as escolas sem dado aparecem no topo (taxa = 0% ou nula). Isso é um falso positivo. Sempre:

1. Calcule `Flag_Tem_Diario` junto com qualquer métrica de frequência
2. Filtre ou destaque separadamente escolas sem cobertura
3. Exiba `'Sem Diário Eletrônico'` em vez de `'0%'` quando `N_Com_Diario = 0`

### 7.5 Contaminação de agregação sem DISTINCT

```cypher
// ❌ Conta o mesmo aluno N vezes se tem múltiplas disciplinas
count(stu) AS N_Alunos

// ✅ Conta alunos únicos
count(DISTINCT stu) AS N_Alunos
```

### 7.6 Turmas com grade_level = stage (campos invertidos)

Como visto na análise real, alguns registros têm `grade_level='TURMA A'` e `stage='NO 6* ANO'`. Isso não é pegado pelos filtros canônicos (que filtram `grade_level IN [...]`), então esses registros são naturalmente descartados. Não tente recuperá-los com lógica adicional — são dados sujos que devem ser ignorados nas análises.

### 7.7 Município nulo no caminho geográfico

Nem toda `School` tem `SchoolGeograph`, e nem toda `SchoolGeograph` tem `Municipality`. Use OPTIONAL MATCH para o caminho geográfico quando quiser incluir escolas sem IBGE:

```cypher
// ✅ Inclui escolas sem dado geográfico
OPTIONAL MATCH (sch)-[:HAS_GEOGRAPHY]->(sg:SchoolGeograph)
OPTIONAL MATCH (sg)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
OPTIONAL MATCH (m)-[:BELONGS_TO_STATE]->(st:State)

// ✅ Exclui escolas sem dado geográfico (mais restritivo, melhor para análises IBGE)
MATCH (sch)-[:HAS_GEOGRAPHY]->(sg:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)
```

### 7.8 Analfabetismo racial está em State, não Municipality

```cypher
// ❌ Não existe em Municipality
m.atl_branco_analf25m
m.atl_negro_analf25m

// ✅ Existe em State
st.branco_pnad_t_analf25m
st.negro_pnad_t_analf25m
```

### 7.9 Embeddings — incrementalidade e cobertura

Embeddings são regenerados incrementalmente: um hash MD5 de cada texto de estudante/escola é comparado com o hash armazenado. Se forem iguais, o embedding é pulado. Isso permite que o pipeline roda mensalmente sem recompilação de todos os 54k+ vetores.

A cobertura atual é 96% de alunos e 98.8% de escolas. Os 4% restantes não têm Parquet data em qualquer ano letivo — não devem aparecer em análises baseadas em features extraídas dos Parquets.

---

## 8. Propriedades que NÃO Existem

Lista consolidada de propriedades **que não existem** no schema e **não devem ser usadas**. Todas foram tentadas e retornam nulo ou erro.

### Municipality — NÃO EXISTE

```
m.atl_branco_analf25m          ← analfabetismo racial está em State
m.atl_negro_analf25m           ← analfabetismo racial está em State
m.atl_rural_freq_liq_fund      ← não existe; use atl_freq_liq_fund + filtro por stu.residence_zone
m.atl_urbano_freq_liq_fund     ← não existe
m.pnad_idhm                    ← IDHM não existe em Municipality
m.idh                          ← não existe
```

### State — NÃO EXISTE

```
st.pnad_idhm                   ← sem prefixo; use branco_pnad_idhm_e ou homem_pnad_idhm_e
st.idhm                        ← não existe como propriedade direta
st.idh                         ← não existe
```

### Health — NÃO EXISTE

```
h.malnutrition_desease         ← nome correto: h.malnutrition
h.diabetes_desease             ← nome correto: h.diabetes
h.obesity_desease              ← nome correto: h.obesity
h.celiac_desease               ← nome correto: h.celiac
```

### Student — NÃO EXISTE

```
stu.deficiency = true          ← deficiency é STRING, não boolean
stu.pcd                        ← não existe; use stu.deficiency STARTS WITH 'Possui'
```

### Classroom — NÃO EXISTE

```
cr.grade_level CONTAINS 'FUNDAMENTAL'  ← nunca verdadeiro; segmento está em cr.stage
cr.nivel                               ← não existe
```

---

## 9. Templates de Query

### 9.1 Template base — Escola com IBGE carregado

Use este bloco como cabeçalho de toda query que precisa de contexto IBGE.

```cypher
// ── ÂNCORA COM TODOS OS IBGEs (carregar uma vez, antes de qualquer CALL) ──
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)
      -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
      -[:BELONGS_TO_STATE]->(st:State)

// Fallback de UF para campos municipais nulos
CALL (st) {
  MATCH (m2:Municipality)-[:BELONGS_TO_STATE]->(st)
  WHERE m2.atl_freq_liq_fund IS NOT NULL AND m2.atl_freq_liq_fund > 0
  RETURN avg(m2.atl_freq_liq_fund) AS UF_Media_Freq
}

WITH sch, m, st,
     // ── Municipal ────────────────────────────────────────────────
     coalesce(m.atl_freq_liq_fund, UF_Media_Freq)    AS Freq_Ref,
     coalesce(m.atl_freq_liq_fund, null)              AS MUNI_Freq_Liq,
     coalesce(m.atl_atraso_2_fund, null)              AS MUNI_Atraso_2Anos,
     coalesce(m.atl_t_analf25m, null)                 AS MUNI_Analf_Adulto,
     coalesce(m.atl_expectativa_estudo_18, null)      AS MUNI_Expectativa_Estudo,

     // ── QEdu Estadual ────────────────────────────────────────────
     coalesce(st.qedu_ideb_ai, null)                  AS EST_IDEB_AI,
     coalesce(st.qedu_ideb_af, null)                  AS EST_IDEB_AF,
     coalesce(st.qedu_taxa_abandono, null)             AS EST_Abandono,
     coalesce(st.qedu_taxa_reprovacao, null)           AS EST_Reprovacao,
     coalesce(st.qedu_fluxo_af, null)                 AS EST_Fluxo_AF,
     coalesce(st.qedu_pct_fora_escola, null)          AS EST_Fora_Escola,
     coalesce(st.qedu_distorcao_ef_af, null)          AS EST_Distorcao_AF,
     coalesce(st.qedu_lp_insuficiente_af, null)       AS EST_LP_Insuf,
     coalesce(st.qedu_mt_insuficiente_af, null)       AS EST_Mat_Insuf,

     // ── PNAD Racial ──────────────────────────────────────────────
     coalesce(st.negro_pnad_t_analf25m, null)         AS EST_Analf_Negro,
     coalesce(st.branco_pnad_t_analf25m, null)        AS EST_Analf_Branco,
     coalesce(st.negro_pnad_t_atraso_fund, null)      AS EST_Atraso_Negro,

     // ── PNAD Gênero ──────────────────────────────────────────────
     coalesce(st.homem_pnad_t_analf25m, null)         AS EST_Analf_Homem,
     coalesce(st.mulher_pnad_t_analf25m, null)        AS EST_Analf_Mulher

// [Suas queries específicas continuam aqui com CALLs isolados]
```

### 9.2 Template — Coleta de alunos por segmento

```cypher
// Filtro EF2 — resultado: Turma, Grade, ListaTurma por escola
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
     OR (cr.stage = 'ENSINO FUNDAMENTAL' AND cr.grade_level =~ 'NA [6-9]\\* SÉRIE')
  RETURN cr.name       AS Turma,
         cr.grade_level AS Grade,
         collect(DISTINCT stu) AS ListaTurma
}
WHERE size(ListaTurma) >= 10  // descartar turmas com pouquíssimos alunos
```

### 9.3 Template — Dimensão frequência

```cypher
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(stu)
  RETURN
    count(DISTINCT CASE WHEN sc IS NOT NULL THEN stu END) AS N_Com_Diario,
    sum(coalesce(sc.total_faults_per_day, 0))             AS TotalFaltas,
    sum(coalesce(sc.scheduled_student_class_days, 200))   AS TotalDias,
    count(DISTINCT CASE WHEN sc IS NOT NULL
                         AND sc.scheduled_student_class_days > 0
                         AND toFloat(sc.total_faults_per_day)
                             / sc.scheduled_student_class_days > 0.10
                        THEN stu END)                      AS N_Falta_Critica
}
WITH *,
     CASE WHEN N_Com_Diario = 0 THEN null
          WHEN TotalDias > 0 THEN round(toFloat(TotalFaltas) / TotalDias * 100, 2)
          ELSE null
     END AS Taxa_Ausencia_Pct
```

### 9.4 Template — Dimensão notas por matéria (EF2)

```cypher
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
  RETURN Materia,
         count(Nota)                                               AS N_Notas,
         round(avg(Nota), 2)                                       AS Media_Nota,
         round(stDev(Nota), 2)                                     AS Dispersao,
         count(CASE WHEN Nota < 5.0 THEN 1 END)                   AS N_Abaixo5,
         count(CASE WHEN Nota >= 4.0 AND Nota < 5.0 THEN 1 END)   AS N_Beira_Aprovacao,
         count(CASE WHEN Nota < 3.0 THEN 1 END)                   AS N_Critico
}
WITH *,
     CASE WHEN N_Notas > 0 THEN
       round(toFloat(N_Abaixo5) / N_Notas * 100, 1)
     ELSE null END AS Pct_Abaixo5,
     CASE WHEN N_Notas = 0 THEN 0 ELSE 1 END AS Flag_Tem_Notas
WHERE Materia IS NOT NULL AND N_Notas >= 5
```

### 9.5 Template — Dimensão notas globais (EF1)

```cypher
CALL (ListaAlunos) {
  UNWIND ListaAlunos AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE coalesce(sd.discipline_name, '') = ''
    AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10
            THEN coalesce(sd.final_mean, sd.grade_1) / 10.0
            ELSE coalesce(sd.final_mean, sd.grade_1)
       END AS Nota,
       CASE WHEN sd.grade_1 IS NOT NULL AND sd.grade_1 > 10
            THEN sd.grade_1 / 10.0
            ELSE sd.grade_1
       END AS NotaInicial
  RETURN count(Nota)                                       AS N_Notas,
         round(avg(Nota), 2)                               AS Media_Global,
         round(stDev(Nota), 2)                             AS Dispersao,
         count(CASE WHEN Nota < 5.0 THEN 1 END)           AS N_Abaixo5,
         round(avg(Nota) - avg(NotaInicial), 2)            AS Trajetoria_Media,
         CASE WHEN count(Nota) = 0 THEN 0 ELSE 1 END      AS Flag_Tem_Notas
}
```

### 9.6 Template — Perfil social (list comprehension)

```cypher
// Depois de ter ListaAlunos ou ListaTurma disponível no WITH
WITH *,
     size(ListaAlunos) AS N_Alunos,
     // Bolsa Família
     size([s IN ListaAlunos WHERE coalesce(s.bolsa_familia, false) = true])
       AS N_BolsaFamilia,
     // PCD — verificação string, não boolean
     size([s IN ListaAlunos WHERE coalesce(s.deficiency, 'Não') STARTS WITH 'Possui'])
       AS N_PCD,
     // Gênero
     size([s IN ListaAlunos WHERE s.gender =~ '(?i)^F.*'])
       AS N_Feminino,
     size([s IN ListaAlunos WHERE s.gender =~ '(?i)^M.*'])
       AS N_Masculino,
     // Zona de residência
     size([s IN ListaAlunos WHERE coalesce(s.residence_zone,'') =~ '(?i).*rural.*'])
       AS N_Rural
```

### 9.7 Template — Exibição segura de métricas opcionais

```cypher
// Sempre exibir contexto de cobertura junto com a métrica
RETURN
  // Frequência — com flag de cobertura
  CASE WHEN N_Com_Diario = 0
       THEN 'Sem Diário Eletrônico'
       ELSE toString(Taxa_Ausencia_Pct) + '%'
  END AS Ausencia_Display,
  N_Com_Diario,
  CASE WHEN N_Com_Diario = 0 THEN 0 ELSE 1 END AS Flag_Tem_Diario,

  // Notas — com flag de cobertura
  CASE WHEN Flag_Tem_Notas = 0
       THEN null
       ELSE Media_Nota
  END AS Media_Nota_Safe,
  Flag_Tem_Notas,

  // IBGE — com flag de fonte
  Freq_Ref AS IBGE_Freq_Ref,
  CASE WHEN MUNI_Freq_Liq IS NOT NULL
       THEN 'Dado Municipal'
       ELSE 'Média UF (Proxy)'
  END AS IBGE_Fonte_Freq
```

---

## 10. Vector Search Indexes (RAG)

### 10.1 Índices criados

Dois índices de busca vetorial foram criados no Neo4j para suportar busca por similaridade entre estudantes e escolas:

```cypher
-- Student index
CREATE VECTOR INDEX student_embedding IF NOT EXISTS
FOR (s:Student) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

-- School index
CREATE VECTOR INDEX school_embedding IF NOT EXISTS
FOR (s:School) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
```

**Status atual:**
- Índice de estudantes: ONLINE, 96% de cobertura (54.290 / 56.560 estudantes)
- Índice de escolas: ONLINE, 98.8% de cobertura

---

### 10.2 Query de busca por similaridade

```cypher
-- Find top-5 similar students (excluding self)
CALL db.index.vector.queryNodes('student_embedding', 6, $embedding)
YIELD node, score
WHERE node.id <> $student_id
RETURN node.id AS id,
       node.risk_cluster AS cluster,
       node.risk_score AS risk_score,
       score
LIMIT 5
```

**Interpretação de scores:**
- Score de `1.0` = perfil idêntico (muito raro)
- Score > `0.80` = similaridade forte (alunos com perfil educacional/social similar)
- Score > `0.70` = similaridade moderada
- Score < `0.70` = dissimilaridade

**Caso de uso:** Dado um aluno João com `risk_score=21.1` (risco médio-alto de evasão), encontrar 5 estudantes com perfil similar que tiveram sucesso académico → informar ao LLM que intervenções usadas nesses alunos similares podem ser eficazes.

---

### 10.3 Embedding de estudante — Conteúdo codificado

O texto narrativo de cada aluno (~100–200 palavras) é convertido em um vetor 384-dimensional e armazenado em `Student.embedding`:

```
"Aluno: gênero feminino, etnia Parda, zona rural, bolsa família sim, deficiência não.
Frequência: 12% de faltas. Nota: sem nota registrada.
Saúde: anemia, malnutrition.
Contexto: UF SE, IBGE freq_liq_muni 0.91, IDEB estadual 4.1, abandono estadual 4.20%.
Cluster de risco: 3."
```

**Campos codificados:**

| Feature | Valor exemplo | Significado semântico |
|---|---|---|
| `gender_bin` | feminino / masculino | Grupo demográfico |
| `ethnicity_raw` | Parda, Branca, Preta | Contexto de vulnerabilidade racial |
| `residence_zone_enc` | rural / urbana | Acesso a infraestrutura |
| `bolsa_familia` | sim / não | Vulnerabilidade socioeconômica |
| `has_deficiency` | sim / não | Flag de necessidades especiais |
| `taxa_ausencia` | 12% de faltas | Sinal de engajamento/risco |
| `tem_diario` | sem diário eletrônico | Qualidade de cobertura de dados |
| `nota_final_norm` | 5.8 / sem nota registrada | Desempenho académico |
| Health flags | anemia, malnutrition | Barreiras de saúde individuais |
| `uf` + IBGE context | UF SE, freq_liq 0.91 | Contexto regional/estrutural |
| `est_ideb_af` + dropout | 4.1, 4.20% | Benchmark de estado |
| `risk_cluster` | 3 | Resultado do clustering ML |

Todos os embeddings são **L2-normalizados** (magnitude = 1), permitindo similaridade coseno via produto escalar.

---

### 10.4 Embedding de escola — Conteúdo codificado

O texto narrativo de cada escola (~80–120 palavras) é convertido em um vetor 384-dimensional e armazenado em `School.embedding`:

```
"Escola: UF SE, município Boquim, saúde Moderado (score 62.3),
ausência 8.4%, nota média 6.1, Bolsa Família 54%, PCD 3.2%,
IBGE freq_liq 0.91, IDEB EF-AF 4.1, abandono estadual 4.20%,
qualidade dos dados: completo."
```

**Campos codificados:**

| Feature | Descrição |
|---|---|
| `uf` + `municipio` | Localização geográfica |
| `nivel_saude` + `score_saude` | Score agregado de saúde escolar (0–100, 4 dimensões) |
| `taxa_ausencia_pct` | Taxa média de ausência de todos os alunos |
| `media_nota_escola` | Nota média de todos os alunos |
| `pct_bolsa_familia` | % de alunos recebendo Bolsa Família |
| `pct_pcd` | % de alunos com deficiência |
| `muni_freq_liq_fund` | Benchmark IBGE de matrícula líquida |
| `est_ideb_af` + `est_taxa_abandono` | Benchmarks estaduais QEdu |
| `data_quality` | Flag de completude (tem notas + dados de frequência) |

---

*Schema validado contra dados reais — D_CLASSROOM_202602252356 (10.219 turmas), nós State e Municipality verificados via queries diretas. Cobertura de embeddings: 96% estudantes, 98.8% escolas. Última atualização: 2026-03.*

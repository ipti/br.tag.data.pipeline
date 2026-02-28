# PLAN: ML/MLOps — Plataforma de Inteligência Educacional

> **Slug:** `ml-neo4j-school-v3`
> **Tipo do Projeto:** BACKEND / DATA SCIENCE / MLOps
> **Depende de:** `PLAN-neo4j-ibge-migration.md` — concluído ✅
> **Status:** EXECUÇÃO
> **Data:** 2026-02-22

---

## 🎯 Visão Geral

Com os dados do IBGE já migrados para o Neo4j (nós `Municipality` e `State` enriquecidos),
o grafo agora carrega dois mundos em paralelo:

- **Dados internos** — o que a escola sabe sobre cada aluno: notas, faltas, saúde, matrícula, turma, professor
- **Dados externos** — o que o território diz sobre o contexto daquele aluno: IDHM, RDPC, IDEB municipal, taxa de abandono regional, distorção idade-série, proficiência, equidade racial e de gênero

O objetivo deste plano é transformar esse grafo em **três entregas concretas**:

1. **Modelos ML** — predição de evasão, queda de notas e clustering de risco com explicabilidade
2. **RAG conversacional** — qualquer pergunta sobre aluno, escola ou região respondida com contexto completo do grafo
3. **MLOps** — retreinamento automático, detecção de drift e gestão de versões de modelos

---

## 🗂️ O Grafo Disponível — O Que Já Temos

```
(Student)
  ├─[:ENROLLED_AT_SCHOOL]──► (School)
  │                               └─[:HAS_GEOGRAPHY]──► (SchoolGeograph)
  │                                                           └─[:LOCATED_IN_MUNICIPALITY]──► (Municipality)
  │                                                                                                └─[:BELONGS_TO_STATE]──► (State)
  ├─[:ENROLLED_IN]──────────► (Classroom)
  ├─[:HAS_HEALTH]────────────► (Health)
  ├─[:HAS_DISCIPLINE]────────► (StudentDiscipline)
  ├─[:EVALUATED_IN]──────────► (Avaliation) ──[:AVALIATION_OF]──► (StudentDiscipline)
  └─[:ATTENDED]◄─────────────  (StudentClass) ──[:ATTENDANCE_OF]──► (Class) ──[:TAUGHT_IN]──► (Classroom)
                                                                              └─[:CLASS_AT_SCHOOL]──► (School)
```

### Propriedades disponíveis por nó (resumo das mais relevantes para ML/RAG)

| Nó | Propriedades internas | Propriedades IBGE |
|----|-----------------------|-------------------|
| `Student` | `gender`, `ethnicity`, `deficiency`, `bolsa_familia`, `residence_zone`, `birthday` | — |
| `Health` | `diabetes`, `obesity`, `malnutrition`, `hypertension`, `celiac`, `sickle_cell_anemia` | — |
| `StudentDiscipline` | `discipline_name`, `grade_1..4`, `rec_bim_1..4`, `rec_final`, `final_mean` | — |
| `StudentClass` | `total_faults_per_day`, `total_faults_per_discipline`, `scheduled_student_class_days` | — |
| `Class` | `teacher_id`, `discipline_name`, `scheduled_day`, `scheduled_month`, `scheduled_year` | — |
| `Classroom` | `grade_level`, `stage`, `year`, `status` | — |
| `School` | `name`, `latitude`, `longitude`, `situation` | — |
| `SchoolGeograph` | `city`, `uf`, `cep` | — (link para Municipality) |
| `Municipality` | — | `atl_*` (Atlas 2010), `qedu_ideb_*`, `qedu_taxa_*`, `qedu_distorcao_*`, `qedu_lp_*`, `qedu_mt_*`, `qedu_permanencia`, `qedu_pct_fora_escola` |
| `State` | — | `pnad_idhm`, `pnad_rdpc`, `pnad_gini`, `pnad_ppob`, `pnad_espvida`, `branco_pnad_*`, `preto_pnad_*`, `pardo_pnad_*`, `homem_pnad_*`, `mulher_pnad_*` |

---

## ❓ 12 Perguntas do Gestor — Com Enriquecimento Completo

Cada pergunta mostra exatamente quais nós internos respondem o **dado bruto** e quais dados do
`Municipality`/`State` transformam a resposta em **decisão contextualizada**.

---

### P1 — "Quais alunos têm alta probabilidade de evadir nos próximos 30 dias?"

**Tipo:** Classificação binária com priorização de lista

**Dado interno (Neo4j):**
- `StudentClass.total_faults_per_day` — faltas acumuladas por dia
- `StudentClass.scheduled_student_class_days` — dias letivos programados → taxa de ausência
- `StudentDiscipline.final_mean`, `grade_1..4` — tendência de queda de notas
- `Avaliation.situation` — reprovações e situações de risco formal
- `Student.bolsa_familia`, `residence_zone`, `ethnicity` — perfil de vulnerabilidade
- `Health.*` — condições que aumentam ausência (malnutrition, sickle_cell_anemia)
- `Classroom.stage`, `grade_level` — série e etapa (risco diferente por ciclo)

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_pct_fora_escola` — % da coorte regional que já saiu da escola (quanto o aluno está acima/abaixo da média local)
- `Municipality.qedu_taxa_abandono` — taxa histórica de abandono do município (baseline de referência)
- `Municipality.atl_atraso_2_fund` — distorção regional (aluno com atraso em município já distorcido = risco maior)
- `State.pnad_ppob`, `pnad_rdpc` — contexto econômico do estado como fator de risco estrutural

**Output esperado pelo gestor:** Lista ranqueada por probabilidade, com explicação por aluno:
"Aluno X tem 84% de prob. de evasão — 12 faltas nos últimos 20 dias, nota caindo para 3.2,
em município com taxa de abandono regional de 9.1% (acima da média estadual de 6.4%)."

---

### P2 — "Qual é a correlação entre contexto socioeconômico e desempenho acadêmico na nossa rede?"

**Tipo:** Análise de correlação + regressão explicativa

**Dado interno:**
- `StudentDiscipline.final_mean`, `grade_1..4` — desempenho acadêmico individual
- `Student.ethnicity`, `residence_zone`, `bolsa_familia` — perfil socioeconômico interno
- Agregado por `School` → desempenho médio por escola

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_ideb_af`, `qedu_nota_mt_af`, `qedu_nota_lp_af` — onde a escola está em relação ao IDEB municipal
- `Municipality.atl_fund_comp_25m`, `atl_superior_comp_25m` — escolaridade da população adulta local (capital cultural familiar)
- `State.pnad_rdpc`, `pnad_gini` — desigualdade econômica do estado
- `Municipality.atl_branco_analf15m`, `atl_negro_analf15m` — desigualdade educacional racial no entorno

**Output esperado:** Scatter com RDPC × nota média por escola, identificando outliers positivos
(escolas que performam acima do esperado para seu contexto) e negativos (abaixo do esperado apesar
de boa infraestrutura regional).

---

### P3 — "Escolas em regiões com baixo IDHM têm maior evasão mesmo com notas similares às de regiões ricas?"

**Tipo:** Análise de subgrupos + teste estatístico

**Dado interno:**
- Evasão calculada via `Avaliation.situation` ou `Student.enrollment_status`
- `StudentDiscipline.final_mean` — notas para controlar desempenho
- Agrupamento por `School` → `SchoolGeograph` → `Municipality`

**Contexto IBGE que enriquece a decisão:**
- `State.pnad_idhm`, `pnad_idhm_e` — dimensão educacional do IDH estadual
- `Municipality.qedu_taxa_abandono` — abandono regional como referência externa
- `Municipality.atl_atraso_2_fund` — proxy estrutural de risco
- `Municipality.qedu_permanencia` — permanência de coorte como evidência longitudinal

**Output esperado:** Comparativo entre grupos de municípios (IDHM alto/médio/baixo) mostrando que,
com mesma nota média interna, alunos em contextos de baixo IDHM evadiam X% mais.
Justifica investimento diferenciado por região.

---

### P4 — "Quais disciplinas têm maior impacto negativo e positivo na nota final do aluno?"

**Tipo:** SHAP / Feature Importance por disciplina

**Dado interno:**
- `StudentDiscipline.grade_1..4`, `rec_bim_1..4`, `rec_final`, `final_mean` — desempenho por bimestre
- `StudentDiscipline.discipline_name` — agrupamento por matéria
- `Avaliation.situation` — resultado formal

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_lp_adequado_af`, `qedu_mt_adequado_af` — % de alunos com aprendizagem adequada no município (se internamente LP está bem mas o benchmark regional é baixo, pode haver efeito de seleção)
- `Municipality.qedu_nota_mt_af`, `qedu_nota_lp_af` — notas SAEB do município como referência de nível

**Output esperado:** Ranking de disciplinas com SHAP values: "Matemática no 3º bimestre explica 31%
da variância na nota final. Município com `lp_adequado_af=28%` sugere que LP é o maior risco
estrutural regional."

---

### P5 — "O aluno X está em risco. O que aconteceu com alunos similares em outras escolas?"

**Tipo:** RAG com busca vetorial + análise de casos análogos

**Dado interno:**
- Embedding do aluno (gerado com features de `Student` + `Health` + médias de `StudentDiscipline` + faltas)
- Busca por alunos de perfil similar via Neo4j Vector Index
- Histórico dos similares: `Avaliation.situation`, `StudentClass.total_faults_per_day`

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_ideb_af` — IDEB da escola onde cada aluno similar estava
- `Municipality.qedu_taxa_abandono` — contexto regional de cada aluno similar
- `State.pnad_idhm` — nível de desenvolvimento do estado de cada similar
- Comparação entre município do aluno atual e município dos similares

**Output esperado:** "Os 5 alunos mais similares ao aluno X (mesma etnia, bolsa família, faltas
no 3º bimestre): 3 evadiram, 2 recuperaram. Os que recuperaram estavam em escolas com
`qedu_ideb_af` 0.8 pontos acima — e a intervenção aconteceu antes do 4º bimestre."

---

### P6 — "Alunos do Bolsa Família têm maior taxa de evasão depois do 5º bimestre?"

**Tipo:** Análise de sobrevivência + segmentação

**Dado interno:**
- `Student.bolsa_familia` — flag do benefício
- `StudentClass` com timestamps → curva de permanência por bimestre
- `Avaliation.situation` ao longo do ano → evento de evasão

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_pct_fora_escola` — % da coorte fora da escola no município (controle regional)
- `Municipality.qedu_taxa_abandono` — taxa de abandono municipal ponderada
- `State.pnad_ppob` — % de pobres no estado (contexto macroeconômico da dependência do benefício)
- `Municipality.atl_freq_15a17` — frequência escolar da faixa etária de risco na região

**Output esperado:** Curva de Kaplan-Meier separando `bolsa_familia=True/False`, com anotação
do contexto regional: "Em municípios com `qedu_pct_fora_escola > 20%`, a diferença entre grupos
Bolsa/não-Bolsa cresce 40% após o 5º bimestre."

---

### P7 — "Quais escolas têm melhor recuperação de alunos em risco vs. a média regional?"

**Tipo:** Benchmarking + ranking relativo

**Dado interno:**
- Alunos que entraram em risco (notas < 5 ou faltas > 25%) e saíram do risco
- Agrupado por `School` → taxa de recuperação interna
- `Class.teacher_id` por disciplina → correlação com professor

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_ideb_af` — IDEB do município como benchmark externo de referência
- `Municipality.qedu_taxa_aprovacao` — taxa de aprovação regional
- `Municipality.atl_freq_liq_fund` — frequência líquida regional (o quanto é normal para o entorno)
- `Municipality.qedu_distorcao_ef_total` — distorção regional (escola com baixa distorção interna em município de alta distorção = outlier positivo)

**Output esperado:** Ranking de escolas com "índice de recuperação ajustado pelo contexto":
"Escola A tem taxa de recuperação 2.3× acima do benchmark municipal — em contexto de IDEB 3.8
e abandono regional de 8%, esse resultado é estatisticamente relevante."

---

### P8 — "Qual é o perfil econômico e geográfico típico de alunos recorrentemente reprovados?"

**Tipo:** Clustering + profiling de subgrupos

**Dado interno:**
- `Avaliation.situation` com múltiplas reprovações históricas
- `Student.ethnicity`, `gender`, `residence_zone`, `deficiency`
- `StudentDiscipline.final_mean` abaixo do limiar por 2+ anos
- `Health.*` — condições de saúde associadas

**Contexto IBGE que enriquece a decisão:**
- `State.preto_pnad_rdpc`, `pardo_pnad_rdpc` vs `branco_pnad_rdpc` — gap racial de renda no estado
- `Municipality.atl_negro_atraso_fund`, `atl_branco_atraso_fund` — atraso escolar por raça no município
- `Municipality.atl_rural_freq_liq_fund` vs `atl_urbano_freq_liq_fund` — diferença urbano/rural
- `State.mulher_pnad_t_flmed` vs `homem_pnad_t_flmed` — gap de gênero em frequência ao EM

**Output esperado:** 3-4 perfis de cluster com características internas + contexto IBGE:
"Cluster 2 (34% dos reprovados): negros, zona rural, 2+ condições de saúde,
municípios com `atl_negro_atraso_fund` = 41% vs `atl_branco_atraso_fund` = 19%.
Este grupo concentra 78% da reprovação recorrente."

---

### P9 — "Em quais meses a frequência cai mais? Isso está correlacionado com a realidade do município?"

**Tipo:** Série temporal + análise de sazonalidade regional

**Dado interno:**
- `StudentClass.total_faults_per_day` com `Class.scheduled_month` → sazonalidade de faltas
- `Class.scheduled_year` → comparação entre anos
- `School` → agrupamento geográfico

**Contexto IBGE que enriquece a decisão:**
- `State.pnad_espvida`, `pnad_mort1` — indicadores de saúde regional (queda em agosto/setembro pode correlacionar com ondas de doenças)
- `Municipality.atl_rural_freq_liq_fund` vs `atl_urbano_freq_liq_fund` — queda maior em zonas rurais pode indicar calendário agrícola
- `Municipality.atl_freq_6a14`, `atl_freq_15a17` — cobertura escolar por faixa etária (meses de queda podem ser previsíveis por faixa)

**Output esperado:** Heatmap mês × escola com overlay de "benchmarks regionais":
"Julho/agosto = queda esperada em todo o estado (benchmark IBGE). Setembro = queda anormal
em escolas rurais do norte do estado — acima do padrão regional, investigar."

---

### P10 — "Relatório completo do aluno Y: notas, frequência, saúde, histórico e sugestões."

**Tipo:** RAG full-graph — síntese contextualizada por LLM

**Dado interno (contexto completo do grafo):**
- `Student` — perfil completo
- `Health` — todas as condições de saúde
- `StudentDiscipline` — notas e recuperações por disciplina e bimestre
- `StudentClass` — faltas por aula e por disciplina
- `Avaliation` — situações formais de avaliação
- `Classroom` — série, etapa e turma
- `School` → `SchoolGeograph` — localização geográfica

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_ideb_af`, `qedu_nota_mt_af`, `qedu_nota_lp_af` — onde a escola está no IDEB
- `Municipality.qedu_lp_adequado_af`, `qedu_mt_adequado_af` — % de alunos com aprendizagem adequada no município
- `Municipality.qedu_taxa_abandono`, `qedu_permanencia` — risco estrutural regional
- `State.pnad_idhm`, `pnad_rdpc` — contexto macroeconômico
- Se `Student.ethnicity` for negro/pardo: `State.preto_pnad_rdpc` / `pardo_pnad_rdpc` e `Municipality.atl_negro_analf15m` para contextualizar desigualdade racial

**Output esperado — bloco RAG no prompt:**
```
=== ALUNO ===
Nome: [anonimizado], Série: 7º ano EF, Turma 2024
Faltas: 18/120 dias (15%) | Nota média: 4.8 | Recuperações: LP, Matemática
Saúde: Desnutrição leve registrada
Bolsa Família: Sim | Zona: Rural

=== ESCOLA / MUNICÍPIO ===
Município: Moju/PA
IDEB Anos Finais (2021): 3.9 — 20% abaixo da média nacional (4.9)
Taxa de abandono municipal: 11.2% | Distorção EF total: 28%
% adequado em LP: 22% | % adequado em Matemática: 18%
Permanência de coorte: 74%

=== ESTADO ===
IDHM Pará (2010): 0.646 [Médio] | RDPC: R$ 439
% pobres: 41% | Taxa de analfabetismo 15+: 11.3%

⚠️ Aluno em contexto de alto risco estrutural.
Sugestão: intervenção imediata em LP e Matemática, acompanhamento de frequência.
```

---

### P11 — "Qual professor está correlacionado com melhor desempenho por disciplina?"

**Tipo:** Análise causal + ranking por professor

**Dado interno:**
- `Class.teacher_id` + `discipline_name` → associação professor × disciplina
- `StudentDiscipline.final_mean`, `grade_1..4` dos alunos de cada turma → desempenho
- `Classroom.grade_level`, `stage` — controle por série (professor de 6º ano vs 9º ano)
- Agrupamento: média de notas por `teacher_id` × `discipline_name` × `grade_level`

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_nota_mt_af`, `qedu_nota_lp_af` — notas SAEB do município como benchmark externo
- `Municipality.qedu_lp_adequado_af`, `qedu_mt_adequado_af` — % de proficiência regional (um professor bom em município de baixo benchmark regional é mais significativo)

**Output esperado:** Ranking de professores com desempenho ajustado pelo benchmark municipal:
"Professor A em Matemática: média de alunos 5.8 vs benchmark SAEB município 4.2 (+38%).
Professor B em LP: média 4.9 vs benchmark 4.6 (+6%) — diferença não significativa."

---

### P12 — "Classifique todas as escolas em quartis de risco de evasão para o próximo semestre."

**Tipo:** Classificação multi-label + ranking de escolas

**Dado interno:**
- Taxa de evasão histórica por escola (via `Avaliation.situation`)
- Média de faltas por escola (`StudentClass.total_faults_per_day` agrupado)
- % de alunos com recuperação (`StudentDiscipline.rec_final`)
- Distribuição de perfis de risco (bolsa família, deficiência, saúde) por escola

**Contexto IBGE que enriquece a decisão:**
- `Municipality.qedu_ideb_af` — IDEB externo como indicador de qualidade sistêmica
- `Municipality.qedu_taxa_abandono` — taxa de abandono regional (escolas acima disso merecem atenção prioritária)
- `Municipality.qedu_distorcao_ef_total`, `qedu_distorcao_em_total` — distorção regional (escola com distorção interna acima da regional = sinal de alerta)
- `Municipality.qedu_pct_fora_escola` — evasão de coorte regional como teto de referência

**Output esperado:** Tabela de escolas com quartil de risco + explicação:
"Escola X — Quartil 4 (crítico): taxa interna de 13.1% vs abandono municipal de 8.2%.
IDEB externo: 3.7 (baixo). Distorção interna acima do benchmark regional em 8pp.
Prioridade máxima de intervenção."

---

## 🏗️ Arquitetura do Sistema

```
Neo4j (Grafo + IBGE integrado)
    │
    ├── Feature Extractor (Cypher → Parquet)
    │       Dados internos + Municipality + State props
    │
    ├── ML Pipeline (scikit-learn / XGBoost / SHAP)
    │       ├── Dropout Classifier
    │       ├── Grade Regressor
    │       └── Risk Clusterer
    │
    ├── Embedding Pipeline (sentence-transformers local)
    │       ├── Student Embedder → Neo4j Vector Index
    │       └── School Embedder → Neo4j Vector Index
    │
    ├── RAG Layer (LangChain + Cypher + LLM)
    │       ├── Retriever (graph + vector search)
    │       ├── Context Builder (bloco IBGE automático)
    │       └── LLM (Gemini Flash / Ollama)
    │
    ├── MLOps (MLflow + Evidently)
    │       ├── Experiment Tracking
    │       ├── Drift Detection
    │       └── Champion/Challenger
    │
    └── API (FastAPI)
            ├── /predict/dropout/{student_id}
            ├── /predict/grade/{student_id}/{discipline_id}
            ├── /ask/student  (RAG)
            ├── /ask/school   (RAG)
            └── /report/school/{school_id}
```

---

## 🗂️ Stack Técnico

| Componente | Tecnologia | Justificativa |
|------------|-----------|---------------|
| Graph DB + Vector | Neo4j 5.11+ (HNSW) | Grafo + busca vetorial nativo |
| Feature Extraction | Cypher → Pandas → Parquet | Aproveitamento do grafo enriquecido |
| ML Classificação | XGBoost + CatBoost | Melhor performance com dados tabulares mistos |
| ML Regressão | GradientBoostingRegressor | Notas contínuas com features mistas |
| Clustering | KMeans + DBSCAN | Silhouette guia escolha de K |
| Sobrevivência | Kaplan-Meier (lifelines) | Curvas de permanência por grupo |
| Explicabilidade | SHAP | Feature importance local + global |
| Embeddings | `paraphrase-multilingual-MiniLM-L12-v2` | Local, gratuito, suporte português |
| RAG Framework | LangChain + LangGraph | Orquestração de chain + memória |
| LLM | Gemini 1.5 Flash (free tier) / Ollama | Zero custo de API |
| MLOps | MLflow (self-hosted) + Evidently AI | Tracking + drift detection |
| Orquestração | Apache Airflow | Reutiliza DAGs existentes |
| API | FastAPI | Padrão do projeto |

---

## 📋 Fases de Execução

### ✅ Fase 0 — Pré-requisito (CONCLUÍDA)

Executada pelo `dag__neo4j_ibge_migration`. O grafo já tem:
- Nós `Municipality` com `atl_*`, `qedu_*`
- Nós `State` com `pnad_*`, `branco_pnad_*`, `preto_pnad_*`, `pardo_pnad_*`
- Relacionamentos `SchoolGeograph -[:LOCATED_IN_MUNICIPALITY]-> Municipality -[:BELONGS_TO_STATE]-> State`

**Verificar antes de continuar:**
```cypher
MATCH (m:Municipality)
WHERE m.qedu_ideb_af IS NOT NULL
RETURN count(m) AS municipios_com_ideb
// Esperado: > 4.000

MATCH (sg:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
RETURN count(sg) AS geographs_linkados
// Esperado: todos os SchoolGeograph linkados
```

---

### 🔶 Fase 1 — Vector Indexes + Feature Extraction

**Objetivo:** Criar os indexes vetoriais e o pipeline de extração de features para ML.

#### Task 1.1 — Criar Vector Indexes no Neo4j

```cypher
CREATE VECTOR INDEX student_embedding IF NOT EXISTS
FOR (s:Student) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};

CREATE VECTOR INDEX school_embedding IF NOT EXISTS
FOR (s:School) ON s.embedding
OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}};
```

> Dimensão 384 alinhada ao `paraphrase-multilingual-MiniLM-L12-v2`.

**Verify:** `SHOW INDEXES` → ambos com status `ONLINE`

#### Task 1.2 — Feature Extractor (`src/ml/features/student_features.py`)

Query Cypher principal que extrai o dataset de treino:

```cypher
// Extrai features de um aluno + contexto regional via grafo
MATCH (s:Student)-[:ENROLLED_AT_SCHOOL]->(school:School)
    -[:HAS_GEOGRAPHY]->(geo:SchoolGeograph)
    -[:LOCATED_IN_MUNICIPALITY]->(mun:Municipality)
    -[:BELONGS_TO_STATE]->(state:State)
OPTIONAL MATCH (s)-[:HAS_HEALTH]->(h:Health)
OPTIONAL MATCH (s)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
OPTIONAL MATCH (sc:StudentClass)-[:ATTENDED]->(s)
RETURN
    -- Identidade
    s.id                              AS student_id,
    -- Perfil do aluno
    s.gender                          AS gender,
    s.ethnicity                       AS ethnicity,
    s.deficiency                      AS deficiency,
    s.bolsa_familia                   AS bolsa_familia,
    s.residence_zone                  AS residence_zone,
    -- Saúde
    h.malnutrition                    AS malnutrition,
    h.obesity                         AS obesity,
    h.diabetes                        AS diabetes,
    h.sickle_cell_anemia              AS sickle_cell_anemia,
    -- Frequência
    avg(sc.total_faults_per_day)      AS media_faltas_dia,
    sum(sc.total_faults_per_discipline) AS total_faltas_disciplina,
    -- Notas (médias por aluno)
    avg(sd.final_mean)                AS media_notas,
    avg(sd.grade_1)                   AS media_nota_b1,
    avg(sd.grade_4)                   AS media_nota_b4,
    count(CASE WHEN sd.rec_final IS NOT NULL THEN 1 END) AS n_recuperacoes_finais,
    -- Contexto município (IBGE)
    mun.qedu_ideb_af                  AS mun_ideb_af,
    mun.qedu_taxa_abandono            AS mun_taxa_abandono,
    mun.qedu_pct_fora_escola          AS mun_pct_fora_escola,
    mun.qedu_permanencia              AS mun_permanencia,
    mun.qedu_distorcao_ef_total       AS mun_distorcao_ef,
    mun.atl_atraso_2_fund             AS mun_atraso_2_fund,
    mun.atl_t_analf15m                AS mun_analf15m,
    mun.qedu_lp_adequado_af           AS mun_lp_adequado,
    mun.qedu_mt_adequado_af           AS mun_mt_adequado,
    -- Contexto estado (IBGE)
    state.pnad_idhm                   AS state_idhm,
    state.pnad_rdpc                   AS state_rdpc,
    state.pnad_gini                   AS state_gini,
    state.pnad_ppob                   AS state_ppob,
    state.pnad_espvida                AS state_espvida
```

**Decisões de feature engineering no Python (pós-query):**
- `taxa_ausencia = media_faltas_dia / scheduled_days` — % de ausência
- `variacao_nota = media_nota_b4 - media_nota_b1` — tendência de queda
- `n_doencas = sum(malnutrition, obesity, diabetes, sickle_cell_anemia)` — score de saúde
- `razao_abandono_vs_regional = taxa_ausencia_interna / mun_taxa_abandono` — quanto o aluno desvia do padrão regional
- Label de evasão: derivado de `Avaliation.situation` ou `enrollment_status`

**Verify:**
```python
df = extract_student_features()
assert df['mun_ideb_af'].notna().mean() > 0.90   # 90%+ com IBGE
assert df['media_notas'].notna().mean() > 0.80    # 80%+ com notas
print(df[['media_faltas_dia', 'mun_taxa_abandono', 'state_rdpc']].describe())
```

---

### 🔶 Fase 2 — Embeddings

**Objetivo:** Gerar vetores numéricos (embeddings semânticos) de Alunos e Escolas para permitir buscas de similaridade no RAG (ex: gestor busca "alunos com perfil parecido") e agrupar contextos por similaridade.

#### Task 2.0 — Motor de Embeddings Local (`src/embeddings/embedder_factory.py`)

Para batermos a meta de **risco/custo zero** de API, todo o pipeline de embeddings rodará localmente. Teremos duas opções de motor de inferência controladas por variável de ambiente (`EMBEDDING_PROVIDER`), gerando os vetores no formato nativo que o driver do Neo4j (Python) e o Vector Index esperam (`List[float]`):

1. **Sentence Transformers (Padrão/Leve):** Modelo `paraphrase-multilingual-MiniLM-L12-v2` (384 dims). Roda super rápido em CPU, ideal para CI/CD e containers simples, tendo fluência nativa e excelente em português.
2. **Ollama (Alternativo/Alta Qualidade):** Modelo `nomic-embed-text` (768 dims, default para RAGs locais) customizado para tarefas de RAG. Requer que o daemon do Ollama esteja de pé.

```python
import os
import requests
from typing import List

class EmbeddingService:
    def __init__(self):
        self.provider = os.getenv("EMBEDDING_PROVIDER", "sentence_transformers")
        
        if self.provider == "ollama":
            self.api_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/embeddings")
            self.model = "nomic-embed-text" # Atenção: índice Neo4j precisa estar configurado p/ 768
            self._embed_func = self._embed_ollama
        else:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            self._embed_func = self._embed_sentence_transformers

    def _embed_ollama(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for text in texts:
            # Integração limpa com API REST do Ollama
            response = requests.post(self.api_url, json={"model": self.model, "prompt": text})
            response.raise_for_status()
            embeddings.append(response.json()["embedding"]) 
        return embeddings

    def _embed_sentence_transformers(self, texts: List[str]) -> List[List[float]]:
        # .encode() retorna numpy array; é vital converter p/ float list nativo do Python 
        # antes de injetar via driver Cypher no Neo4j, senão o serializer falha.
        embeddings = self.model.encode(texts)
        return [emb.tolist() for emb in embeddings]
        
    def generate(self, texts: List[str]) -> List[List[float]]:
        return self._embed_func(texts)
```

#### Task 2.1 — Text Builders (`src/embeddings/text_builders.py`)

Transformar propriedades em uma "frase" rica semanticamente (o input do modelo):

```python
# Texto concatenado para embedding do aluno
def build_student_text(student: dict) -> str:
    return (
        f"Aluno: {student['gender']}, {student['ethnicity']}, "
        f"zona {student['residence_zone']}, "
        f"bolsa família: {student['bolsa_familia']}, "
        f"média notas: {student['media_notas']:.1f}, "
        f"faltas: {student['taxa_ausencia']:.1%}, "
        f"recuperações: {student['n_recuperacoes_finais']}, "
        f"saúde: {student['n_doencas']} condições"
    )

def build_school_text(school: dict) -> str:
    return (
        f"Escola municipal em {school['city']}/{school['uf']}. "
        f"Indicadores externos: IDEB regional é {school['mun_ideb_af']}, "
        f"Taxa de abandono na região: {school['mun_taxa_abandono']:.1%}. "
        f"A distorção idade-série local bate {school['mun_distorcao_ef']:.1%} e "
        f"o município tem proficiência adequada de {school['mun_lp_adequado']:.1%} em Língua Portuguesa."
    )
```

#### Task 2.2 — Neo4j Vector Writer (`src/embeddings/neo4j_writer.py`)

Gravando os embeddings massivos no Neo4j através das sessões do driver de forma segura.

```python
def build_school_text(school: dict) -> str:
    return (
        f"Escola em {school['city']}/{school['uf']}, "
        f"IDEB: {school['mun_ideb_af']}, "
        f"taxa abandono regional: {school['mun_taxa_abandono']:.1%}, "
        f"IDHM estado: {school['state_idhm']}, "
        f"RDPC: R${school['state_rdpc']:.0f}, "
        f"distorção EF: {school['mun_distorcao_ef']:.1%}, "
        f"LP adequado: {school['mun_lp_adequado']:.1%}"
    )
```

**Verify:**
```cypher
MATCH (s:Student) WHERE s.embedding IS NOT NULL RETURN count(s)
MATCH (s:School)  WHERE s.embedding IS NOT NULL RETURN count(s)
// Validar se o HNSW index responde (via call db.index.vector.queryNodes)
```

---

### 🔶 Fase 3 — Modelos ML

**Objetivo:** Treinar, avaliar e registrar os três modelos principais.

#### Task 3.1 — Dropout Classifier

**Arquivo:** `src/ml/models/dropout_classifier.py`

```python
# Features em ordem de importância esperada (validar via SHAP)
FEATURES_EVASAO = [
    # Internas — maior poder preditivo imediato
    'taxa_ausencia',
    'variacao_nota',           # queda de nota b1→b4
    'n_recuperacoes_finais',
    'bolsa_familia',
    'n_doencas',
    'residence_zone',
    'ethnicity',
    # Externas IBGE — contexto estrutural
    'razao_abandono_vs_regional',   # feature derivada (interno/externo)
    'mun_pct_fora_escola',
    'mun_taxa_abandono',
    'mun_atraso_2_fund',
    'state_ppob',
    'state_rdpc',
    'state_idhm',
]

TARGET = 'evadiu'  # 0/1 derivado de Avaliation.situation ou enrollment_status
```

**Estratégia de treino:**
- Split temporal: treinar em anos letivos anteriores, validar no mais recente
- Balanceamento: `class_weight='balanced'` no XGBoost (evasão é minoria)
- Threshold: otimizar F1 para Recall ≥ 0.75 (falso negativo é pior que falso positivo)
- Baseline comparativo: modelo sem features IBGE → quantificar ganho de AUROC

**Verify:**
```
AUROC ≥ 0.82 no holdout temporal
Recall ≥ 0.75 (threshold ajustado)
Ganho de AUROC com IBGE vs sem IBGE: registrar no MLflow
```

#### Task 3.2 — Grade Regressor

**Arquivo:** `src/ml/models/grade_regressor.py`

```python
FEATURES_NOTA = [
    'media_nota_b1', 'media_nota_b2', 'media_nota_b3',  # histórico de notas
    'n_recuperacoes_finais',
    'taxa_ausencia',
    'discipline_name',         # feature categórica
    'teacher_id',              # efeito professor
    # Externos
    'mun_ideb_af',
    'mun_lp_adequado',
    'mun_mt_adequado',
    'state_idhm',
]

TARGET = 'final_mean'  # nota final prevista
```

> Usar apenas alunos do Ensino Fundamental — `StudentDiscipline` tem notas por bimestre.

**Verify:** `RMSE ≤ 1.5`, `R² ≥ 0.60`

#### Task 3.3 — Risk Clusterer

**Arquivo:** `src/ml/models/risk_clusterer.py`

Entrada: embeddings de alunos (Fase 2) + features numéricas normalizadas.

```python
# Perfil esperado de clusters (validar após treino)
CLUSTER_PROFILE_TEMPLATE = {
    'low_risk':    {'taxa_ausencia': '<5%',  'mun_taxa_abandono': '<5%',  'state_idhm': '>0.75'},
    'medium_risk': {'taxa_ausencia': '5-15%', 'mun_taxa_abandono': '5-10%', 'state_idhm': '0.65-0.75'},
    'high_risk':   {'taxa_ausencia': '>15%', 'mun_taxa_abandono': '>10%', 'state_idhm': '<0.65'},
    'structural':  {'bolsa_familia': True,   'mun_pct_fora_escola': '>20%', 'n_doencas': '>1'},
}
```

Escreve `Student.risk_cluster` de volta no Neo4j.

**Verify:** `Silhouette ≥ 0.35`, clusters com perfil IBGE interpretável e nomeado

#### Task 3.4 — SHAP Explainability

**Arquivo:** `notebooks/04_shap_analysis.ipynb`

Análise crítica com separação interna vs externa:

```python
# Separar importâncias
internal_features = ['taxa_ausencia', 'variacao_nota', 'n_recuperacoes_finais',
                     'bolsa_familia', 'n_doencas', 'residence_zone', 'ethnicity']
ibge_features     = ['razao_abandono_vs_regional', 'mun_pct_fora_escola',
                     'mun_taxa_abandono', 'mun_atraso_2_fund',
                     'state_ppob', 'state_rdpc', 'state_idhm']

shap_internal = shap_values[:, [f in internal_features for f in feature_names]].sum()
shap_ibge     = shap_values[:, [f in ibge_features     for f in feature_names]].sum()

print(f"Contribuição IBGE no modelo: {shap_ibge / (shap_internal + shap_ibge):.1%}")
```

**Verify:** Features IBGE presentes no top-10 global; contribuição IBGE documentada no MLflow

#### Task 3.5 — Análise de Equidade Racial e de Gênero

**Arquivo:** `notebooks/05_equity_analysis.ipynb`

```python
# Cruzar cluster de risco com desagregações IBGE do nó State
# Perguntas a responder:
# 1. Alunos pretos/pardos estão concentrados em municípios com maior gap racial IBGE?
# 2. Meninas em municípios com maior disparidade de gênero têm diferente padrão de evasão?

# Dados do grafo:
# Student.ethnicity ↔ State.preto_pnad_rdpc / pardo_pnad_rdpc
# Student.gender    ↔ State.mulher_pnad_t_flmed / homem_pnad_t_flmed
```

---

### 🔶 Fase 4 — RAG Pipeline

**Objetivo:** Responder as 12 perguntas do gestor em linguagem natural, com contexto completo do grafo.

#### Task 4.1 — Retriever (`src/rag/retriever.py`)

```python
def get_student_context(student_id: str) -> dict:
    """Retorna contexto completo do aluno via grafo, incluindo dados IBGE."""
    # Cypher: Student + Health + Disciplines + Classes + School + Municipality + State
    pass

def find_similar_students(student_id: str, top_k: int = 5) -> list[dict]:
    """
    Busca vetorial por alunos similares.
    Retorna cada similar com seu contexto Municipal IBGE para comparação.
    """
    # Neo4j Vector Index: db.index.vector.queryNodes('student_embedding', top_k, embedding)
    # Para cada similar: incluir mun.qedu_ideb_af, mun.qedu_taxa_abandono, state.pnad_idhm
    pass
```

**Verify:** `< 2s` por consulta no P95

#### Task 4.2 — Context Builder (`src/rag/context_builder.py`)

Template de bloco IBGE no prompt — gerado automaticamente para qualquer aluno/escola:

```python
def build_ibge_block(municipality: dict, state: dict, student: dict) -> str:
    """Formata o bloco de contexto regional para o prompt do LLM."""
    ethnicity = student.get('ethnicity', '').lower()
    racial_context = ""
    if 'pret' in ethnicity or 'pard' in ethnicity:
        key = 'preto' if 'pret' in ethnicity else 'pardo'
        racial_context = (
            f"\nContexto racial ({key}):\n"
            f"  RDPC {key}: R${state.get(f'{key}_pnad_rdpc', 'N/A')}\n"
            f"  Analfabetismo {key} 15+: {municipality.get('atl_negro_analf15m', 'N/A')}%"
        )

    return f"""
=== CONTEXTO REGIONAL ({municipality['name']}/{state['sigla']}) ===
IDHM Estado (2010): {state['pnad_idhm']} | Educação: {state['pnad_idhm_e']}
Renda per capita estado: R$ {state['pnad_rdpc']:.0f} | Gini: {state['pnad_gini']:.2f}
% pobres no estado: {state['pnad_ppob']:.1%}

IDEB Anos Finais EF ({municipality['name']}): {municipality.get('qedu_ideb_af', 'N/D')}
Taxa de abandono municipal: {municipality.get('qedu_taxa_abandono', 0):.1%}
Distorção idade-série EF: {municipality.get('qedu_distorcao_ef_total', 0):.1%}
% adequado em LP: {municipality.get('qedu_lp_adequado_af', 0):.1%}
% adequado em Matemática: {municipality.get('qedu_mt_adequado_af', 0):.1%}
Permanência de coorte: {municipality.get('qedu_permanencia', 0):.1%}
{racial_context}
"""
```

**Verify:** 100% dos prompts gerados contêm o bloco IBGE com dados não nulos

#### Task 4.3 — Pipeline RAG Completo (`src/rag/rag_pipeline.py`)

```python
# Orquestração: pergunta → retrieval → context → LLM → resposta
def ask(question: str, student_id: str | None = None,
        school_id: str | None = None) -> str:
    context = get_student_context(student_id) if student_id else get_school_context(school_id)
    similar = find_similar_students(student_id) if student_id else []
    ibge_block = build_ibge_block(context['municipality'], context['state'], context['student'])
    prompt = build_prompt(question, context, similar, ibge_block)
    return llm.invoke(prompt)
```

---

### 🔶 Fase 5 — MLOps

**Objetivo:** Garantir que os modelos se mantêm confiáveis ao longo do tempo.

#### Task 5.1 — MLflow Setup (`src/ml/mlops/mlflow_client.py`)

```python
# O que logar por experimento
def log_experiment(model, metrics: dict, features: list, ibge_gain: float):
    mlflow.log_params({
        'n_features_internal': len([f for f in features if f not in IBGE_FEATURES]),
        'n_features_ibge': len([f for f in features if f in IBGE_FEATURES]),
    })
    mlflow.log_metrics({
        'auroc': metrics['auroc'],
        'recall': metrics['recall'],
        'f1': metrics['f1'],
        'auroc_gain_from_ibge': ibge_gain,   # diferença vs modelo sem IBGE
    })
    mlflow.sklearn.log_model(model, 'dropout_classifier')
```

**Verify:** Experimentos aparecem no MLflow UI com comparativo interno vs IBGE

#### Task 5.2 — Drift Detector (`src/ml/mlops/drift_detector.py`)

```python
# Monitorar três tipos de drift
DRIFT_MONITORS = {
    'feature_drift': [
        'taxa_ausencia',       # pode mudar com políticas escolares
        'mun_taxa_abandono',   # muda quando QEdu atualiza dados
        'state_pnad_rdpc',     # muda quando Atlas PNAD atualiza
    ],
    'prediction_drift': 'distribuição de scores de risco por escola',
    'label_drift':  'taxa real de evasão por mês vs taxa prevista',
}
```

> **Atenção especial:** quando o DAG `neo4j_ibge_migration` rodar novamente (nova edição do QEdu),
> as features `mun_*` e `state_*` mudarão. Esse evento deve disparar drift check automático
> e recalibração do threshold do modelo.

**Verify:** DAG `dag__ml_drift_detection` roda semanalmente e gera relatório Evidently

#### Task 5.3 — Auto-Retrain DAG (`dags/dag__ml_retrain.py`)

```
Fluxo do DAG de retreino:
  1. check_ibge_freshness          ← verifica se Municipality/State foram atualizados
  2. extract_features_from_neo4j  ← query Cypher → Parquet
  3. validate_feature_quality     ← % nulos por feature, distribuição
  4. train_dropout_classifier     ← XGBoost com novo dataset
  5. train_grade_regressor        ← GBM com novo dataset
  6. evaluate_challenger          ← AUROC, Recall, F1
  7. promote_or_reject            ← champion/challenger logic
```

#### Task 5.4 — Champion/Challenger (`src/ml/mlops/champion_challenger.py`)

```python
def should_promote(challenger_metrics: dict, champion_metrics: dict) -> bool:
    """
    Promove challenger se:
    - AUROC > champion + 0.01 (mínimo de ganho)
    - Recall não caiu abaixo de 0.75 (recall mínimo para não perder alunos em risco)
    - F1 não caiu (balanceamento geral mantido)
    """
    return (
        challenger_metrics['auroc'] > champion_metrics['auroc'] + 0.01
        and challenger_metrics['recall'] >= 0.75
        and challenger_metrics['f1'] >= champion_metrics['f1'] - 0.02
    )
```

---

### 🔶 Fase 6 — API FastAPI

**Objetivo:** Expor todos os modelos e o RAG via endpoints REST.

#### Endpoints

| Endpoint | Input | Output |
|----------|-------|--------|
| `POST /predict/dropout/{student_id}` | student_id | `{probability, risk_level, top_factors, regional_context}` |
| `POST /predict/grade/{student_id}/{discipline}` | ids | `{predicted_grade, confidence, benchmark_municipal}` |
| `POST /ask/student` | `{student_id, question}` | Resposta RAG com contexto IBGE |
| `POST /ask/school` | `{school_id, question}` | Resposta RAG com contexto regional |
| `GET /report/school/{school_id}` | school_id | Relatório completo: quartil risco, clusters, SHAP, IBGE |
| `GET /health` | — | Status dos modelos e do grafo |

#### Response model de evasão (exemplo)

```json
{
  "student_id": "abc123",
  "probability": 0.84,
  "risk_level": "alto",
  "top_factors": [
    {"feature": "taxa_ausencia",            "impact": "+0.31"},
    {"feature": "variacao_nota",            "impact": "+0.18"},
    {"feature": "razao_abandono_vs_regional","impact": "+0.14"},
    {"feature": "mun_pct_fora_escola",      "impact": "+0.09"}
  ],
  "regional_context": {
    "municipio": "Moju/PA",
    "ideb_af": 3.9,
    "taxa_abandono_municipal": 0.112,
    "state_idhm": 0.646,
    "pct_fora_escola_regional": 0.26
  }
}
```

---

## ✅ Critérios de Sucesso por Fase

| Fase | Critério | Métrica |
|------|----------|---------|
| Fase 1 | Feature coverage | ≥ 90% dos alunos com `mun_ideb_af` não nulo |
| Fase 2 | Embedding coverage | 100% de alunos e escolas com vetor |
| Fase 2 | Vector search quality | Top-5 similares com cosine ≥ 0.80 |
| Fase 3 | Dropout Classifier | AUROC ≥ 0.82, Recall ≥ 0.75 |
| Fase 3 | Grade Regressor | RMSE ≤ 1.5, R² ≥ 0.60 |
| Fase 3 | Risk Clusterer | Silhouette ≥ 0.35, clusters com perfil IBGE interpretável |
| Fase 3 | SHAP | Features IBGE no top-10 global; ganho de AUROC documentado |
| Fase 4 | RAG latência | P95 ≤ 15s por query |
| Fase 4 | RAG qualidade | 100% das respostas contêm bloco IBGE com dados não nulos |
| Fase 4 | RAG cobertura | 12/12 perguntas do gestor respondíveis |
| Fase 5 | MLOps | Retreino automático funcional; drift detectado antes de degradação |
| Fase 5 | Champion/Challenger | Promoção correta validada com dados históricos |
| Fase 6 | API | Todos os endpoints com P95 ≤ 500ms (exceto RAG) |

---

## 📌 Ordem de Execução

```
✅ Fase 0  IBGE no Neo4j (dag__neo4j_ibge_migration — concluída)
    │
    ▼
🔶 Fase 1  Vector Indexes + Feature Extractor
    │
    ▼
🔶 Fase 2  Embeddings (Student + School)
    │
    ├──────────────────────────────────┐
    ▼                                  ▼
🔶 Fase 3  ML Models               🔶 Fase 4  RAG Pipeline
    │       (Treino + SHAP)              │       (Retriever + Context + LLM)
    │                                    │
    └──────────────┬─────────────────────┘
                   ▼
🔶 Fase 5  MLOps (MLflow + Drift + Retrain DAG)
                   │
                   ▼
🔶 Fase 6  API FastAPI (exposição de tudo)
```

> Fases 3 e 4 podem rodar em paralelo após Fase 2.
> Fase 5 deve ser configurada junto com Fase 3 (logar experimentos desde o primeiro treino).
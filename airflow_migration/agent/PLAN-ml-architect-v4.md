# PLAN: MLOps Refinement & ML Architecture V4

> **Slug:** `mlops-refinement`
> **Tipo do Projeto:** DATA SCIENCE / MLOps / BACKEND
> **Base de Conhecimento:** Integrado e enriquecido a partir de `plan_ml01.md`, `ML-layer_v3.md`, `neo4_schema_and_tips.md`, `Q_risco_evasao.md` e `Q_risco_evasaoQ2.md`
> **Status:** PLANEJAMENTO
> **Objetivo:** Estabelecer o padrão definitivo e detalhado para Feature Engineering, código produtivo de ML, Orquestração e Serving na stack Neo4j + Airflow + MLflow + FastAPI.

---

## 1. Princípios de Arquitetura e Padrões de Código

Para garantir que o código de Machine Learning seja tratável como software de produção, as seguintes regras são inegociáveis:

1. **Single Responsibility (SRP):** Funções com mais de 40 linhas são sinal de alerta. Transformações são separadas de extrações. `neo4j_extractor.py` NUNCA deve fazer lógica de `XGBoost`.
2. **Tratamento Cypher O(N):** TODO acesso ao banco usa a estratégia `collect(DISTINCT stu) -> UNWIND -> agregar` (padrão Isolado) para evitar produto cartesiano e _timeouts_ em propriedades opcionais como notas e faltas.
3. **Data Leakage & Time-Travel Prevention:** Split temporal é OBRIGATÓRIO (`ano_letivo < test_year` para treino). Proibido usar `train_test_split` aleatório em séries temporais de educação.
4. **Tipagem e Contratos:** O Feature Set é um contrato. `schema.py` define o modelo estrito de entrada usando listas descritivas de colunas. Todas as funções Python usam Type Hints rígidos com retorno definido. Pydantic é recomendado para validação na camada de Serving.
5. **Observabilidade ML:** MLflow não é usado apenas para auroc; logging estruturado e explicabilidade (SHAP global e local) devem ser versionados por artefato.
6. **Privacidade (PII):** PROIBIDO logar `student_id`, nome ou metadados de identificação. Nomes são serializados apenas nos prompts de RAG temporários, nunca armazenados estáticos fora do Neo4j.

---

## 2. Estrutura Padrão Produtiva (Repositório)

```text
src/ml/
├── features/
│   ├── neo4j_extractor.py       # Acesso Cypher → Pandas (Retorna raw dataframe)
│   ├── feature_pipeline.py      # sklearn Pipeline: imputer → label_enc → scaler
│   ├── derived_features.py      # Lógica de cálculo de Grupos Proximidade e Scores
│   └── schema.py                # Constantes: ID_COLS, TARGET_EVASAO, EXPECTED_TYPES
├── models/
│   ├── base_model.py            # Interfaces de BaseClassifier/BaseRegressor
│   ├── dropout_classifier.py    # XGBoost + Tratamento scale_pos_weight
│   ├── grade_regressor.py       # GBM para regressão de notas EF2
│   └── risk_clusterer.py        # KMeans (Elbow/Silhouette) + PCA + Writeback Neo4j
├── evaluation/
│   ├── metrics.py               # Funções determinísticas: auroc, f1, precision, recall
│   └── explainability.py        # SHAP Summary (Plots) + SHAP Local (Dicionário JSON API)
├── mlops/
│   ├── mlflow_experiment.py     # Wrapper para MLflow log_run()
│   ├── model_registry.py        # Gerenciamento Staging → Production
│   ├── drift_detector.py        # Evidently AI (Feature/Label/Concept drift)
│   └── champion_challenger.py   # Lógica algorítmica de threshold para Replace Model
└── training/
    ├── train_evasao.py          # Entrypoint de treinamento diário/semanal
    └── train_notas.py
dags/
├── dag__ml_feature_store.py     # Atualiza cache parquets diários no Data Lake
├── dag__ml_retrain.py           # Pipeline Orquestrado (Extractor → Train → Compare → Promote)
└── dag__ml_drift_monitor.py     # Executa Drift Alerting para Slack/Teams
```

---

## 3. Schema.py e Feature Engineering (O Contrato)

A Engenharia de features aproveita 100% o contexto de sub-scores (Painel Executivo de Escola) e Grupos de Proximidade construídos nos relatórios dos gestores.

### 3.1 Construção de Targets
- `target_evasao` (Binário 0/1): Se `taxa_ausencia > 0.25` OU `enrollment_status` inativo.
- `target_nota` (Float 0-10): `final_mean` normalizada (dividida por 10 se estivesse na antiga escala 0-100).
- `target_reprovacao` (Binário 0/1): `target_nota < 5.0`.

### 3.2 Listas de Features Nativas e Contextuais

```python
# src/ml/features/schema.py
ID_COLS = ["student_id", "school_id", "uf", "materia"]

DEMO_FEATURES = ["gender_bin", "ethnicity_enc", "has_deficiency", "bolsa_familia", "residence_zone_enc"]
HEALTH_FEATURES = ["has_health_record", "n_doencas_criticas", "has_malnutrition"] # Agregados de h.malnutrition, etc
FREQ_FEATURES = ["taxa_ausencia", "total_faltas_abs", "falta_critica"]
# Novos Contextos de Risco Extraídos Analiticamente:
SCHOOL_SCORE_FEATURES = ["school_presenca_score", "school_desempenho_score", "school_equidade_score", "school_cobertura_score"]
STUDENT_PROXIMITY_FEATURES = ["distancia_corte_beira", "distancia_corte_intermediario"] 

MUNICIPAL_FEATURES = ["muni_freq_liq_fund", "muni_atraso_2anos", "muni_analf_adulto", "muni_delta_freq_turma"]
STATE_QEDU_FEATURES = ["est_ideb_af", "est_taxa_abandono", "est_distorcao_serie", "est_pct_fora_escola"]
STATE_PNAD_FEATURES = ["est_analf_negro", "est_analf_branco", "est_gap_analf_gender"]
```

**Estratégias de Imputação (`feature_pipeline.py`):**
- **Notas nulas:** Imputar com `-1`. Uma escola que não lança notas é um sinal comportamental profundo na rede.
- **IBGE Municipal ausente:** Fallback de `avg(UF)`. Não use média global aleatória, o estado diz mais.

---

## 4. O Pipeline Cypher -> Pandas (`neo4j_extractor.py`)

A performance de Extração deve seguir a **Regra Anti-Cartesiana (CALL Collections)** listada em `neo4_schema_and_tips.md`. O carregamento das estatísticas geográficas (School `->` Geograph `->` Municipality `->` State) deve ser executado no bloco `WITH` base.

### Pseudo-Código Padrão
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
WITH sch, m, st, ... (extração completa IBGE)

// COLETA ALUNOS
CALL (sch) {
  MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
  WHERE cr.grade_level IN ['NO 6* ANO','NO 7* ANO','NO 8* ANO','NO 9* ANO']
  RETURN collect(DISTINCT stu) AS ListaTurma
}

// DIMENSÃO NOTAS (Isolada)
CALL (ListaTurma) {
  UNWIND ListaTurma AS stu
  OPTIONAL MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline) ...
  RETURN count(Nota) AS N_Notas, round(avg(Nota), 2) AS Media_Nota ...
}
```

O Extrator em Python:
```python
def extract_students_ef2(self, year: int) -> pd.DataFrame:
    # Lê todo Cypher estruturado 
    query = load_query("extract_ef2_pipeline.cypher")
    query = query.replace("{YEAR_FILTER}", f"cr.year = {year}")
    
    with self._driver.session() as session:
         records = session.run(query)
         df = pd.DataFrame([r.data() for r in records])
         return df
```

---

## 5. Modelos ML: Padrões Operacionais

### 5.1 XGBoost Dropout Classifier (`dropout_classifier.py`)
Modelos em educação têm classes absurdamente desbalanceadas (A Evasão geralmente orbita 5 a 15%). 
A normalização é obrigatória:
- **`scale_pos_weight`**: Auto-computado via `n_negative_samples / max(n_positive_samples, 1)`.
- **Split Temporal**: Validação cruzada proibida (K-Fold clássico quebra o conceito de fluxo do ano letivo). Fazer "Walk-forward validation" testando o ano recente (`2024`) treinando nos anteriores (`2021`, `2022`, `2023`).
- **Métricas Finais Mínimas**: AUROC $\ge$ 0.82, Recall $\ge$ 0.75 (*O pior cenário de um modelo de risco educativo é o falso negativo - perder um aluno em risco*).

### 5.2 KMeans Risk Clusterer + DBSCAN (`risk_clusterer.py`)
- Standard Scaler obrigatório antes.
- Aplicação de `PCA` (retendo 95% variância) para otimizar espaço vetorial denso e eliminar ruído das 50 features.
- Gravação explícita via driver Neo4j. O KMeans deve exportar para o banco: `stu.risk_cluster` e `stu.risk_score`.

### 5.3 OBRIGATÓRIO: Explicação de Resultados via SHAP (`explainability.py`)
A rede municipal de ensino e diretores não confiam em caixa-preta.
- O entrypoint exporta um dicionário JSON Local Waterfall_Plot dos motivos de evasão.
- `Explainer` armazena no MLflow o ranking para checagem corporativa: *As features de IBGE devem aparecer nas "Top 10" macro. A ausência (`taxa_ausencia`) geralmente encabeça o TOP 1.*

---

## 6. MLOps e Orquestração Airflow

O framework de versionamento foca numa promoção robusta (*Champion / Challenger*).

### 6.1 Detecção de Drift (`drift_detector.py`)
Ferramenta: **Evidently AI**
1. **Data/Feature Drift**: Alguém mudou regra de chamada escolar ("agora toleramos mais faltas") mudando a distribuição de `taxa_ausencia`? Dispara Notificação para Data Scientists e gera Report HTML (salvo no cache).
2. **Concept Drift**: A correlação entre renda IBGE e notas inverteu.
Se `% Drifted Features > 30%` $\to$ Push via XCom informando Retreino obrigatório no Airflow.

### 6.2 O DAG Completo (`dag__ml_retrain.py`)
O ciclo semanal (roda Domingo à noite):
```text
(1) sensor_dados_ibge_novos
(2) extract_neo4j_features >> feature_quality_expectation_check
(3) split_temporal_dataset
(4) train_xgboost_challenger_model
(5) generate_shap_and_log_mlflow
(6) compare_champion_challenger 
      ↳ threshold algorítmico: (Δ AUROC > +0.01) E (Recall Challenger > 0.75) E (Queda_F1 < 0.02)
(7) promote_production_model (if approved)
```

---

## 7. RAG Integrado (Serving)

O modelo treinado deve ser consumível dinamicamente pela interface FastAPI (`/predict/dropout/{sys_student}`) em conjunto com o RAG Educacional.

As perguntas do RAG (Ex. *"Por que a turma 8ºB está com Score Saude Critico?"*) devem montar prompts ricos aproveitando os vetores:
- Enriquecer bloco `CONTEXTO IBGE` gerado on-the-fly (`src/rag/context_builder.py`).
- Extrair os `SHAP_TOP_Fatores` providos pelo JSON Explainability para fundamentar a predição.

---

## 8. Checklist de Aceite do Arquiteto (Go/No-Go)

- [ ] Todas as chamadas Cypher respeitam a técnica de isolamento O(N) via Múltiplos `CALL { ... }`.
- [ ] Não há `train_test_split` aleatórios; as classes python implementam divisórias por temporalidade (`ano_letivo`). 
- [ ] Fallbacks e Tratamentos de `null` em propriedades de `Municipality` estão codificados nativamente via substituição mediana da Estadual (`UF_Media`).
- [ ] Métricas em classes Python são determinísticas (pydantic base) não emitindo dicionários abertos na API de Scoring.
- [ ] DAG Airflow implementa lógica restrita de Champion/Challenger no Registro do MLflow antes de transitar modelo de "Staging" para "Production".
- [ ] O RAG retorna latência `< 15 segs` puxando dados vetoriais de Similaridade, e Predições Endpoints respondem sub-500ms.

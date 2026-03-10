# Sistema de Alerta Precoce Educacional (EWS) — Documento de Arquitetura
**Audiência:** CTO / Tech Lead
**Versão:** 1.0 — Consolidado a partir de PLAN-ML-01, PLAN-ML-02, REGRAS_E_DECISOES, ANALYSIS_EF2
**Escopo:** Pipeline ML + RAG + LLM sobre grafo Neo4j educacional

---

## O Problema que Estamos Resolvendo

Gestores educacionais — do professor ao secretário estadual — tomam decisões sobre intervenção pedagógica com base em intuição ou relatórios atrasados. Um aluno que vai evadir no 3º bimestre poderia ter sido retido no 1º, se alguém soubesse olhar os sinais certos. Uma turma inteira pode estar afundando por causa de um único fator estrutural (ausência de diário eletrônico, concentração de vulnerabilidade socioeconômica), e ninguém vê isso de forma agregada.

Este sistema responde três perguntas fundamentais com dados reais do grafo:

1. **"Quais alunos do EF1 estão em rota de evasão ou reprovação?"** → Classificação XGBoost
2. **"No EF2, o que realmente explica a nota baixa de um aluno?"** → Regressão Gradient Boosting
3. **"Onde, em qual turma e município, está concentrado o maior risco?"** → RAG + LLM sobre Neo4j

O output final não é um número. É uma **resposta interpretável em português**, contextualizada com benchmarks IBGE, QEdu e PNAD, entregue para o gestor certo no nível hierárquico certo.

---

## Fundamento: Por Que a Granularidade é o Centro do Design

O sistema opera em **cinco granularidades hierárquicas**. Esta não é uma decisão técnica — é uma decisão pedagógica. Cada nível tem um gestor diferente, uma pergunta diferente e um tipo de intervenção diferente.

```
ESTADO
  └── MUNICÍPIO
        └── ESCOLA
              └── TURMA
                    └── ALUNO
```

| Granularidade | Quem usa | Pergunta típica | Fonte de dados |
|---|---|---|---|
| **Aluno** | Orientador / professor | "Por que João tem 85% de risco?" | Grafo Neo4j + vector similarity |
| **Turma** | Coordenador pedagógico | "Qual turma do 7º ano precisa de reforço?" | Q15 God Matrix + Q8 composite risk |
| **Escola** | Gestor local | "Como nossa escola está vs o município?" | Q_SAUDE_ESCOLA + IBGE municipal |
| **Município** | Secretaria municipal | "Quais escolas estão em colapso?" | Agregação escola→município + IBGE |
| **Estado** | SEDUC | "Como nosso estado compara vs IDEB nacional?" | QEdu + PNAD racial + PNAD gênero |

**A regra de ouro:** nenhuma pergunta de um nível é respondida com dados do nível errado. Um gestor de escola não vê dados de alunos nominais. Uma SEDUC não recebe lista de turmas — recebe ranking de municípios.

---

## Camada 1 — Modelos Preditivos de ML

### 1.1 EF1: XGBoost Classifier (Classificação de Evasão)

**O que prediz:** Probabilidade de um aluno do Ensino Fundamental I evadir ou reprovar no ano letivo.

**Por que XGBoost e não outro modelo:**
O dataset tem ~7,7 milhões de aprovações contra ~24 mil evasões — razão de 1:268. O XGBoost resolve isso nativamente via `scale_pos_weight`:

```python
scale_pos_weight = n_negativos / n_positivos  # ~268
# O modelo "pune" mais erros na classe minoritária (evasão)
# sem precisar de dados sintéticos (SMOTE) que distorceriam a distribuição real
```

**Por que não GradientBoosting aqui:** XGBoost lida melhor com o desequilíbrio extremo de classes via esse parâmetro nativo. GradientBoosting padrão requereria undersample mais agressivo.

**Decisão de downsampling (Defesa contra OOM — Exit Code 137):**
Com 7M+ de linhas, o container Docker colapsava por falta de RAM. A regra adotada:
- Mantém **todos** os ~24k alunos em risco (Target=1) — são valiosos, não podem ser perdidos
- Sorteia aleatoriamente **1 milhão** dos 7,7M aprovados (Target=0)
- Dataset final: ~1,024M registros — nuances demográficas preservadas, memória controlada
- `import gc; gc.collect()` forçado após cada etapa pesada

**Features de entrada (EF1):**
- `taxa_ausencia` — frequência relativa ao ano
- `total_faltas_abs` — faltas absolutas acumuladas
- `nota_global_norm` — média global normalizada (base 10)
- `bolsa_familia` — flag socioeconômica
- `deficiency` — flag PCD
- `residence_zone` — rural/urbano
- `pct_saude_risco` — proporção com condição de saúde (malnutrição, anemia, diabetes)
- `muni_analf_adulto` — contexto IBGE do município
- `est_taxa_abandono` — contexto QEdu do estado

**Output:** `risco_evasao_prob` (0.0–1.0) por `student_id`

---

### 1.2 EF2: Gradient Boosting Regressor (Predição de Nota Contínua)

**O que prediz:** Média final do aluno no intervalo contínuo 0.0–10.0, por disciplina, ao fim do ano letivo.

**Por que Regressão e não Classificação aqui:**
No EF2, a pergunta deixa de ser binária (vai evadir ou não) e passa a ser "qual nota ele vai fechar?". A regressão permite identificar alunos que vão fechar com 4.8 — à beira da reprovação, alto retorno de intervenção — vs alunos com 2.1 que precisam de intervenção estrutural.

**Proteção contra NaN (SimpleImputer no Pipeline Scikit-Learn):**
Alunos sem histórico de nota no G1/G2 quebravam o modelo (`input contains NaN`). Solução:
```python
Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('model', GradientBoostingRegressor(...))
])
```
O median imputer preenche passivamente com a mediana sem viciar as árvores de decisão.

**As 6 variáveis mais preditivas (por importância algorítmica real):**

| Variável | Importância | Por quê importa |
|---|---|---|
| `pct_disciplinas_abaixo5` | **66,15%** | Efeito bola de neve — G1/G2 com muitas disciplinas em risco prediz colapso no final |
| `nota_mat_norm` | **17,23%** | Correlação +0,65 com nota final geral. Menor média de todas (6,37). 8,7% dos alunos abaixo de 5 |
| `nota_dispersao` | **6,46%** | Alunos com alta variância entre disciplinas (10 em Artes, 3 em Português) colapsam nos bimestres finais |
| `nota_lp_norm` + `nota_geo_norm` | **~5,2%** | Capacidade leitora irradia para todas as outras matérias |
| `taxa_ausencia` + `total_faltas_abs` | **~2,24%** | Ofensores demográficos — sem notas na mesa, são os maiores preditores |
| `est_taxa_abandono` + demografia | **~2%** | Contexto estrutural do município/estado impõe limitador indireto |

**Decisão crítica de feature engineering — O Paradoxo do Parquet:**
O pipeline de features foi **proibido** de incluir strings de turma/escola no treinamento. Nomes como `"Turma 502"` ou `"EMEIF JOSE PEREIRA"` gerariam dezenas de milhares de colunas dummy via One-Hot Encoding, inflacionando o tensor e diluindo o peso limpo da nota de matemática. O modelo treina **cego**, usando apenas `student_id` numérico e flags.

A localização geográfica real é reintroduzida **depois** da predição via Extrator de Ponte — uma query Cypher no Neo4j que faz o join `UUID → Classroom → School → Municipality`.

**Output:** `nota_predita_final` (0.0–10.0) por `student_id × discipline_name`

---

### 1.3 O que os Modelos Sozinhos NÃO Respondem

Os modelos entregam números. Eles **não explicam** ao gestor:
- Por que o risco é alto
- O que fazer agora
- Como a escola compara com vizinhas similares
- Se o problema é estrutural (turma inteira) ou individual

É aqui que entra a Camada 2.

---

## Camada 2 — RAG + LLM: Da Predição à Resposta Interpretável

### 2.1 O que é RAG neste contexto

RAG aqui não é busca em documentos PDF. É **síntese de contexto multi-fonte e multi-granularidade**. O fluxo é:

```
Pergunta do gestor
      ↓
identify_granularity()     → detecta: aluno / turma / escola / município / estado
      ↓
Retriever (Cypher puro)    → busca dados no Neo4j — sem LLM, sem API key
      ↓
ContextBuilder             → serializa em texto estruturado ≤ 16.000 chars
      ↓
Prompt Template            → instrui o LLM com o formato esperado por granularidade
      ↓
LLM remoto (OpenAI GPT)    → sintetiza resposta em português com CONFIANÇA
      ↓
RAGResponse                → answer + latency + quality + granularity
```

**O LLM nunca acessa o banco. Toda lógica de busca é determinística e testável sem API key.**

---

### 2.2 Separação Local vs Remoto

Esta é uma decisão de custo e volume, não de qualidade:

| Componente | Onde roda | Por quê |
|---|---|---|
| **Embedding** (`sentence-transformers`) | Local — container Docker | Volume alto (N alunos por refresh semanal). Custo zero. ~90MB em RAM |
| **LLM de síntese** (OpenAI GPT-4o-mini) | Remoto — API paga | Volume baixo (perguntas de gestores, não N alunos). Custo por request aceitável |

Modelo de embedding: `paraphrase-multilingual-MiniLM-L12-v2` — 384 dimensões, multilingual, otimizado para português.

Trocar de GPT para Gemini ou Ollama local: `LLM_PROVIDER=gemini` — sem tocar no código.

---

### 2.3 O Que o RAG Responde por Granularidade

#### Aluno
- "Por que João tem 85% de risco de evadir?"
- "O que aconteceu com alunos com o mesmo perfil?"
- "Esse aluno tem condições de saúde que explicam as faltas?"
- "Qual a trajetória de notas do G1 para G2?"

**Como funciona:** `get_student_context()` puxa perfil + frequência + notas + saúde + IBGE do município. `find_similar_students()` usa o vector index (384d) para encontrar os 5 alunos mais similares no grafo com desfecho conhecido (evadiu / não evadiu). O LLM recebe tudo isso e explica em linguagem natural.

#### Turma
- "Qual turma do 7º ano precisa de reforço urgente?"
- "A turma está pior que o esperado para o município?"
- "Quantos alunos da turma são de zona rural + Bolsa Família?"

**Como funciona:** `get_classroom_context()` executa Q8 composite risk — `soma_sinais_risco = 0.40×faltas + 0.35×notas + 0.25×saúde` — sobre a lista de alunos da turma. Retorna classificação CRÍTICO / ALERTA / MODERADO.

#### Escola
- "Como nossa escola está comparada ao município?"
- "Qual dimensão está puxando nosso score de saúde pra baixo?"
- "Alunos de Bolsa Família têm nota muito menor que os outros?"
- "Escolas similares à nossa conseguem resultados melhores?"

**Como funciona:** `get_school_context()` implementa Q_SAUDE_ESCOLA — score 0–100 em 4 dimensões (35% presença + 35% desempenho + 20% equidade + 10% cobertura). `find_similar_schools()` usa vector index de escola para benchmark com pares similares.

#### Município
- "Quais escolas do município estão em colapso?"
- "Quantas escolas ainda não têm diário eletrônico?"
- "A desigualdade racial na rede é preocupante?"

**Como funciona:** `get_municipality_context()` agrega métricas de todas as escolas + benchmarks IBGE municipal + PNAD racial do estado. Retorna ranking de escolas por taxa de ausência.

#### Estado
- "Como nosso estado está no IDEB vs a meta nacional?"
- "A desigualdade racial é pior que a média nacional?"
- "Que % de crianças estão fora da escola?"

**Como funciona:** `get_state_context()` retorna QEdu completo (IDEB, fluxo, distorção, proficiência) + PNAD racial (negro/branco: analf, atraso, idhm_e, freq_fund) + PNAD gênero (homem/mulher: analf, anosest) + top-5 municípios por analfabetismo adulto.

---

### 2.4 Embedding: Para Que Serve e Por Que Só Aluno e Escola

O embedding não é usado em todas as granularidades porque serve para uma função específica: **busca de similares** (`find_similar_*`). Você vetoriza uma entidade e pergunta "quem é parecido?"

| Granularidade | Tem embedding? | Justificativa |
|---|---|---|
| Aluno | ✅ | `find_similar_students()` — alunos com perfil similar que já têm desfecho conhecido (evadiu/ficou) |
| Escola | ✅ | `find_similar_schools()` — escolas com métricas parecidas para benchmark real |
| Turma | ❌ | Turma é agregado já resolvido pelo Q8/Q15 via Cypher direto |
| Município | ❌ | Contexto IBGE estático — a pergunta do gestor já tem o identificador explícito |
| Estado | ❌ | Idem — contexto QEdu/PNAD estrutural |

**Refresh dos embeddings:** DAG Airflow `dag__rag_embedding_refresh`, schedule `0 5 * * 1` (segunda-feira, 5h — após feature engineering das 3h). Duas tasks paralelas: `refresh_student_embeddings` + `refresh_school_embeddings`. A task de escola também persiste `score_saude` + `nivel_saude` no nó `School` para o Retriever ler sem recalcular.

---

## Camada 3 — Infraestrutura e Decisões de Stack

### Stack técnico

| Componente | Tecnologia | Decisão |
|---|---|---|
| Grafo | Neo4j 5+ | Schema com Student, Classroom, School, Municipality, State |
| Orquestração | Apache Airflow (Docker Compose) | DAGs semanais para ML e embedding refresh |
| ML | XGBoost + GradientBoosting + Scikit-Learn Pipeline | Ver §2.1 e §2.2 |
| Embedding local | `sentence-transformers` — MiniLM-L12-v2 | 384d, ~90MB, sem API |
| Vector index | Neo4j vector index (cosine, 384d) | `student_embedding` + `school_embedding` |
| LLM remoto | OpenAI GPT-4o-mini (padrão) | Configurável via `LLM_PROVIDER` env var |
| Tracking ML | MLflow + S3 | Champion/challenger, artefatos, métricas |
| Explicabilidade | SHAP TreeExplainer | Por aluno e por turma (pivot classroom) |
| Serving | FastAPI | Endpoints por granularidade |

### Decisões de schema Neo4j que afetam tudo

- `(sc:StudentClass)-[:ATTENDED]->(stu:Student)` — direção confirmada (não inversa)
- `discipline_name = ''` para nota global EF1 (não nulo, string vazia)
- `malnutrition` sem sufixo `_desease` — propriedade confirmada no nó `Health`
- `PNAD racial` está no nó `State`, **não** em `Municipality`
- `CALL (var) { }` — sintaxe Neo4j 5+ obrigatória (sem escopo implícito)
- Normalização de notas: `CASE WHEN nota > 10 THEN nota/10.0 ELSE nota END` — base 100 vs base 10

### Fallback IBGE

Quando `atl_freq_liq_fund` do município é nulo, o retriever usa a média dos outros municípios da mesma UF como proxy, e sinaliza `fonte_freq_ibge = 'Media_UF_Proxy'` para o LLM saber que é uma estimativa.

---

## Output Final: O Que o Gestor Recebe

O output não é uma dashboard com números. É uma **resposta em linguagem natural** estruturada assim:

```
[DIAGNÓSTICO]
A Turma 7C da Escola EMEIF José Pereira tem Score de Risco 72/100 (🔴 Crítico).
O principal driver é a taxa de ausência de 23,4% — 8,2 pontos acima do benchmark
municipal (15,2% — fonte: IBGE municipal).

[FATORES CRÍTICOS]
1. 7 alunos (63%) com nota de Matemática abaixo de 5 — disciplina com maior
   correlação com reprovação final (+0,65)
2. 4 alunos com falta crítica (>10% dos dias previstos)
3. 68% são beneficiários do Bolsa Família — turma de alta vulnerabilidade

[CONTEXTO ESTRUTURAL]
O estado tem taxa de abandono oficial de 4,2% (QEdu). A turma está 5,1 pontos
acima desse benchmark na métrica de ausência.

[INTERVENÇÕES SUGERIDAS]
- Prioridade imediata: 3 alunos "À Beira" (nota 4,0–4,9) precisam de < 0,6 pontos
  para passar — alto ROI de intervenção
- Acionar professor regente da turma, não PAE individual
- Verificar cobertura do diário eletrônico (Flag_Tem_Diario: 1)

CONFIANÇA: Alta (dados completos — notas + frequência + saúde disponíveis)
```

---

## Fluxo Completo de Ponta a Ponta

```
[SEMANAL — Airflow]
Neo4j → Feature Engineering → XGBoost (EF1) / GradientBoosting (EF2)
→ Predições gravadas no S3 + MLflow
→ Extrator de Ponte: join UUID → Classroom → School (Cypher)
→ Embedding refresh: student_embedder + school_embedder (local, sentence-transformers)
→ Embeddings gravados de volta no Neo4j (vector index)

[TEMPO REAL — por pergunta do gestor]
Pergunta em linguagem natural
→ identify_granularity() [sem LLM — keyword matching]
→ Retriever [Cypher puro no Neo4j]
→ ContextBuilder [serialização ≤ 16.000 chars]
→ Prompt Template [por granularidade]
→ OpenAI GPT-4o-mini [API remota]
→ RAGResponse [answer + latency + quality + granularity]
→ FastAPI → Painel do gestor
```

---

## Riscos e Mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| Escola sem diário eletrônico | Alta | Flag `Flag_Tem_Diario` explícita — LLM informa o gestor, não ignora |
| Município sem dados IBGE | Média | Fallback UF proxy + campo `Fonte_IBGE` |
| LLM API indisponível | Baixa | `LLM_PROVIDER=ollama` como fallback local |
| Embedding cache perdido no restart Docker | Alta | Volume montado `./models_cache:/root/.cache/huggingface` |
| OOM no container Airflow | Resolvido | Downsampling 1M + `gc.collect()` + Worker separado do Webserver |
| Drift de modelo | Monitorado | Evidently em produção, champion/challenger via MLflow |

---

## O Que Este Sistema NÃO É

- **Não é um sistema de vigilância de alunos** — nenhum dado nominal é exposto para gestores fora do nível de orientador/professor
- **Não substitui o pedagogo** — entrega contexto, não decisão
- **Não prediz com certeza** — entrega probabilidade e confiança explícita
- **Não é uma dashboard estática** — é um sistema de perguntas e respostas em linguagem natural, contextualizado por quem pergunta e de qual nível hierárquico

---

*Documento gerado a partir de: PLAN-ML-01, PLAN-ML-02-RAG-LLM-v2, REGRAS_E_DECISOES_PIPELINE_ML, ANALYSIS_VARIADAS_EF2, CYPHER-QUERY-MATRIX-ML, Q_RISCO_EVASAO_EF2, Q_SAUDE_ESCOLA, Q_PROXIMIDADE_ALUNOS, NEO4J-SCHEMA-REFERENCE*
# Guia Definitivo e Detalhado: Implementação Preditiva e ML Models no EF2

Este documento sumariza **tudo o que foi demandado, analisado e implementado** para construir a inteligência preditiva das escolas focadas no Ensino Fundamental 2 (EF2). A finalidade é servir de documentação âncora para a implementação posterior (Dashboards Gestores, Pipelines de Dados, e Atuação de Tutoria).

---

## 1. O Escopo Demandado
A demanda inicial envolvia as seguintes questões para tomada de decisão gerencial:
1. **Quais variáveis mais pesam para a nota média dos alunos?**
2. **Como poderíamos inferir (prever) que alunos tirariam notas abaixo de 5.0?**
3. **Quais matérias puxam mais o aluno para essa linha de corte (abaixo de 5)?**
4. **Quais turmas (`Classrooms`) concentram a maior incidência desse problema?**
5. **Quais escolas (`Schools`) representam epicentros críticos?**
6. **Mapear tudo combinando dados de pelo menos 6 variáveis distintas.**

---

## 2. A Engenharia de Modelos ("O que temos e o que treinamos")

No pipeline do Airflow (`dag__ml_retrain` e `dag__ml_feature_engineering`), operamos com duas abordagens de modelagem preditiva interligadas no **MLflow**:

### 2.1 Modelo de Evasão (Classificador - Existente e Refatorado)
* **Objetivo:** Prever a probabilidade absoluta de um aluno desistir ou reter de ano.
* **Componentes:** Baseia-se no pipeline de classificação, normalmente algoritmos de boosting em árvore (`RandomForestClassifier`, `LightGBM`, `XGBClassifier`), treinados consumindo o target `target_evasao`.
* **Uso posterior:** Fornece o Score de Drop-out utilizado em resgates pedagógicos ao final dos bimestres.

### 2.2 Modelo de Predição de Notas - EF2 (Regressor - Treinado e Debuggado Focamente)
* **Objetivo:** Prever a flutuação da **nota média geral** temporalmente, capturando o fracasso acadêmico *antes* da evasão ocorrer.
* **Problema Resolvido:** O modelo original (`XGBRegressor`) colapsou diversas vezes tentando processar dados ausentes na nossa amostragem do EF2 (alunos sem notas parciais preenchidas nas escolas, e sem variáveis socioeconômicas perfeitas).
* **Nova Arquitetura (Aprovada):** O modelo treinado hoje, promovido ao Alias `@champion`, utiliza um pipeline de scikit-learn estruturado da seguinte maneira:
  1. `SimpleImputer(strategy='mean')`: Imputação rigorosa de variáveis demográficas e textuais parciais em pipeline para evitar `NaN`. Variáveis de ausência também receberam tratamento via sentinelas `-1`.
  2. `GradientBoostingRegressor`: Utilizado de forma robusta e otimizada (via hiperparâmetros) para prever a métrica contínua de Notas.
* **Critério de Risco (Inferência Derivada):** Como nós inferimos "Abaixo de 5.0"? Pegamos a previsão contínua do Gradient Regressor (`target`) e fazemos uma binarização lógica pós-inferência: `aluno_risco = previsão < 5.0`. 

---

## 3. A Resolução Preditiva (As 6+ Variáveis e a Matemática)

No EF2, usando o SHAP e a matriz de importância de features gerada pelo modelo (Grade Regressor), a resposta exata para **"O que derruba a média de um aluno?"**:

1. **V1. Carga de Disciplinas em Risco (`pct_disciplinas_abaixo5`) - Peso de 66.15%:**
   Não existe queda randômica de média. O fator primário é a distribuição de notas vermelhas: se o aluno possui grande % de disciplinas isoladas já abaixo da meta, a "Nota Média Preditiva" final desaba matematicamente.
2. **V2. A Letalidade da Matemática (`nota_mat_norm`) - Peso de 17.23%:**
   Matemática foi comprovada como a variável âncora do fracasso acadêmico na amostra de EF2 treinada (2022-2025). Ela tem o poder preditivo mais cirúrgico entre as "matérias". Se a nota de matemática de um aluno do EF2 despenca para a casa dos "3.0" ou "4.0", a máquina afirma que o quadro global dele resultará abaixo de "5.0". A matéria isoladamente tem **8.7%** dos alunos sem aprovação direta.
3. **V3. Inconstância e Lacunas (`nota_dispersao`) - Peso de 6.46%:**
   A variação de desvio padrão intra-aluno prova que estudantes focados parcialmente não sustentam médias duras. O modelo capta um aluno com "10 num eixo e 2 no outro" e rebaixa sua predição, prevendo exaustão.
4. **V4. Português e Geografia (`nota_lp_norm` e `nota_geo_norm`) - Peso Combinado de ~5.2%:**
   As outras extremidades. Língua Portuguesa falha cerca de 4.0% dos estudantes e sinaliza um déficit básico de interpretação severo que desaba todas as disciplinas teóricas vinculadas, resultando na queda estrutural do Target.
5. **V5. Abandono Invisível (`taxa_ausencia` e `total_faltas_abs`) - Peso Combinado de ~2.2%:**
   Saindo do eixo notas, a "falta crítica" aparece antes do desengajamento final. Escolas que monitoram o diário eletrônico fornecem esse insumo: uma taxa de ausência em crescimento esmaga a curva projetada no ML para a média.
6. **V6. Variáveis Estruturais e Regionais (`est_taxa_abandono` / Aspectos Base):**
   Fatores como vulnerabilidade de Bolsa Família e atraso de CEP (taxa metrificada municipal pelo IBGE) entram como redutores colaterais, inserindo viés estatístico em alunos historicamente invisibilizados. A IA aprende que estes clusters exigem esforços múltiplos.

---

## 4. O Abismo dos Dados: Extração e Agregação Graph (Neo4j)

A grande dificuldade em descobrir **QUAIS TURMAS ESTÃO PIORES** de imediato nasce da arquitetura de escalabilidade do pipeline principal:
* **Parquets de ML:** Os arquivos base (`EF2_*.parquet`) que alimentam o preditor `GradientBoost` **não possuem os nomes das turmas (`Classroom Name`) nem das escolas (`School Name`)**. Isso ocorre proprositalmente para evitar que strings inflem a matriz do tensor (`OneHotEncoding` gigantesco).
* **Consequência:** A inferência nos disse que milhares de alunos iam falhar (temos IDs UUID e a probabilidade exata), mas era impossível entregar ao diretor da escola **ONDE** fisicamente agrupar a intervenção de gestão! Aquele ID pertencia a qual sala?

### Como Solucionamos? O "Extrator Bridge" via Neo4j:
O banco Neo4j detém o mapa físico relacional contendo onde ou "em qual grupo" cada UUID estuda, mas usar o grafo diretamente para agrupar as "Previsões Flutuantes de Pandas" custaria caro lá dentro do backend. O *Herói* foi um **Script Python de Ponte**.

Nós resolvemos na unha em um Extrator Python standalone processado dentro do nó Docker (`airflow-webserver`):

1. **A Coleta via Cypher no GraphDatabase:** Iniciamos uma extração focada conectando ao Driver via `neo4j.GraphDatabase` que puxou apenas e estritamente os nós envolvidos passando pela relação `(Student)-[:ENROLLED_IN]->(Classroom)`:
   ```cypher
   MATCH (sch:School)<-[:ENROLLED_AT_SCHOOL]-(s:Student)-[:ENROLLED_IN]->(c:Classroom)
   RETURN s.id AS student_id, c.name AS classroom_name, sch.name AS school_name
   ```
2. **O Pesadelo do OOM (Out of Memory):** Tentamos cruzar cruamente as notas dos Parquets com as mais de X matrículas do Neo4J usando o Pandas (`pd.merge`). O Docker colapsou por falta de memória (Código de Erro 137). Arquivos duplicados e junções N pra N transformaram a operação num produto cartesiano gigantesco.
3. **A Resolução "Na Marra":** 
    - Nós restringimos o *subsetting* do Parquet apenas às chaves cruciais (`student_id`, `nota_media_geral`, e sub-notas) antes do merge.
    - Fizemos deduplicação forçada `.drop_duplicates('student_id')` logo de cara na extração Graph. 
    - E mais importante: chamamos ativamente a coleta de Lixo Nativa do Python (`import gc; gc.collect()`) para esvaziar da RAM o grande dataframe bruto `df_base` após guardar o referencial enxuto que de fato subiria.
4. **O Join Seguro:** O merge restrito juntou as malhas de predição do modelo EF2 à topologia extraída limpa, finalmente "vestindo" a inferência matemática cega com o contexto físico exato daquela turma mapeada.

---

## 5. Insight Direto do Modelo: As Turmas Colapsadas

Foi apenas cruzando o Output da DAG de Inteligência com o Cypher Extraction no Banco Neo4J em memória restrita que conseguimos identificar os clusters letais. 

*As 5 turmas mais submetidas a anomalias de ensino na base validada:*
| Turma / Classroom Name | Escola Associada | Taxa Crítica de Reprovação (<5.0) | Média Geral Ocultada |
|------------------------|--------------------------------|-----------------------------------|----------------------|
| **100-2019** | EMEIF JOSE PEREIRA DE QUEIROZ | **27.3%** | 6.18 |
| **TURMA 502** | E M E I F NOVA VIDA | **26.7%** | 6.11 |
| **701-2019** | EMEIF JOSE PEREIRA DE QUEIROZ | **25.0%** | 6.72 |
| **301-2018** | E M E F SAO LUIZ | **25.0%** | 6.04 |
| **102-2019** | E M E F ANTONIO MARTINS | **20.0%** | 5.43 |

> ⚠️ ***O Paradoxo da Média Ocultada:***
> Ao analisar estritamente a "Turma 100-2019" sob as lentes tradicionais, os gestores viam uma "Turma passando com nota razoável (6.18)". 
> **A Ciência de Dados identificou o contrário:** A média está distorcida porque os bons alunos passam com louvor, enquanto a turma possui **quase 30% das crianças ativamente condenadas nas métricas analíticas falhando fortemente**. É necessária uma separação intra-turma liderada por monitoria focal.

---

## 6. Diretrizes Técnicas para Suporte Contínuo da Pipeline (Airflow)

Para manutenção e suporte futuro de implementação no Dashboard, essas são as premissas estabelecidas na nossa intervenção de sucesso:

1. **Airflow (`dag__ml_retrain` e `dag__ml_feature_engineering`):** O código foi refatorado para possuir fallback inteligente através de chaves dinâmicas (`storage_mode='local'`) quando o Azure Blob Store se desconectar, forçando uso persistente de volumes docker para treinar as pipelines offline perfeitamente.
2. **Tratamento Dinâmico de Tipos:** Sempre trate `student_id` como um vetor string (`.astype(str)`) quando for cruzar resultados do ML (onde usualmente transicionam para floats e int genéricos pós inferência) contra dados capturados de labels estruturados Neo4J da API de gerenciamento, protegendo contra *KeyErrors* no sub-nível do Pandas.
3. **Migração do MLFlow:** Retiramos oficialmente todas as referências transicionais legadas antigas (`transition_model_version_stage`). Todos os modelos, tanto os disponíveis (Evasão) quanto os retreinados focados agora (Notas), fluirão pelas malhas de registro da DAG utilizando *Client Aliases* flexíveis do MLflow 2.x. Modificadores explícitos geram a tag `@champion`.  

Caminho livre para o Backend construir a view de turmas alimentada e aprimorada pela detecção proativa dessas inferências.

# Diretrizes, Regras e Decisões de Arquitetura - Pipeline de Machine Learning

Este documento consolida o histórico de decisões, regras de negócio adotadas e a engenharia desenvolvida nos bastidores das Pipelines de Machine Learning do TAG (EF1 e EF2). Ele serve como um mapa mental sobre **por quê** as coisas foram construídas da forma como estão hoje.

---

## 1. As Perguntas Fundamentais (O Que Queríamos Responder?)

Toda a arquitetura de dados e de ML foi construída ao redor para tentar responder três perguntas primárias de alto impacto para a gestão escolar:

1. **"Quais são os alunos do EF1 que estão em rota garantida de evasão ou reprovação?"**
   * *A Resposta:* Criada através de um modelo de **Classificação** focado 100% no EF1 (anos iniciais, onde a alfabetização e retenção são o foco). Este modelo emite bandeiras vermelhas baseadas não só em notas, mas em fatores sócio-demográficos ausências.
2. **"No EF2, quais variáveis (alavancas) explicam o real motivo de um aluno ter nota baixa no fim do ano?"**
   * *A Resposta:* Respondido via algoritmo de Regressão. A inteligência artificial descobriu sem viés humano que: **66%** da tração de falha provinha de ter grande volume cumulativo de matérias abaixo de 5 no início do ano (bola de neve) e **17,2%** tinha ligação direta com a ruína na fundação de **Matemática** especificamente.
3. **"Onde (em qual sala física e Estado) estão concentrados os alunos com o maior risco avaliado pela inteligência artificial?"**
   * *A Resposta:* Respondemos isso unindo Data Engineering em Parquet com Extração do Grafo, resultando na detecção e priorização de Turmas e Cidades críticas (ex: Top 20 Turmas Críticas explicitado nas Análises do EF2).

---

## 2. Escolha dos Algoritmos e Modelos de ML

Decidimos dividir a abordagem matemática entre os dois ciclos do Ensino Fundamental.

### 2.1 EF1: XGBoost Classifier (Classificação de Evasão)
* **A Escolha:** Para o EF1, foi escolhido o **XGBoost (Classifier)**. Seu uso é ideal para dados tabulares heterogêneos com colunas de diferentes grandezas.
* **O Desafio Equacionado:** No Brasil, felizmente, a maioria esmagadora dos estudantes passa de ano incólume no fundamental inferior. Nosso dataset tinha cerca de **7.7 Milhões de aprovações contra 24 mil evasões/reprovações**. O XGBoost lida magicamente bem com isso através de sua *feature* de peso via regra matemática:
  ```python
  # O modelo descobre automaticamente a proporção e "pune" mais o erro das classes minoritárias (Evasões)
  ratio = n_neg (7M) / n_pos (24k)
  scale_pos_weight = ratio # (~ 268)
  ```

### 2.2 EF2: Gradient Boosting Regressor (Predição de Notas Contínuas)
* **A Escolha:** Para o EF2, as métricas deixam de ser binárias e o foco se volta ao boletim. Introduzimos o `GradientBoostingRegressor` que prevê as médias finais num intervalo contínuo de `0.0` a `10.0`.
* **A Proteção contra o "Erro Perfeito" (NaNs):** O modelo puro na versão inicial falhou ao quebrar (`input contains NaN`) caso algum aluno aparecesse nos Parquets sem histórico de alguma nota no início do ano.
* **A Decisão:** Restauramos a abordagem protetiva via **Scikit-Learn Pipeline** aplicando o `SimpleImputer(strategy="median")`. É uma regra segura que, ao ver uma nota faltante, preenche passivamente com o valor mediano sem viciar a árvore de decisão do modelo.

---

## 3. Decisões Estratégicas de Engenharia de Dados

Para viabilizar as predições num ecossistema real (rodando via Airflow Docker), tivemos que contornar gargalos brutais de infraestrutura e formatação.

### A. O Paradoxo do Parquet (Por que isolamos o Neo4j?)
* **A Regra Técnica:** Se o Parquet carregasse todas as colunas de texto contendo nomes de Turmas (ex: `"Turma 502"`, `"102-2019"`) ou Escolas, a conversão matemática do modelo (via *One-Hot Encoding*) criaria dezenas de milhares de novas colunas dummy. Isso **estouraria ou inflacionaria** o tensor matemático, tirando o peso limpo da "nota de matemática".
* **A Solução:** O Pipeline de Features (Airflow) foi **proibido** de inserir entidades gráficas no treinamento. O Machine Learning mastiga os dados completamente **CEGO**, focado só em IDs (`student_id`) numéricos e flags socioeconômicas.

### B. O Extrator de Ponte ("Vestindo" o Preditor com Geografia)
* **Problema:** A predição não tem utilidade pro Gestor da Escola se ele for avisado sobre o "ID a1b2". Ele quer saber "Qual a série/turma/escola?".
* **Decisão:** Após rodar a Inteligência Artificial e recuperar a lista cega do Risco de cada UUID, nós acionamos em Python um Extrator que entra na porta do Banco em Grafo **(Neo4j)**, executa uma *Query Cypher* e recupera as localizações reais que unem os UUIDS às escolas (`c:Classroom` e `sch:School`). Nós então unimos via "Merge / Inner Join" as duas realidades sem pesar os contêineres e subimos para o painel em formato de Markdown legível humano (A Tabela Geral de Ocorrências).

### C. A Defesa Contra Falência por Memória (OOM - Exit Code 137)
* Ao longo das esteiras, percebemos que o contêiner Docker `airflow-webserver` colapsava sem rastreabilidades (Exit Code 137). 
* Constatamos que isso não era erro de código, mas **Falta de Memória RAM**. 7 milhões de linhas de predição lidas de maneira síncrona.
* **A Regra Adotada (Downsampling Seguro):** No processamento do *Train_Evasao*, foi introduzida uma regra explícita de "Downsampling":
  1. Nós pegamos todos os estudantes problemáticos (Evasão/Risco) da base de 7 milhões (`Target=1`), pois são valiosos. (~24 mil registros retidos).
  2. Sorteamos ("Sampleamos") rigorosa e aleatoriamente **apenas 1 Milhão** do oceano de estudantes perfeitos.
  3. Com um bloco final com quase 1 Milhão de registros misturados, garantimos que todas as nuances demográficas se mantivessem intactas mantendo a máquina a salvo da falha em Memória antes de acionar a inteligência artificial. Isso acompanhado de gatilhos forçados de limpa-lixo na raiz do Python (`import gc; gc.collect()`).

## Conclusão de Filosofia

O desenvolvimento demonstrou cabalmente que **a inteligência do projeto não reside no hiper-parâmetro do modelo matemático em si, mas em como lapidamos o caminho dos dados.**
As árvores de decisão em *Gradient Boosting* encontraram o óbvio para os especialistas em pedagogia e diretores do EF2. Sem essa engenharia prévia que limpa as pontes, omite strings, lida com faltas e faz recálculos cirúrgicos de RAM, nenhum resultado de alta camada sequer atingiria a ponta operacional nos estados assistidos pelo IPTI.

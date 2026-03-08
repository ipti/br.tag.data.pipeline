# ARQUITETURA PREDITIVA E SOLUÇÃO ESPACIAL DE GRAFOS: IPTI Tag Data Pipeline

Este documento consolida a arquitetura em nuvem (Airflow + MLFlow) do **Sistema de Alerta Antecipado (EWS)**. Ele descreve, de ponta a ponta, as lógicas, finalidades e a integração com banco de grafos (Neo4J) dos dois cérebros matemáticos operando na camada Parquet-ML.

---

## 1. O Ecossistema de Inteligência (Modelos base)

Operamos sob dois fluxos computacionais isolados e avaliados em pipeline contínua. Ambos recebem amostragens massivas oriundas de limpezas prévias da base consolidada do Inep, cruzando históricos e estatísticas intra-municipais.

### 📉 A. Modelo 1: Classificador de Risco de Evasão Escolar (`train_evasao.py`)
- **Algoritmo Base**: `GradientBoostingClassifier`
- **Métrica Alvo (Target)**: `abandono` (variável binária: *0 para fica, 1 para evade*).
- **Tipo de Inferência**: O modelo retorna uma probabilidade % de risco de o aluno não finalizar o ano letivo.
- **Funcionamento Tático**:
  A base histórica mapeada tem milhões de alunos matriculados ao longo da última década. Devido à imensa maioria concluir sem abandonar (gerando desbalanceamento e perigo de "Memory Leak" ou OOM na máquina no Docker), estabelecemos o método de *Random Under-Sampling*. O algoritmo coleta 100% dos que evadiram, amostra 1 milhão dos que focaram (igualando as distribuições) e treina.
- **Utilidade Real**: Emitir lista nominal em dashboard de alunos na zona vermelha de distanciamento demográfico-intelectual antes que aconteça a evasão real.

### 📊 B. Modelo 2: Regressor de Rendimento Escolar - Notas Finais (`train_notas.py`)
- **Algoritmo Base**: `GradientBoostingRegressor`
- **Métrica Alvo (Target)**: `nota_final_continua` ou equivalente paramétrico (Nota contínua entre 0 e 10).
- **Tipo de Inferência**: O modelo cospe a pontuação média ou nota base esperada ao fim do letivo. Caso seja detectado abismos educacionais (menor que média regional), a luz amarela é acesa.
- **Funcionamento Tático**:
  Em vez de focar na probabilidade de fugir da escola, a engenharia cruza as subnotas matemáticas já extraídas (Ex: Pct. Disciplinas abaixo de 5) combinada com a taxa bruta de ausência contínua. A pipeline mapeia isso num Regressor.
- **Utilidade Real**: Fornecer métrica analítica por sala e por professor; quem está abaixo da nota preditiva aceitável do IDEB ou qual escola precisa de re-alinhamento pedagógico urgente.

---

## 2. A Intersecção Físico-Digital: Neo4J Enrichment

A IA preditiva é incapaz de resolver o problema institucional cegamente. Se a rede informa que o "Aluno_089" possui 90% de evasão, o gestor de políticas educacionais precisará investigar. **É aí que os nós de grafo (Neo4J) são evocados para enriquecimento.** 

O Neo4J rastreia a posição física do estudante na esfera municipal e governamental. Entidades separadas no MLFlow são consolidadas no Jupyter Analítico de Grafos.

### Como a Máscara Lógica Funciona no EWS:

1. **O MLflow é Cego (Identidade Anônima)**: O pipeline do Scikit-Learn e MLflow processam apenas IDs (`student_id`), atributos numéricos educacionais (notas, etnia, pct_faltas), e soltam `pred_evasao` ou `pred_nota_final`.
2. **Neo4j Cypher Lookup (Resgate Contextual)**:
   Consultamos a hierarquia completa através do Grafo direcionado do Airflow.
   ```cypher
   MATCH (s:Student)-[:ENROLLED_IN]->(c:Classroom)
   MATCH (c)-[:LOCATED_IN]->(sch:School)
   MATCH (sch)-[:BELONGS_TO]->(muni:City)
   RETURN s.id AS student_id, c.name AS classroom, sch.name AS school, muni.name AS city
   ```
3. **Cruzamento de Matrizes (Pandas Join)**:
   Os ID's preditos pela inteligência são interconectados lateralmente via Pandas (`df_features.merge(df_geo, on="student_id")`). De repente, aquele `pred=drop` de 90% não é mais um número anônimo; pertence à "Escola Estadual X", na "Turma C", município "Sergipe_Z".
4. **Alerta Focal Agregado**:
   Como a escola age na *turma*, os dados consolidados do modelo de predição são cruzados e isolados gerando o **Painel de Risco**. (O painel seleciona `group_by(['school', 'classroom']).mean()`). Se uma turma inteira projetar média final = 3.2, o alerta soa no nível de Classe, não mais apenas de aluno.

---

## 3. Explainer Exato (SHAP Diagnóstico) 

Descobrir que a Turma 'C' possui risco final de evasão ou notas muito baixas é inútil para criar intervenções de fato se a gestão pública não souber o motivo.

Para combater diagnósticos soltos, assim que a matriz do Neo4j indica a turma "Alvo" baseando-se no pico de predições cruzadas, o modelo passa as características (Features) específicas da respectiva classe pela biblioteca matemática de retrocompatibilidade **SHAP (Shapley Additive exPlanations)**.

### Estrutura de Investigação Raiz:
- O módulo destrói a barreira técnica, extraindo exatamente os coeficientes causadores da nota baixa ou Evasão e entregando o peso.
- Exemplo: Ele extrai um `DataFrame` isolando uma turma (onde o Neo4j apontou picos), lê via método TreeExplainer (`explainer.shap_values(Turma_Alvo)`) no modelo embutido pelo MLFlow e responde de fato:

> *"Essa turma da Escola Liberdade pontua mal primariamente pois puxa negativamente os seguintes eixos cruzados: `taxa_ausencia_pct` impactando -0.04 e a distorção `pct_disciplinas_abaixo5` puxando -0.03 de perda linear."*

---

## Conclusão: Abordagem Tecnológica

A pipeline inteira gira em cima deste trio de ferro. As extrações de Inep entram em Parquet; os nós caem via pyArrow para os Arrays em RAM no `Airflow Worker`. O modelo Treina as florestas (GradientBoosting) salvando versões robustecidas no `MLFlow S3` com downsampling e limpeza de memória contínua. 
Por fim, no painel, o Gestor de EWS consulta o container via HTTP, a Inteligência cruza com as coordenadas Neo4j e cospe não apenas "Qual sala?", mas "Por quê?" via SHAP dinâmico. Um ecossistema à prova de balas focado em direcionar governos, não apenas apontar anomalias numéricas.

# 🌐 Explorando o Grafo Escolar no Neo4j

Este documento contém 10 queries essenciais para você explorar o banco de dados que acabamos de construir. Elas foram desenhadas para mostrar o poder da modelagem baseada em grafos, onde os **relacionamentos são tão importantes quanto os próprios dados**.

> ⚠️ **Por que os LIMITs são cruciais?** No Neo4j Browser (`http://localhost:7474`), se você retornar milhares de nós e relações de uma vez, o seu navegador vai tentar renderizar todas as físicas das linhas na tela e vai travar por falta de memória RAM. O `LIMIT` garante que você veja apenas uma sub-rede para validar a lógica visual.

---

## 🔍 10 Queries Essenciais

### 1. Perfil 360º de um Aluno (Grafo Estrela)
**O que faz:** Pega um aluno aleatório e mostra absolutamente tudo ligado a ele no raio de 1 pulo (matrícula, avaliações, saúde, faltas, informações da escola).
**Por que usar:** Excelente para visualizar o histórico de um indivíduo em um formato de "painel de controle visual".
```cypher
MATCH (s:Student)-[r]-(connected_data)
RETURN s, r, connected_data
LIMIT 50
```

### 2. A Hierarquia Escolar (Caminhos Longos)
**O que faz:** Desenha o caminho completo: *Escola → Turma Escolar → Aula da Disciplina → Faltas/Presença → Aluno*.
**Por que usar:** No SQL, isso exigiria 5 `JOINs` pesados. No Neo4j, navegamos pelo caminho desenhado (*Path*). É ótimo para entender onde o aluno está alocado fisicamente.
```cypher
MATCH path = (sc:School)<-[:HELD_AT]-(cr:Classroom)<-[:TAUGHT_IN]-(cl:Class)<-[:ATTENDANCE_OF]-(stc:StudentClass)-[:ATTENDED]->(s:Student)
RETURN path
LIMIT 15

No changes, no records
Completed after 72 ms

2 warnings
01N51: Relationship type does not exist
The relationship type `HELD_AT` does not exist in database `neo4j`. Verify that the spelling is correct.
MATCH path = (sc:School)<-[:HELD_AT]-(cr:Classroom)<-[:TAUGHT_IN]-(cl:Class)<-[:ATTENDANCE_OF]-(stc:StudentClass)-[:ATTENDED]->(s:Student)
                            ^
RETURN path
LIMIT 15
01N51: Relationship type does not exist
The relationship type `ATTENDED` does not exist in database `neo4j`. Verify that the spelling is correct.
MATCH path = (sc:School)<-[:HELD_AT]-(cr:Classroom)<-[:TAUGHT_IN]-(cl:Class)<-[:ATTENDANCE_OF]-(stc:StudentClass)-[:ATTENDED]->(s:Student)
                                                                                                                    ^
RETURN path
LIMIT 15
```

### 3. Impacto da Saúde nas Notas (Busca Cruzada Padrão)
**O que faz:** Encontra alunos com desnutrição ou anemia e tenta buscar suas disciplinas e avaliações (notas).
**Por que usar:** Ideal para times pedagógicos. Responde à pergunta: "Há correlação entre problemas de saúde severos e o rendimento em sala?"
```cypher
MATCH (h:Health)<-[:HAS_HEALTH]-(s:Student)-[:HAS_DISCIPLINE]->(d:StudentDiscipline)
WHERE h.malnutrition = true OR h.iron_deficiency_anemia = true
RETURN s.name, h, d
LIMIT 20
```

### 4. Faltas Críticas por Turma (Agregação de Fato)
**O que faz:** Encontra aulas/disciplinas pontuais (Class) onde no geral os alunos acumularam mais de 10 faltas, e mostra quem são os alunos responsáveis pelo alto índice.
**Por que usar:** Permite focar a gestão escolar onde o incêndio está acontecendo (evasão contínua em determinadas disciplinas).
```cypher
MATCH (cl:Class)<-[:ATTENDANCE_OF]-(sc:StudentClass)-[:ATTENDED]->(s:Student)
WHERE sc.total_faults_per_discipline > 10
RETURN cl.discipline_name, sc.total_faults_per_discipline, s.name
ORDER BY sc.total_faults_per_discipline DESC
LIMIT 25

No changes, no records
Completed after 5 ms

01N51: Relationship type does not exist
The relationship type `ATTENDED` does not exist in database `neo4j`. Verify that the spelling is correct.
MATCH (cl:Class)<-[:ATTENDANCE_OF]-(sc:StudentClass)-[:ATTENDED]->(s:Student)
                                                       ^
WHERE sc.total_faults_per_discipline > 10
RETURN cl.discipline_name, sc.total_faults_per_discipline, s.name
ORDER BY sc.total_faults_per_discipline DESC
LIMIT 25
```

### 5. Escolas com Maior Frequência de Avaliações Críticas
**O que faz:** Navega de Escola até Avaliação passando por Estudante, para contar incidência de alunos em situação crítica de nota (ex: repetição de rec_final).
**Por que usar:** Mostra o poder do Cypher em fazer agregações estatísticas passando por nós intermediários sem lentidão.
```cypher
MATCH (school:School)<-[:HELD_AT]-(:Classroom)<-[:ENROLLED_IN]-(student:Student)-[:EVALUATED_IN]->(av:Avaliation)
WHERE av.situation IN ["REPROVADO", "RECUPERAÇÃO"] // ajuste os status
RETURN school.name, count(av) as Reprovacoes
ORDER BY count(av) DESC
LIMIT 10

01N51: Relationship type does not exist
The relationship type `HELD_AT` does not exist in database `neo4j`. Verify that the spelling is correct.
MATCH (school:School)<-[:HELD_AT]-(:Classroom)<-[:ENROLLED_IN]-(student:Student)-[:EVALUATED_IN]->(av:Avaliation)
                         ^
WHERE av.situation IN ["REPROVADO", "RECUPERAÇÃO"] // ajuste os status
RETURN school.name, count(av) as Reprovacoes
ORDER BY count(av) DESC
LIMIT 10
01N51: Relationship type does not exist
The relationship type `EVALUATED_IN` does not exist in database `neo4j`. Verify that the spelling is correct.
MATCH (school:School)<-[:HELD_AT]-(:Classroom)<-[:ENROLLED_IN]-(student:Student)-[:EVALUATED_IN]->(av:Avaliation)
                                                                                   ^
WHERE av.situation IN ["REPROVADO", "RECUPERAÇÃO"] // ajuste os status
RETURN school.name, count(av) as Reprovacoes
ORDER BY count(av) DESC
LIMIT 10
```

### 6. Isolando Bolsistas Familiares (Filtragem Específica)
**O que faz:** Filtra e exibe o cluster de estudantes que recebem Bolsa Família e como as turmas deles estão interligadas na escola X.
**Por que usar:** Para entender de forma focada métricas socioeconômicas em rede.
```cypher
MATCH (s:Student {bolsa_familia: true})-[r:ENROLLED_AT_SCHOOL]->(school:School)
RETURN s, r, school
LIMIT 30
```

### 7. Geografia da Evasão Escolar (Clusterização)
**O que faz:** Seleciona as Escolas que possuem geografia associada (CEP, cidade) e relaciona com estudantes em status de "ABANDONADO".
**Por que usar:** Ajuda a localizar pólos de evasão num mapa mental ou preparar as coordenadas prontas para um mapa de calor.
```cypher
MATCH (g:SchoolGeograph)<-[:HAS_GEOGRAPHY]-(sc:School)<-[e:ENROLLED_AT_SCHOOL]-(s:Student)
WHERE e.status = "ABANDONADO" 
RETURN g.city, sc.name, count(s) as QuantidadeEvasao
ORDER BY QuantidadeEvasao DESC
LIMIT 10
```

### 8. Identificando Alunos "Fantasmas" (Órfãos)
**O que faz:** Tenta encontrar estudantes que caíram no banco de dados mas **não** estão conectados a nenhuma Turma ou Escola.
**Por que usar:** Excelente query de auditoria e qualidade de dados (Data Quality). Detecta falhas no fluxo SQL original.
```cypher
MATCH (s:Student)
WHERE NOT (s)-[:ENROLLED_IN]->() AND NOT (s)-[:ENROLLED_AT_SCHOOL]->()
RETURN s.name, s.id, s.updated_at
LIMIT 10
```

### 9. Top Disciplinas Problemáticas por Aluno (Sort e Limit Interno)
**O que faz:** Para cada aluno retornado, exibe a disciplina com a menor nota "final_mean".
**Por que usar:** Em SQL, isso envolveria sub-queries densas (Window Functions). Em Cypher, a travessia torna o código limpíssimo.
```cypher
MATCH (s:Student)-[:HAS_DISCIPLINE]->(d:StudentDiscipline)
WHERE d.final_mean IS NOT NULL
RETURN s.name, d.discipline_name, d.final_mean
ORDER BY d.final_mean ASC
LIMIT 15
```

### 10. A Teia Acadêmica de uma Região (Macro-Visualização)
**O que faz:** Pega uma cidade específica, puxa as escolas dela, as turmas e uma amostra de alunos.
**Por que usar:** Produz um gráfico macro lindíssimo. Permite ver a "teia" educacional de uma zona municipal inteira. Recomenda-se dar Zoom Out.
```cypher
MATCH path = (g:SchoolGeograph)<-[:HAS_GEOGRAPHY]-(sc:School)<-[:HELD_AT]-(cr:Classroom)<-[:ENROLLED_IN]-(s:Student)
// WHERE g.city = "NOME DA CIDADE" // Descomente para filtrar por cidade específica
RETURN path
LIMIT 40 // O limit afeta o path inteiro, gerando várias ramificações

No changes, no records
Completed after 127 ms

01N51: Relationship type does not exist
The relationship type `HELD_AT` does not exist in database `neo4j`. Verify that the spelling is correct.
MATCH path = (g:SchoolGeograph)<-[:HAS_GEOGRAPHY]-(sc:School)<-[:HELD_AT]-(cr:Classroom)<-[:ENROLLED_IN]-(s:Student)
                                                                 ^
RETURN path
LIMIT 40
```

---

## 🚀 O Próximo Nível: O que fazer agora com o Neo4j?

Você tirou os dados da restrita estrutura de tabelas SQL (Focada em *Onde* e *Quem*) e os colocou em uma matriz de ligações biológicas (Focada em *Como* e *Por Que*). Aqui está o real valor a extrair agora:

### 1. Grafos para Machine Learning (GDS - Graph Data Science)
O Neo4j GDS é um plugin oficial focado em IA/ML. Ele consegue fazer a matemática vetorial passar pelo desenho da rede. Pode ser usado nativamente neste banco.
*   **Predição de Links (Link Prediction):** Ensinar a rede neural a prever "Qual estudante tem mais chance de desenvolver a ligação de *ABANDONADO* para o ano que vem baseada na topologia da sua turma?".
*   **Centralidade (PageRank / Degree):** Descobrir matematicamente as aulas ou as disciplinas "gargalo", os nós que, quando performam mal, puxam estatisticamente toda a escola para baixo junto com eles.

### 2. Motor de Recomendação e Alertas
O banco grafo responde a consultas complexas invisíveis no SQL em milissegundos. Você interligar ele a APIs para secretarias:
*   *"Atenção: O aluno João Silva reprovou em Matemática. A análise estrutural indica que 80% dos alunos de sua escola com o perfil dele (desnutrição + bolsa família) evadiram no ano letivo consecutivo. Recomenda-se reforço social imediato."*

### 3. Integração com LLMs (Knowledge Graphs / GraphRAG)
O estado da arte (SOTA) da inteligência artificial: Conectar seu Neo4j diretamente a um Agente IA (ex: LangChain).
*   Você não precisará mais escrever queries ou criar Dashboards travados. Um gestor pode abrir um chat e falar em linguagem natural: *"Liste num csv os alunos diabéticos do 5º ano que estão com faltas contínuas em ciências na escola XYZ"*.
*   O LLM formula o Cypher invisivelmente, bate no grafo, e cospe respostas factuais impecáveis baseadas puramente na realidade dos seus dados relacionais (evitando as famosas alucinações).

### 4. Dashboards Analíticos Nativos (Neo4j Bloom)
Esqueça tentar juntar as linhas num cubo OLAP do Power BI ou fazer flat-tables pesadíssimas.
O Neo4j possui o **Neo4j Bloom**, uma ferramenta feita puramente para executivos e gestores navegarem visualmente pelo grafo clicando sobre bolinhas coloridas e arrastando conexões pra expandir correlações sociais, sem nunca precisar ver uma linha de código.

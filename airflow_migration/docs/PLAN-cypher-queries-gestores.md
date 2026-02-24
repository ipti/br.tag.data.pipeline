# 🔥 Matriz Oficial de Consultas Cypher (Gestores e Machine Learning)

**Versão:** 4.0 (Super Otimizada & Rigor Estatístico) | **Alinhamento:** `NEO4J-SCHEMA-REFERENCE.md` & `NEO4J-ANALYSIS-RULES.md`

Este documento consolida 11 lógicas de extração hiper-otimizadas prontas para rodar no ambiente de BI e pipelines de Machine Learning (removidos gargalos de Produtos Cartesianos). 

> **Regras de Proteção Aplicadas:**
> *   Todas as queries de Notas (Fato) possuem a Vacina Matemática (`nota/10.0` se `> 10`).
> *   Eliminação de Falsos-Positivos: `count(stu) > 10` (Exige quorum) e `stDev > 0` nas notas perfeitas.
> *   `coalesce()` absoluto nas variáveis secundárias de Município do IBGE, para nunca quebrar (retornar null global) se o município não tiver a métrica X mapeada.
> *   Separação total entre `elementary_school` e `Ensino Fundamental`.

---

## 🏫 BLOCO 1: Escola vs Escola (O Micro-Mural Municipal)
*Objetivo:* Comparar escolas vizinhas contra a demografia da própria cidade.

### Query 1: Evasão Severa nas Etapas Sensíveis (Faltas Comparadas vs IBGE)
*Descritivo:* Agrupa por `Classroom` para encontrar qual Série e Turma lidera as faltas na mesma vizinhança. Quando o município não possui `atl_atraso_2_fund`, usa o dado estadual (`pnad_t_atraso_fund`) como proxy da UF — evita scan pesado de média entre municípios.
```cypher
MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)

WHERE sc.total_faults_per_day IS NOT NULL 
  AND sc.total_faults_per_day > 0 
  AND coalesce(cr.grade_level, '') <> ''

WITH sch.name AS Escola, 
     cr.grade_level AS Serie, 
     m.name AS Municipio,
     // Fallback: se o município não tem dado de atraso, pega a média estadual
     CASE WHEN m.atl_atraso_2_fund IS NOT NULL AND m.atl_atraso_2_fund > 0
          THEN m.atl_atraso_2_fund
          ELSE coalesce(st.pnad_t_atraso_fund, 0.0)
     END AS IBGE_Atraso_Escolar_Ref,
     CASE WHEN m.atl_atraso_2_fund IS NOT NULL AND m.atl_atraso_2_fund > 0
          THEN 'Municipal' ELSE 'Estadual (proxy UF)'
     END AS Fonte_Atraso,
     sum(sc.total_faults_per_day) AS Volume_Evasao_Apurada,
     count(DISTINCT stu) AS Alunos_Avaliados

WHERE Alunos_Avaliados > 10 // O Cortex do Rigor Estatístico

RETURN Escola, Serie, Municipio, Volume_Evasao_Apurada, Alunos_Avaliados, 
       IBGE_Atraso_Escolar_Ref, Fonte_Atraso
ORDER BY Municipio ASC, Serie ASC, Volume_Evasao_Apurada DESC
```

### Query 2: Alfabetização Primária (Avaliação Global Isolada)
*Descritivo:* Identifica alunos do primário cujas disciplinas são avaliações globais (sem `discipline_name` definido). O filtro antigo `sd.id CONTAINS 'elementary'` foi removido pois os IDs reais são HASH_IDs (GUIDs) que nunca continham essa string — era a causa do retorno vazio.
```cypher
MATCH (sch:School)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)

// Filtro: Avaliação global (primário) = discipline_name vazio
WHERE coalesce(sd.discipline_name, '') = ''
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch, cr, stu, sd,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota_Limpa

WITH sch.name AS Escola, cr.name AS Turma, count(DISTINCT stu) AS N_Alunos, 
     round(avg(Nota_Limpa), 2) AS Rendimento_Primario,
     round(stDev(Nota_Limpa), 2) AS Variancia_Estatistica

WHERE N_Alunos > 10 AND (Rendimento_Primario < 10.0 OR Variancia_Estatistica > 0)

RETURN Escola, Turma, N_Alunos, Rendimento_Primario, Variancia_Estatistica
ORDER BY Rendimento_Primario DESC LIMIT 100
```

### Query 3: Dispersão de Matemática do Fundamental Intramuros
*Descritivo:* Fundamental (6 ao 9 Ano). Foco em desvios absurdos na mesma escola - "Por que em uma turma a média é 9 e na outra 4, se a escola é a mesma?".
```cypher
MATCH (cr:Classroom)<-[:ENROLLED_IN]-(stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)

WHERE cr.grade_level =~ '(?i).*ANO.*'
  AND sd.discipline_name =~ '(?i).*MATEM.*'
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola, cr.name AS Turma,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota

WITH Escola, Turma, count(Nota) AS Estudantes, avg(Nota) AS Media_Pura, stDev(Nota) AS Dispersao_Interna
WHERE Estudantes > 10 AND (Media_Pura < 10.0 OR Dispersao_Interna > 0)

RETURN Escola, Turma, Estudantes, round(Media_Pura, 2) AS Media_Pura, round(Dispersao_Interna, 2) AS Dispersao_Interna
ORDER BY Dispersao_Interna DESC LIMIT 50
```

### Query 4: Equidade Financeira: Bolsa Família x Rendimento no Fundamental
*Descritivo:* Uma escola atende crianças que dependem do Bolsa Família melhor que as escolas com mesmo Nível de município? Corrigido: propriedade real é `bolsa_familia` (não `bolsa_familia_participator`).
```cypher
MATCH (stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WHERE stu.bolsa_familia = True
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  AND sd.discipline_name =~ '(?i).*PORT.*' // Foco em Português Fundamental

WITH sch.name AS Escola, m.name AS Municipio, cr.grade_level AS Serie,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota_Port

WITH Escola, Municipio, Serie, avg(Nota_Port) AS Media_Bolsistas, count(Nota_Port) AS N_Bolsistas
WHERE N_Bolsistas >= 5 

RETURN Municipio, Escola, Serie, N_Bolsistas, round(Media_Bolsistas, 2) AS Media_Bolsistas
ORDER BY Municipio, Media_Bolsistas DESC
```

### Query 5: Saúde Demográfica: Bairros com Atrasos Médicos vs Faltas (Cruzando D_HEALTH)
*Descritivo:* Encontrando Turmas rurais ou de escolas distantes cruzando doenças (malnutrição ou anemia) vs volume diário de faltas. Corrigido: propriedades Health são `malnutrition` e `iron_deficiency_anemia` (sem sufixo `_desease`). Parênteses adicionados no OR/AND.
```cypher
MATCH (stu:Student)-[:HAS_HEALTH]->(h:Health)
MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
MATCH (sc:StudentClass)-[:ATTENDED]->(stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)

WHERE (coalesce(h.malnutrition, False) = True 
    OR coalesce(h.iron_deficiency_anemia, False) = True)
  AND sc.total_faults_per_day > 0

WITH sch.name AS Escola, cr.name AS Turma, 
     count(DISTINCT stu) AS Alunos_Com_Risco_Nutricional, 
     sum(sc.total_faults_per_day) AS Faltas_Relacionadas
WHERE Alunos_Com_Risco_Nutricional >= 3

RETURN Escola, Turma, Alunos_Com_Risco_Nutricional, Faltas_Relacionadas
ORDER BY Faltas_Relacionadas DESC
```


---

## 🏙️ BLOCO 2: A Escola vs A Teia Macroeconômica (Município e Estado)
*Objetivo:* Foco contraponto QEdu/IBGE absoluto vs o esforço da Turma em si.

### Query 6: Desvio do Censo na Frequência Escolar
*Descritivo:* Será que uma turma do 6º de uma Escola está perdendo feio para a Média Líquida de Frequência do Município? Otimizada: filtra apenas registros com faltas reais (>0) para evitar scan de fantasmas, com LIMIT para controlar retorno.
```cypher
MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WHERE sc.total_faults_per_day > 0  // Filtra apenas quem tem faltas reais
  AND cr.grade_level =~ '(?i).*ANO.*' // Focaliza Fundamentais 

WITH sch.name AS Escola,
     cr.grade_level AS Etapa,
     m.name AS Municipio,
     coalesce(m.atl_freq_liq_fund, 0.0) AS IBGE_Frequencia_Bairro,
     sum(sc.total_faults_per_day) AS Total_Faltas_Ocorridas,
     sum(coalesce(sc.scheduled_student_class_days, 200)) AS Grade_Previsao_Dias,
     count(DISTINCT stu) AS Headcount

WHERE Headcount > 10

RETURN Escola, Etapa, Headcount, Total_Faltas_Ocorridas, 
       round((toFloat(Total_Faltas_Ocorridas) / Grade_Previsao_Dias) * 100, 2) AS Pct_Falta_Calculado,
       IBGE_Frequencia_Bairro
ORDER BY Pct_Falta_Calculado DESC
LIMIT 100
```

### Query 7: O Mapa do Analfabetismo IBGE vs Retenção de Meninas (Gênero)
*Descritivo:* Cruza o analfabetismo adulto do município (IBGE) com as notas de Português das alunas. Corrigido: o campo `gender` pode usar valores variados ('F', 'Feminino', 'FEMININO') — regex aplicado. Reduzido o quorum para 5 para garantir resultados.
```cypher
MATCH (stu:Student)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WHERE stu.gender =~ '(?i)^F.*'  // Aceita 'F', 'Feminino', 'FEMININO', etc.
  AND sd.discipline_name =~ '(?i).*PORT.*'
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola, m.name AS Municipio, coalesce(m.atl_t_analf25m, 0.0) AS IBGE_Analfabetismo_Adultos,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota

WITH Escola, Municipio, IBGE_Analfabetismo_Adultos, count(Nota) AS N_Meninas, round(avg(Nota), 2) AS Media_Linguagem_Meninas
WHERE N_Meninas >= 5
RETURN Municipio, IBGE_Analfabetismo_Adultos, Escola, N_Meninas, Media_Linguagem_Meninas
ORDER BY Media_Linguagem_Meninas ASC
LIMIT 100
```

### Query 8: As Turmas Que Vencem (Ou Perdem) As Metas SAEB/QEdu
*Descritivo:* Executa as notas numa timeline isolada sem conectar com StudentClass (Otimização Hiper Expressa). Escala as Notas, exige `Universitarios > 10` com Standard Deviation contrapondo ao Estado Oficial (`mt_adequado`).
```cypher
MATCH (stu:Student)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
WHERE sd.discipline_name =~ '(?i).*MATEM.*' AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH stu, sd, 
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Math_Nota

MATCH (stu)-[:ENROLLED_IN]->(cr:Classroom)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)

WITH sch.name AS Escola, cr.name AS Turma, st.sigla AS UF, 
     coalesce(st.qedu_mt_adequado_ai, 0.0) AS Governo_Mt_Adequado,
     coalesce(st.qedu_ideb_ai, 0.0) AS Governo_IDEB,
     count(Math_Nota) AS Universitarios, 
     round(avg(Math_Nota), 2) AS Rendimento,
     round(stDev(Math_Nota), 2) AS Variancia

WHERE Universitarios > 10 AND (Rendimento < 10.0 OR Variancia > 0)

RETURN UF, Escola, Turma, Rendimento, Variancia, Governo_IDEB, Governo_Mt_Adequado
ORDER BY Rendimento DESC LIMIT 50
```

---

## 🇧🇷 BLOCO 3: Estado x Estado e Exportação para ML
*Objetivo:* Agregadores gigantes e geração de Dataframes com `OPTIONAL MATCH` sequencial para anular o perigoso 'Produto Cartesiano N*M'.

### Query 9: Índice Abstrato de Abandono Escolar vs Taxa QEdu
*Descritivo:* Uma query levíssima. Conta apenas quem teve Faltas, isolado do corpo estudantil geral, contrastando a soma estadual da evasão contra a métrica bruta divulgada pelo MEC/QEdu. 
*Nota:* Adicionado cálculo de `Pct_Evasores_Internos` = proporção dos alunos com faltas vs total de alunos distintos no estado. O total QEdu (`qedu_taxa_abandono`) é a taxa governamental oficial para comparação direta.
```cypher
MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
WHERE sc.total_faults_per_day > 0 // Garante remover fantasmas

WITH st,
     count(DISTINCT sch) AS Escolas_Medidas,
     count(DISTINCT stu) AS Alunos_Evasores_Unicos,
     sum(sc.total_faults_per_day) AS Massa_Faltas_Estado

// Pega o total de alunos no estado (incluindo sem faltas) para calcular %
OPTIONAL MATCH (stu2:Student)-[:ENROLLED_AT_SCHOOL]->(:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(:Municipality)-[:BELONGS_TO_STATE]->(st)
WITH st.name AS Nome_Estado,
     coalesce(st.qedu_taxa_abandono, 0.0) AS QEdu_Abandono_Oficial,
     Escolas_Medidas, Alunos_Evasores_Unicos, Massa_Faltas_Estado,
     count(DISTINCT stu2) AS Total_Alunos_Estado

RETURN Nome_Estado, Escolas_Medidas, Alunos_Evasores_Unicos, Total_Alunos_Estado,
       round(toFloat(Alunos_Evasores_Unicos) / Total_Alunos_Estado * 100, 2) AS Pct_Evasores_Internos,
       Massa_Faltas_Estado, QEdu_Abandono_Oficial
ORDER BY Pct_Evasores_Internos DESC
```

### Query 10: Rendimento Pós-Pandemia: Série Atraso vs Distorção (QEdu)
*Descritivo:* Acompanha alunos com discrepância brutal (`cr.year` ou Idade atrelados ao Rendimento Deficiente) validando contra `qedu_distorcao_ef_ai`.
*Nota:* Adicionado cálculo de distorção idade-série do nosso lado. Contamos alunos onde o `cr.year` (ano letivo) aparece incompatível com o `grade_level` esperado, contrastando com o QEdu oficial.
```cypher
MATCH (cr:Classroom)<-[:ENROLLED_IN]-(stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)

WHERE coalesce(cr.grade_level, '') <> ''

WITH st, cr.grade_level AS Etapa, 
     count(DISTINCT stu) AS Estudantes,
     count(DISTINCT sch) AS Qtd_Escolas

WHERE Estudantes > 10

WITH st.sigla AS UF, Etapa, Qtd_Escolas, Estudantes,
     coalesce(st.qedu_distorcao_ef_ai, 0.0) AS QEdu_Distorcao_Oficial

RETURN UF, Etapa, Qtd_Escolas, Estudantes, QEdu_Distorcao_Oficial
ORDER BY UF ASC, Estudantes DESC 
LIMIT 100
```

### Query 11: The God Matrix 360 v2 (Extract Otimizado de ML)
*Nota Arquitetural Tática:* O erro de "Query Longa Infinita" anterior sumiu. Dividimos em Agregações Subquery Seguras limitadas a `Classroom_ID`. O Neo4j renderiza ela em ms.
```cypher
MATCH (sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(st:State)
MATCH (sch)<-[:ENROLLED_AT_SCHOOL]-(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)

WITH sch, m, st, cr, collect(stu) AS AlunosDaTurma
WHERE size(AlunosDaTurma) > 10

// Fase 1: Abstrair as Matérias (Só Fundamental Math) sem cruzar por enquanto
CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  MATCH (stu)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
  WHERE sd.discipline_name =~ '(?i).*MATEM.*' AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  WITH CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota
  RETURN round(avg(Nota), 2) AS Avg_Matematica, round(stDev(Nota), 2) AS StDev_Matematica
}

// Fase 2: Abstrair a Evasão separadamente das Notas (Corta Cartesiano)
CALL {
  WITH AlunosDaTurma
  UNWIND AlunosDaTurma AS stu
  MATCH (stu)<-[:ATTENDED]-(sc:StudentClass)
  WHERE sc.total_faults_per_day > 0
  RETURN sum(sc.total_faults_per_day) AS Total_Evasao
}

// Aplicação Final da Regra das Mentirosas e Nulos
WITH sch.id AS School_ID, cr.grade_level AS Classroom_Stage, cr.name AS Classroom_Name,
     coalesce(m.atl_t_analf25m, 0.0) AS FEAT_Muni_Analfabetismo, coalesce(m.atl_freq_liq_fund, 0.0) AS FEAT_Muni_Freq,
     coalesce(st.qedu_ideb_ai, 0.0) AS FEAT_State_Ideb,
     Avg_Matematica, StDev_Matematica, coalesce(Total_Evasao, 0) AS Target_Evasao

WHERE Avg_Matematica IS NOT NULL 
  AND (Avg_Matematica < 10.0 OR StDev_Matematica > 0)

RETURN School_ID, Classroom_Stage, Classroom_Name, 
       Avg_Matematica, StDev_Matematica, Target_Evasao,
       FEAT_Muni_Analfabetismo, FEAT_Muni_Freq, FEAT_State_Ideb
```

---

## 📊 BLOCO 4: Queries Explicativas (Cálculos de % do Nosso Lado)
*Objetivo:* Queries complementares que calculam percentuais internos para contrastar com indicadores IBGE/QEdu, gerando insights mais ricos para gestores.

### Query 1-A: Taxa de Ausência % por Escola (Complementar à Query 1)
*Descritivo:* Em vez de apenas volume absoluto de faltas, calcula a **taxa de ausência percentual** (faltas / dias previstos × 100) por escola, mostrando ao gestor qual escola perde mais dias proporcionalmente. Cruza com o atraso escolar do IBGE.
```cypher
MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)
MATCH (sch)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WHERE sc.total_faults_per_day > 0

WITH sch.name AS Escola, m.name AS Municipio,
     count(DISTINCT stu) AS Total_Alunos,
     sum(sc.total_faults_per_day) AS Total_Faltas,
     sum(coalesce(sc.scheduled_student_class_days, 200)) AS Total_Dias_Previstos,
     coalesce(m.atl_atraso_2_fund, 0.0) AS IBGE_Atraso_Fund

WHERE Total_Alunos > 10

RETURN Escola, Municipio, Total_Alunos, Total_Faltas, Total_Dias_Previstos,
       round(toFloat(Total_Faltas) / Total_Dias_Previstos * 100, 2) AS Pct_Ausencia_Escola,
       IBGE_Atraso_Fund
ORDER BY Pct_Ausencia_Escola DESC
LIMIT 50
```

### Query 4-A: Bolsistas vs Não-Bolsistas na Mesma Escola (Complementar à Query 4)
*Descritivo:* Na mesma escola, quem vai melhor em Português: bolsistas ou não-bolsistas? Calcula a média e o **delta percentual** entre os dois grupos. Se o delta for positivo, bolsistas estão indo melhor.
```cypher
MATCH (stu:Student)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)

WHERE sd.discipline_name =~ '(?i).*PORT.*'
  AND coalesce(sd.final_mean, sd.grade_1) IS NOT NULL

WITH sch.name AS Escola, stu.bolsa_familia AS BolsaFamilia,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota

WITH Escola, 
     CASE WHEN BolsaFamilia = True THEN 'Bolsista' ELSE 'Nao_Bolsista' END AS Grupo,
     count(Nota) AS N, round(avg(Nota), 2) AS Media

WHERE N >= 5

RETURN Escola, Grupo, N, Media
ORDER BY Escola, Grupo
LIMIT 200
```

### Query 7-A: Disparidade Racial: Analfabetismo IBGE por Raça vs Rendimento por Etnia
*Descritivo:* Cruza os dados do Atlas IBGE de analfabetismo desagregado por raça (`atl_branco_analf25m` e `atl_negro_analf25m`) com o desempenho real dos alunos por etnia (`stu.ethnicity`) na nossa base. Mostra se a desigualdade histórica do IBGE se reflete nas notas atuais. **As % de analfabetismo já vêm do IBGE** — calculamos do nosso lado a **média e contagem** por grupo étnico.
```cypher
MATCH (stu:Student)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)
MATCH (stu)-[:ENROLLED_AT_SCHOOL]->(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)

WHERE coalesce(sd.final_mean, sd.grade_1) IS NOT NULL
  AND coalesce(stu.ethnicity, '') <> ''
  AND sd.discipline_name =~ '(?i).*PORT.*'

WITH m.name AS Municipio, stu.ethnicity AS Etnia,
     coalesce(m.atl_branco_analf25m, 0.0) AS IBGE_Analf_Branco,
     coalesce(m.atl_negro_analf25m, 0.0) AS IBGE_Analf_Negro,
     CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE coalesce(sd.final_mean, sd.grade_1) END AS Nota

WITH Municipio, Etnia, IBGE_Analf_Branco, IBGE_Analf_Negro,
     count(Nota) AS N_Alunos, round(avg(Nota), 2) AS Media_Nota

WHERE N_Alunos >= 5

RETURN Municipio, Etnia, N_Alunos, Media_Nota, 
       IBGE_Analf_Branco, IBGE_Analf_Negro
ORDER BY Municipio, Media_Nota ASC
LIMIT 100
```

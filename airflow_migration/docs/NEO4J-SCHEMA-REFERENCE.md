# 🗺️ Guia de Referência do Schema Neo4j (SQL -> Cypher)

Este documento é a "Bíblia" arquitetural do Data Warehouse (`[data-warehouse-tag].dbo_tia`) traduzido para o formato de Grafos (Neo4j). Ele documenta explicitamente como os dados de Fatos (`F_`) e Dimensões (`D_`) foram inseridos, virando Nós e Relacionamentos.

Sempre consulte esse guia antes de escrever queries Cypher para garantir que você está apontando para o Nó correto e fazendo as amarrações de Chaves corretas.

---

## �️ 1. O Motor Fato/Relacional (Tabelas `F_`)
No SQL, as tabelas Fato conectam IDs. No Neo4j, elas se transformam nos **Relacionamentos** e nos **Nós de Interação** transacionais diários na escola.

### 1.1. Inscrições e Vínculos Estruturais (A `F_ENROLLMENT`)
A `F_ENROLLMENT` não vira um nó solto. Ela é o "Coração Matemático" que cria as **Molas (Setas)** conectando o Aluno fisicamente ao sistema escolar. Através de `school_id` e `classroom_id`, ela costura:
- `(stu:Student)-[:ENROLLED_AT_SCHOOL]->(sch:School)`
- `(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)`

### 1.2. O Diário de Classe Físico - Nó `StudentClass` (A `F_STUDENT_CLASS`)
Aqui moram as ocorrências transacionais (O que acontece diariamente), especialmente a **Evasão/Faltas**.
- **Propriedades Mapeadas:** 
  - `total_faults_per_day` (Quantidade consolidada de Faltas Diárias)
  - `total_faults_per_discipline` 
  - `scheduled_student_class_days` (Dias previstos para estar presente)
- **Como Navega (Relacionamentos):**
  - **Qual Aluno?** `(sc:StudentClass)-[:ATTENDED]->(stu:Student)` *(Lembre-se, a seta vai do Diário PARA o Aluno)*.
  - **De qual Matéria/Agendamento?** `(sc:StudentClass)-[:ATTENDANCE_OF]->(c:Class)`

### 1.3. O Agendamento da Matéria - Nó `Class` (A `F_CLASS`)
**⚠️ CUIDADO:** O `Class` no Neo4j NÃO é a Turma Física. É a **instância de calendário de aulas para o professor!**
- **Propriedades Mapeadas:**
  - `discipline_name` (Matemática, Ciências, etc)
  - `scheduled_class_days` (Volume de dias letivos formatados)
  - `scheduled_lessons_per_day` (Volume de aulas numa mesma dobra/dia)
  - `scheduled_month`, `scheduled_year`, `scheduled_day`
- **Como Navega:** `(c:Class)-[:CLASS_AT_SCHOOL]->(sch:School)`

### 1.4. O Estado do Aluno - Nó `Avaliation` (A `F_AVALIATION`)
Mapeamento transacional do Status Final ("Aprovado", "Reprovado", "Transferido").
- **Propriedades:** `situation`
- **Como Navega:** Se relaciona com o Student e possivelmente com o período (Mapeamento dependente da query).

---

## 🏛️ 2. As Entidades Físicas (Tabelas Dimensão `D_`)
Aqui moram as características hard-coded de pessoas, prédios e regiões.

### 2.1. O Aluno - Nó `Student` (A `D_STUDENT`)
Carrega altíssimo grão demográfico e cruzamentos socioeconômicos.
- **Propriedades Ricas:**
  - `name`, `gender`, `ethnicity`, `birthday`, `bolsa_familia_participator`
  - `deficiency` (PCD)
  - `residence_zone` (Urbana/Rural)
  - `public_transport` (Dependência de ônibus)

### 2.2. A Turma Administrativa - Nó `Classroom` (A `D_CLASSROOM`)
A Tabela Cadastral das Turmas Físicas Reais da Escola (O mural da porta).
- **As Propriedades Traduzidas:** 
  - `name` (O nome da sala, ex: "TURMA 302", "702-2022")
  - `grade_level` (🚨 **Atenção:** A coluna `stage` do SQL foi convertida com o nome `grade_level` no Grafo! Exemplos: "NO 3* ANO", "NA PRÉ-ESCOLA")
  - `year`, `status`, `serie`
- **Como chegar aqui pela Falta?**
  - Passo 1: Falta (`StudentClass`) vai até o Aluno (`Student`).
  - Passo 2: Aluno vai até a Turma Gestora (`Classroom`).
  - `MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)`

### 2.3. O Boletim de Notas - Nó `StudentDiscipline` (A `D_STUDENT_DISCIPLINE`)
Onde moram as Notas de provas consolidadas.
- **Propriedades:** `discipline_name`, `final_mean`, `grade_1`, `grade_2`, `grade_3`, recuperações (`rec_bim_...`).
- **Como Navega:** `(stu:Student)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)`
- 🛠️ **Truques de Query (Vacinas de Limpeza):**
  - Notas Acima de 10: Limpe com `CASE WHEN coalesce(sd.final_mean, sd.grade_1) > 10 THEN coalesce(sd.final_mean, sd.grade_1) / 10.0 ELSE ... END`
  - **Filtro de Ensino Primário:** A base manda o ID ou MATÉRIA com a Hash de primário em vez de Hist/Geog. Encontre o Primário limpando assim: `WHERE (toLower(toString(sd.id)) CONTAINS 'elementary' OR coalesce(sd.discipline_name, '') = '')`

### 2.4. A Saúde - Nó `Health` (A `D_HEALTH`)
Comorbidades, alergias e diagnósticos vitais atrelados ao aluno.
- **Propriedades Exclusivas:** `diabetes_desease`, `celiac_desase`, `malnutrition_desease`, `hypertension_desease`, `obesity_desease`, etc.
- **Como Navegar:** Se o Aluno estiver linkado, `(Student)-[?]->(Health)`. (É muito usual buscar pelo ID).

### 2.5. A Escola Física - Nó `School` (A `D_SCHOOL`)
- **Propriedades:** `name`, `address_neighborhood`, `situation`, `latitude`, `longitude`

---

## 🗺️ 3. O Ecossistema Externo (Geografia IBGE/QEdu)

As tabelas de Município não são da Tag base original, foram derivadas por ingestões massivas do Atlas IBGE. Todas as escolas amarram numa árvore de Geo Espaço.
- **Árvore Fixa:** `(sch:School)-[:HAS_GEOGRAPHY]->(:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)-[:BELONGS_TO_STATE]->(s:State)`

### 3.1. Nó Base: `SchoolGeograph` (Da `D_SCHOOL_GEOGRAPH`)
- **Propriedades:** `cep`, `city`, `uf`. 

### 3.2. Nó Acoplado: `Municipality` (O Município IBGE)
Possui métricas regionais e sociológicas do entorno da Escola.
- **Dados Destacados:** 
  - Rendimento Social: `atl_t_analf25m`, `atl_expectativa_estudo_18`.
  - Frequencia do Bairro: `atl_freq_liq_fund`.
  - Atrasos de 2 Anos (Fund): `atl_atraso_2_fund`.

### 3.3. Nó Alvo Governamental: `State` (O Estado / SAEB / QEdu)
Possui metas absolutas governamentais usadas nos comparativos de Machine Learning e relatórios de benchmarking estatal.
- **Granularidade:** Estritamente **Estadual**. Os dados macro-educacionais aqui são do fechamento do estado inteiro como entidade única, não da cidade.
- **Fontes de Origem Embutida:** Dados do **QEdu**, que internamente são digeridos do **SAEB** (Níveis de Proficiência em Matemática e Português) e **Censo Escolar** (Distorção Idade-Série, Abandono/Evasão, Taxas de Aprovação).
- **Dados Destacados no Cypher:** 
  - *Metas de Qualidade:* `qedu_ideb_ai` (IDEB dos Anos Iniciais do Estado).
  - *Metas de Proficiência (SAEB):* `qedu_mt_adequado_ai` (% de alunos no estado que sabem pelo menos o básico adequado de matemática da série). Idem para `qedu_lp_adequado_ai` (Linguagem).
  - *Fluxo Escolar (Censo Escolar):* `qedu_taxa_abandono` (O Abandono "Cru" governamental do Estado), `qedu_taxa_aprovacao`.
  - *Atrasos (Censo Escolar):* `qedu_distorcao_ef_ai` (% de alunos matriculados no estado que estão velhos demais para as séries de anos iniciais).

### 3.4. Resumo de Granularidade das Fontes (Cheatsheet)
Sempre que o gestor ou cientista de dados perguntar sobre a matriz de dados:
- **PNAD / Censo Demográfico / Atlas IBGE:** Vive sempre dentro do Nó `Municipality` (Municipal). Responde perguntas Sociais (Raça, Renda, Acesso a Esgoto, Frequência Escolar do Bairro, Analfabetismo de Adultos).
- **QEdu / IDEB / SAEB / Censo Escolar:** Vive sempre dentro do Nó `State` (Estadual). Responde perguntas de Desempenho Educacional Governamental (Quantos % aprenderam, qual a meta do IDEB, qual a distorção geral).

---

## 🚀 "Cheat Sheet" Visual de Como Cruzar (Cypher Paths)

**Quero agregar Faltas por Turma (Sala 3ºB):**
✅ Certo: Pular pelo Aluno para achar a Turma Cadastral.
`MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)-[:ENROLLED_IN]->(cr:Classroom)`
❌ Errado: Pular pelo `Class` (Não tem `name` nem `grade_level` da sala)
`MATCH (sc:StudentClass)-[:ATTENDANCE_OF]->(c:Class)`

**Quero Cruza Rendimento Financeiro (Bolsa Familia) com o Desempenho do Aluno:**
`MATCH (stu:Student)-[:HAS_DISCIPLINE]->(sd:StudentDiscipline)`
`WHERE stu.bolsa_familia_participator = True`
`RETURN avg(sd.final_mean)`

**Quero Analisar se Crianças Ribeirinhas (Rural) tem Teto Maior/Menor de Falta Diária:**
`MATCH (sc:StudentClass)-[:ATTENDED]->(stu:Student)`
`WHERE stu.residence_zone = 'Rural'`
`RETURN avg(sc.total_faults_per_day)`

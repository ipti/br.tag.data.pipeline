# 📏 Diretrizes de Qualidade para Análises e ML no Neo4j

Para que nossos dados educacionais sejam **confiáveis, estatisticamente rigorosos e isentos de falsos-positivos**, todas as extrações Cypher utilizadas para Dashboards de Gestores ou Modelos Predictivos (Machine Learning) **DEVEM RESTRIÇÕES OBRIGATÓRIAS** baseadas no `docs/NEO4J-SCHEMA-REFERENCE.md`.

---

## Regra 1: Separação Explícita de Escopo (Primário vs Fundamental)
O desempenho acadêmico de uma escola nunca deve juntar "crianças em fase de alfabetização" com "adolescentes do 9º ano". Amontoar tudo distorce a linha analítica.

**Diretriz:**
- **Sempre crie 2 Visões Separadas ou adicione uma Flag Categorizadora na Query:**
  - **Filtro Primário (`elementary_school`):** As crianças do bloco primário são avaliadas globalmente em vez de disciplinas isoladas. Elas não têm "Física" ou "História".
    * `WHERE (toLower(toString(sd.id)) CONTAINS 'elementary' OR coalesce(sd.discipline_name, '') = '')`
  - **Filtro Fundamental/Graus Específicos:** Filtrar explicitamente o nome da matéria.
    * `WHERE sd.discipline_name =~ '(?i).*MATEM.*'`

---

## Regra 2: A Normalização da Nota Falsa (O Problema do 10 Perfeito)
É **estatisticamente impossível** que uma escola com 200 alunos tenha "Média 10.0" em todas as disciplinas em um cenário público/rede. Se isso acontecer no DB principal (em massa), ou as notas estão na base 100 sem normalizar, ou são dados fictícios/sem-uso.

**Diretriz (O Algoritmo de Castração):**
1. **Vacina Centesimal:** Todas as notas devem sofrer escala via `CASE WHEN nota > 10 THEN nota / 10.0 ELSE nota END`.
2. **Rejeição Matemática de Artifícios:** Nenhuma escola deve ser julgada apenas pela `Media_Simples (avg)`. Você deve usar um critério de penalização ou remoção de "Perfeição Falsa".
  - **Ação:** Em Dashboards de Gestores, você deve remover as escolas suspeitamente estagnadas.
  - **Exemplo em Cypher:** 
    ```cypher
    WITH sch, avg(nota_padrao) AS Media_Bruta, stDev(nota_padrao) AS Modulo_de_Engano
    // Escolas onde a média deu 10 absoluto mas Ninguém teve variância alguma, é falso-registro.
    WHERE Media_Bruta < 10.0 AND Modulo_de_Engano > 0 
    ```

---

## Regra 3: Tratamento de Dívida / Cadastro Fantasma (O Silêncio dos Dados)
Dezenas de escolas na rede estadual/municipal ainda não digitalizaram o processo. Elas usam a plataforma para registrar alunos, mas **não lançam** faltas diárias nem diários cruzados reais. Se passarmos `sum(faults)` puro para o ML, ele assumirá que a evasão é "Zero" onde, na verdade, os dados nunca foram digitados.

**Diretriz:**
1. **Blindando as Faltas (Evasão Iminente):**  Sempre exija que a escola possua pelo menos **algum pulso de falta não-zero**.
   - `WHERE sc.total_faults_per_day IS NOT NULL AND sc.total_faults_per_day > 0`
2. **Tratamento de Display para Gestores:** No FRONT-END, ao invés de exibir `Faltas: 0`, se a contagem real quebrou no Cypher, a Query que monta o JSON ou Relatório deve projetar uma flag clara:
   - `CASE WHEN Carga_Evasao_Apurada > 0 THEN Carga_Evasao_Apurada ELSE "Sem Uso do Sistema" END` 

---

## Regra 4: Rigor e Comprovação Estatística Básica (Peso de N)
Não faça análises em escolas que possuam **Amostragens minúsculas**, gerando uma "Super Escola" por causa de 2 alunos cadastrados. É obrigatório impor o **N Mínimo**.

**Diretriz para Consultas de Impacto:**
No lugar de apenas entregar a nota (avg), exija que exista um corpo de alunos denso para validar a nota.
```cypher
WITH m, sch, 
     count(stu) as Universo_de_Alunos_Avaliados, // O Tamanho do N
     avg(nota_padrao) as Media_Apurada,
     stDev(nota_padrao) as Variancia_Estatistica // Quão mentirosa é a nota

// Aprovação de Rigor (Regra de Ouro)
WHERE Universo_de_Alunos_Avaliados > 15 
  AND Variancia_Estatistica > 0.1 

RETURN sch.name, Media_Apurada, Universo_de_Alunos_Avaliados
```

Deste modo, a inteligência que vai para o Gestor garante automaticamente a penalidade de escolas fantasmas e mostra a **Confiabilidade da Amostra (Universo)** na tomada de decisão.

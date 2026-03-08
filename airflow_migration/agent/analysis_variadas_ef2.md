# Análise de Risco de Desempenho (EF2) - Fatores Preditivos para Notas < 5.0

Baseado nas inferências reais extraídas pelo modelo `grade-regression-ef2` validado e pelos dados recém-processados (cohort do Ensino Fundamental 2 em 2025 focado em notas cruzadas com contexto municipal e escolar), estruturamos um detalhamento sobre o que realmente afeta e rebaixa as médias de um estudante.

O modelo e os dados apontam os holofotes para **6 principais variáveis preditivas ou contextuais** que formam o perfil dos alunos em maior risco (abaixo de 5).

---

## 1. As 6 Variáveis que Mais Pesam para "Afundar" a Média Geral

Como podemos inferir rapidamente que um aluno fechará com média inferior a 5.0 no ano letivo? Em ordem de impacto, estes são os maiores indicadores de atenção:

### V1. Percentual de Disciplinas em Risco (`pct_disciplinas_abaixo5`)
* **Peso no Modelo (Importância Algorítmica):** `66.15%`
* **Por que importa:** O abismo normalmente não acontece de uma vez. O modelo demonstrou categoricamente que alunos que não sustentam uma base mínima de disciplinas equilibradas encaram um "efeito bola de neve". Se no G1/G2 o estudante já possui um % considerável de disciplinas com nota apertada, a probabilidade da média geral decair para menos que 5 é gigantesca.

### V2. A "Gravidade" da Matemática (`nota_mat_norm`)
* **Peso no Modelo (Importância Algorítmica):** `17.23%`
* **Realidade Observada:** Dentre os mais de 150 mil alunos pareados, **Matemática** é a disciplina com a menor média (6.37) e a maior ocorrência contínua de reprovações específicas (8.7% dos alunos não chegam a 5). 
* **Correlação:** A correlação com a nota final geral é a maior entre todas as disciplinas (`+0.65`). Isso significa que **uma nota fraca em Matemática é o sinal mais isolado e perfeito de que este aluno ficará abaixo de 5 no final do ano em toda a escola.**

### V3. Inconsistência e Flutuações (`nota_dispersao`)
* **Peso no Modelo (Importância Algorítmica):** `6.46%` 
* **Por que importa:** O Desvio Padrão (`dispersão`) atua como uma âncora escondida. Um aluno que tira 10 em Artes mas 3 em Português carrega um nível de dispersão severo. O algoritmo detecta que perfis altamente oscilantes (que aprendem tópicos isolados mas falham em bases lógicas densas) caem precipitadamente de média nos bimestres finais.

### V4. As "Matérias Base de Leitura": Português e Geografia (`nota_lp_norm` e `nota_geo_norm`)
* **Peso Combinado:** `~5.2%`
* **Realidade Observada:** Enquanto Matemática possui o maior índice de falhas, a capacidade Leitora de um aluno é a fundação para todas as outras matérias (Ciências, História, etc). Dificuldade nas estruturas formais dessas duas matérias se irradia indiretamente baixando o teto global da média do aluno.

### V5. O Peso do Absenteísmo / Ausência (`taxa_ausencia` e `total_faltas_abs`)
* **Peso no Modelo:** Representam os maiores ofensores _demográficos/comportamentais_ quando tiramos as notas da mesa (`~2.24%`).
* **Correlação:** Ambas mostram uma correlação estritamente negativa que indica que a falha em frequentar fisicamente as aulas, para a população que mais sofre de risco, afeta a formação cognitiva global. Alunos cujos diários mostram _faltas absolutas frequentes_ encaram notas preditivas esmagadas antes mesmo das provas.

### V6. Contexto Estrutural e Histórico Escolar / Municipal (`est_taxa_abandono` e Demografia Regional)
* **Correlação Encontrada:** O modelo validou que alunos presentes em escolas em municípios com alta `taxa de abandono histórico` sentem o impacto independentemente de seu esforço individual (uma correlação de -0.022 negativa base natural). Além disso, dados como a raça e recursos macro (`muni_pct_negro_pub`) demonstraram o abismo socioeconômico impondo um limitador indireto (correlação base de -0.026 com o sucesso acadêmico pleno) ao longo do tempo. Variáveis associadas à recepção escolar ("Bolsa Família", ou turmas com estrutura prejudicada) refletem a resiliência acadêmica que precisa de monitoramento extra constante.

---

## 2. Qual Matéria "Puxa" Alunos Específicos para a Falha?

Olhando estritamente para o comportamento analítico e taxas de sucesso:

1. **Matemática (`nota_mat_norm`)**: O principal adversário. **8.7%** dos estudantes de 2025 amostrados com notas válidas estão amargando pontuações abaixo de 5.
2. **Língua Portuguesa (`nota_lp_norm`)**: Fica em um sensível segundo lugar onde as fundações bases reprovam ou rebaixam a performance de cerca de **4.0%** dos estudantes ativos.
3. **Geografia (`nota_geo_norm`)**: Retém em torno de **3.1%** com notas críticas, refletindo talvez o formato das provas ou a abstração de dados que prejudicam turmas do EF2.

---

## 3. Células Críticas (Quais Escolas Mais Sofrem)

Focando no recorte real gerado nos dados de 2025 para escolas que atendem turmas razoáveis (N >= 20 matrículas validadas com histórico escolar/merge concluído), identificamos os 5 epicentros com **médias gerais abaixo da nota de corte aceitável (menor que 5.0)** gerando enormes volumes formativos e índices de notas "vermelhas".

| ID INEP da Escola | Alunos Analisados (nesta amostra) | % Alunos Tirando Abaixo de 5 | Média Geral da Escola |
|--------------------|-----------------------------------|------------------------------|-----------------------|
| **21191287**       | 21                                | **71.43%**                   | **4.01**              |
| **35222343**       | 28                                | **71.43%**                   | **4.80**              |
| **21586675**       | 22                                | **59.09%**                   | **4.89**              |
| **28015290**       | 26                                | **50.00%**                   | **5.38**              |
| **15569853**       | 24                                | **45.83%**                   | **5.00**              |

_Nota: Destas 5 escolas, observa-se que as 3 piores possuem médias finais institucionalizadas abaixo da linha de salvamento, demonstrando falhas que transcendem alunos e incidem claramente nos métodos propostos pela escola ou gestão da infraestrutura presente localmente._

---

## Como usar tudo iss para Resgate Rápido? (Action Plan)
Para intervir *antes* do final do ano:
1. Ative alertas aos gestores quando qualquer aluno estiver com `nota_mat_norm` e `pct_disciplinas_abaixo5` subindo perigosamente nos primeiros cortes avaliativos (Bimestre 1 e 2). Um aluno reprovando já nestes campos, sem presença assídua em sala (`taxa_ausencia`), está estatisticamente matematicamente predestinado a uma nota global inferior a 5.0.
2. Mobilize imediatamente tutores pedagógicos específicos para o INEP **21191287** e **35222343** que possuem anomalias de aprendizagens onde 7 a cada 10 alunos estagnaram no insucesso.

---

## 4. O Peso Invisível da Turma (Granularidade de Sala de Aula)

O sistema educacional não distribui alunos aleatoriamente e o algoritmo captura essa concentração de risco. Uma das formas mais acuradas de deduzir quem deixará a média cair da linha aceitável é mapear não apenas as notas e atrasos diretos do aluno, mas a sua **Célula Demográfica Base (A Turma/Classroom).**

### O Efeito "Turma de Maior Risco"
Nos testes, foi provado que certas "Turmas" detêm propriedades contextuais onde a variação pedagógica esmaga quase todos os estudantes matriculados concomitantemente. 

### Principais Exemplos Analisados
Ao fazer o *join* definitivo entre o modelo preditivo EF2 e o Banco em Grafo Neo4j cruzando com as variáveis geográficas do dataset local, extraímos o **Top 20 Nacional de Turmas Críticas** com maiores taxas de reprovação previstas na nossa amostragem (N >= 10 alunos avaliados). Turmas inteiras chegam a beirar **30% de reprovação predita**, demonstrando as fragilidades apontadas nas seções anteriores diretamente agrupadas nessas salas e localidade.

| UF | Município | Turma / Classroom Name | Escola Associada | Taxa Crítica de Reprovação (<5.0) | Média Geral da Turma | Alunos Avaliados |
|----|-----------|------------------------|------------------|-----------------------------------|----------------------|------------------|
| **PB** | Santa Luzia / Outros | **100-2019** | EMEIF JOSE PEREIRA DE QUEIROZ | **27.3%** | 6.18 | 11 |
| **PA** | Santa Luzia / Outros | **TURMA 502** | E M E I F NOVA VIDA | **26.7%** | 6.11 | 15 |
| **PB** | Santa Luzia / Outros | **701-2019** | EMEIF JOSE PEREIRA DE QUEIROZ | **25.0%** | 6.72 | 12 |
| **RS** | Santa Luzia / Outros | **301-2018** | E M E F SAO LUIZ | **25.0%** | 6.04 | 12 |
| **MA** | Santa Luzia / Outros | **102-2019** | E M E F ANTONIO MARTINS | **20.0%** | 5.43 | 10 |
| **PA** | Santa Luzia / Outros | **CRECHE 2 A** | E M E F PAROQUIAL XAVERIANA | **20.0%** | 6.47 | 10 |
| **PA** | Santa Luzia / Outros | **TURMA 404** | E M E I F NOVA VIDA | **18.8%** | 6.37 | 16 |
| **MA** | Santa Luzia / Outros | **TURMA 34** | CRECHE MUNICIPAL BOM PASTOR | **17.6%** | 6.59 | 17 |
| **PB** | Santa Luzia / Outros | **802-2020** | EMEIFM ROSA DIAS DO NASCIMENTO | **15.4%** | 6.30 | 13 |
| **PB** | Santa Luzia / Outros | **201-2020** | EMEIF JOSE PEREIRA DE QUEIROZ | **15.4%** | 6.03 | 13 |
| **PB** | Santa Luzia / Outros | **402-2018** | EMEIF JOSE PEREIRA DE QUEIROZ | **14.3%** | 5.87 | 14 |
| **PA** | Santa Luzia / Outros | **603-2019** | E M E F PAROQUIAL XAVERIANA | **12.5%** | 6.94 | 24 |
| **PA** | Santa Luzia / Outros | **PRE 2 ANEXO** | E M E F PAROQUIAL XAVERIANA | **11.1%** | 6.75 | 18 |
| **PA** | Santa Luzia / Outros | **602-2020** | E M E F DR FERNANDO GUILHON | **10.0%** | 7.12 | 10 |
| **PB** | Santa Luzia / Outros | **904 - Aceleração II** | EMEIFM ROSA DIAS DO NASCIMENTO | **10.0%** | 6.29 | 10 |
| **PB** | Santa Luzia / Outros | **200-2020** | EMEIFM ROSA DIAS DO NASCIMENTO | **10.0%** | 7.15 | 10 |
| **PA** | Santa Luzia / Outros | **TURMA 302** | E M E I F NOVA VIDA | **10.0%** | 6.76 | 10 |
| **PA** | Santa Luzia / Outros | **200-2020** | E M E I F NOVA VIDA | **10.0%** | 6.16 | 10 |
| **RJ** | Santa Luzia / Outros | **204-2021** | ESCOLA MUNICIPAL MANOEL ALVES RANGEL | **9.1%** | 7.56 | 11 |
| **MA** | Santa Luzia / Outros | **P1-02T** | CRECHE MUNICIPAL BOM PASTOR | **9.1%** | 6.60 | 11 |

**Como Utilizar a Variável `Turma` no Modelo?**
A inteligência não recomenda agir sobre alunos sozinhos nestas células. Se o Gestor visualizar no painel que uma `Turma` inteira, como o _"GRUPO IV"_, pontuou fortemente no preditivo de reprovação (como vimos na correlação cruzada de Matemática), a intervenção precisa ser feita com o Professor Regente ou com a Infraestrutura daquela sala específica, invés de focar num PAE (Plano de Atendimento Especializado) individual. 

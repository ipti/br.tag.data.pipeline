# Análise de Risco de Desempenho — EF2

Baseado no modelo `grade-regression-ef2` validado e dados do cohort EF2 2025, com foco em notas cruzadas com contexto municipal e escolar.

---

## 1. As 6 Variáveis que Mais Pesam para "Afundar" a Média

### V1. `pct_disciplinas_abaixo5` — Peso: **66.15%**
O "efeito bola de neve": alunos que não sustentam base mínima em disciplinas têm probabilidade gigantesca de fechar abaixo de 5. Se no G1/G2 já há % considerável de disciplinas apertadas, a queda da média geral é quase certa.

### V2. `nota_mat_norm` (Matemática) — Peso: **17.23%**
- Menor média de todas as disciplinas: **6.37**
- Maior taxa de reprovação específica: **8.7%** dos alunos abaixo de 5
- Correlação com nota final geral: **+0.65** — o sinal mais isolado e perfeito de risco

### V3. `nota_dispersao` (Desvio Padrão entre matérias) — Peso: **6.46%**
Perfis altamente oscilantes (10 em Artes, 3 em Português) caem precipitadamente nos bimestres finais. Alta dispersão = base lógica instável.

### V4. `nota_lp_norm` + `nota_geo_norm` (Português + Geografia) — Peso combinado: **~5.2%**
A capacidade leitora é a fundação para todas as outras matérias. Dificuldade nessas duas irradia indiretamente para o teto global da média.

### V5. `taxa_ausencia` + `total_faltas_abs` — Peso: **~2.24%**
Maior ofensor demográfico/comportamental quando tiramos notas da equação. Correlação estritamente negativa: faltas absolutas frequentes esmagam notas preditivas antes das provas.

### V6. Contexto Estrutural (`est_taxa_abandono` + demografia regional) — Peso: **~2%**
- Correlação de -0.022 com sucesso acadêmico via `taxa de abandono histórico` do município
- `muni_pct_negro_pub` e indicadores raciais impõem limitador indireto (-0.026)
- Bolsa Família + turmas com infraestrutura prejudicada = alertas constantes de monitoramento

---

## 2. Qual Matéria "Puxa" Alunos para a Falha

| Matéria | % Alunos com Nota < 5 |
|---|---|
| **Matemática** | **8.7%** |
| **Língua Portuguesa** | **4.0%** |
| **Geografia** | **3.1%** |

---

## 3. Células Críticas — 5 Escolas com Médias < 5.0

Recorte real dos dados de 2025 (N ≥ 20 matrículas com histórico completo):

| ID INEP | Alunos Analisados | % Abaixo de 5 | Média Geral |
|---|---|---|---|
| **21191287** | 21 | **71.43%** | **4.01** |
| **35222343** | 28 | **71.43%** | **4.80** |
| **21586675** | 22 | **59.09%** | **4.89** |
| **28015290** | 26 | **50.00%** | 5.38 |
| **15569853** | 24 | **45.83%** | 5.00 |

> As 3 piores têm médias institucionalizadas abaixo da linha de salvamento — falhas que transcendem alunos e incidem nos métodos da escola ou na gestão local.

**Ação imediata:** Mobilizar tutores pedagógicos para INEP **21191287** e **35222343** — 7 em cada 10 alunos estagnaram no insucesso.

---

## 4. Top 20 Turmas Críticas Nacionais

Alunos N ≥ 10 com histórico de notas válido. Taxa de reprovação predita pelo modelo:

| UF | Turma | Escola | Taxa Reprov. Predita | Média | N |
|---|---|---|---|---|---|
| PB | 100-2019 | EMEIF JOSE PEREIRA DE QUEIROZ | **27.3%** | 6.18 | 11 |
| PA | TURMA 502 | E M E I F NOVA VIDA | **26.7%** | 6.11 | 15 |
| PB | 701-2019 | EMEIF JOSE PEREIRA DE QUEIROZ | **25.0%** | 6.72 | 12 |
| RS | 301-2018 | E M E F SAO LUIZ | **25.0%** | 6.04 | 12 |
| MA | 102-2019 | E M E F ANTONIO MARTINS | **20.0%** | 5.43 | 10 |
| PA | CRECHE 2 A | E M E F PAROQUIAL XAVERIANA | **20.0%** | 6.47 | 10 |
| PA | TURMA 404 | E M E I F NOVA VIDA | **18.8%** | 6.37 | 16 |
| MA | TURMA 34 | CRECHE MUNICIPAL BOM PASTOR | **17.6%** | 6.59 | 17 |
| PB | 802-2020 | EMEIFM ROSA DIAS DO NASCIMENTO | **15.4%** | 6.30 | 13 |
| PB | 201-2020 | EMEIF JOSE PEREIRA DE QUEIROZ | **15.4%** | 6.03 | 13 |
| PB | 402-2018 | EMEIF JOSE PEREIRA DE QUEIROZ | **14.3%** | 5.87 | 14 |
| PA | 603-2019 | E M E F PAROQUIAL XAVERIANA | **12.5%** | 6.94 | 24 |
| PA | PRE 2 ANEXO | E M E F PAROQUIAL XAVERIANA | **11.1%** | 6.75 | 18 |
| PA | 602-2020 | E M E F DR FERNANDO GUILHON | **10.0%** | 7.12 | 10 |
| PB | 904 - Aceleração II | EMEIFM ROSA DIAS DO NASCIMENTO | **10.0%** | 6.29 | 10 |
| PB | 200-2020 | EMEIFM ROSA DIAS DO NASCIMENTO | **10.0%** | 7.15 | 10 |
| PA | TURMA 302 | E M E I F NOVA VIDA | **10.0%** | 6.76 | 10 |
| PA | 200-2020 | E M E I F NOVA VIDA | **10.0%** | 6.16 | 10 |
| RJ | 204-2021 | ESCOLA MUNICIPAL MANOEL ALVES RANGEL | **9.1%** | 7.56 | 11 |
| MA | P1-02T | CRECHE MUNICIPAL BOM PASTOR | **9.1%** | 6.60 | 11 |

---

## 5. Como Usar a Variável Turma na Intervenção

Quando uma **Turma inteira** pontua alto no preditivo de reprovação:
- A intervenção deve ser feita com o **Professor Regente** ou com a **Infraestrutura daquela sala**, não com PAE individual por aluno
- Turmas com muitos alunos "À Beira" (4.0–4.9) têm alto ROI de intervenção — use `Q_PROXIMIDADE_ALUNOS` para identificá-las

**Sinais de alerta precoce (Bimestres 1 e 2):**
- `nota_mat_norm` crítica + `pct_disciplinas_abaixo5` crescente + `taxa_ausencia` alta = reprovação praticamente certa

# PLAN: Neo4j IBGE Enrichment Migration

> **Slug:** `neo4j-ibge-migration`
> **Tipo do Projeto:** BACKEND / DATA ENGINEERING  
> **Relacionado a:** `PLAN-ml-neo4j-school-v2.md` — Phase 0 (Foundation)  
> **Status:** PLANEJAMENTO  
> **Data:** 2026-02-22

---

## 🎯 Objetivo

Migrar e enriquecer o Neo4j com dados externos do SQL Server (schemas `BUF` e `raw`) seguindo
exatamente o mesmo padrão do `dag__neo4j_full_migration.py` já existente — mesmo stack
(`stream_to_neo4j`, `Neo4jIngestor`, `queries.py`, `transformers.py`), mesmas convenções de
nomenclatura e mesma estrutura de stages.

O resultado final será:
1. Dois novos tipos de nó no grafo: **`Municipality`** e **`State`**
2. Relacionamentos conectando esses nós ao grafo de alunos/escolas já existente
3. Caminho completo de contexto socioeducacional disponível para todo aluno via grafo

---

## 📐 Princípios de Implementação (DRY + Boas Práticas)

- **Reutilizar `stream_to_neo4j`** de `src/utils/neo4j/airflow_tasks.py` — zero código novo de infraestrutura
- **Reutilizar `DatabaseConnectionManager`** para conexão com o SQL Server
- **Novas queries SQL** em `src/utils/neo4j/ibge_queries.py` — não poluir `queries.py` principal
- **Novos Cypher MERGE/SET** em `src/utils/neo4j/ibge_cypher.py` — idem
- **Novos transformers** em `src/utils/neo4j/ibge_transformers.py`
- **Variável de batch: `$rows`** — igual ao padrão de `queries.py` (`UNWIND $rows AS row`)
- **Prefixo de propriedades** obrigatório (`atl_`, `pnad_`, `qedu_`) para não colidir com props dos nós existentes
- **Granularidade racial preservada** — `branco_`, `preto_`, `pardo_` são prefixos distintos; agrupamentos ficam para o tempo de consulta
- **`ano` como parâmetro de filtro** — facilita reprocessamento por ano sem alterar código

---

## 🗺️ Grafo Existente — Referência para os Joins

Com base em `queries.py` e `dag__neo4j_full_migration.py`, o grafo atual tem os seguintes nós
e relacionamentos, que **não devem ser alterados por este DAG**:

```
Nós existentes:
  (Student)           id = F_HASH_ID de d_student
                      props: name, gender, ethnicity, deficiency, bolsa_familia,
                             residence_zone, city_address, uf, birthday, ...
  (School)            id = HASH_ID de d_school
                      props: name, latitude, longitude, situation, ...
  (Classroom)         id = HASH_ID de d_classroom
                      props: name, year, grade_level, stage, status
  (Health)            id = F_HASH_ID de d_health
                      props: celiac, diabetes, hypertension, malnutrition, obesity, ...
  (SchoolGeograph)    id = HASH_ID de d_school_geograph   ← âncora do IBGE
                      props: cep, city, uf
  (StudentDiscipline) id = HASH_ID de d_student_discipline
                      props: discipline_name, grade_1..4, rec_bim_1..4, final_mean, ...
  (Avaliation)        id = HASH_ID de f_avaliation
                      props: situation
  (Class)             id = HASH_ID de f_class
                      props: scheduled_day, scheduled_class_days, scheduled_month,
                             scheduled_year, discipline_name, ...
  (StudentClass)      id = HASH_ID de f_student_class
                      props: total_faults_per_day, total_faults_per_discipline,
                             scheduled_student_class_days

Relacionamentos existentes:
  (Student)        -[:ENROLLED_IN]->        (Classroom)
  (Student)        -[:ENROLLED_AT_SCHOOL]-> (School)
  (Student)        -[:HAS_HEALTH]->         (Health)
  (Classroom)      -[:HELD_AT]->            (School)
  (School)         -[:HAS_GEOGRAPHY]->      (SchoolGeograph)  ← âncora do IBGE
  (Student)        -[:HAS_DISCIPLINE]->     (StudentDiscipline)
  (Student)        -[:EVALUATED_IN]->       (Avaliation)
  (Avaliation)     -[:AVALIATION_OF]->      (StudentDiscipline)
  (Class)          -[:TAUGHT_IN]->          (Classroom)
  (Class)          -[:CLASS_AT_SCHOOL]->    (School)
  (StudentClass)   -[:ATTENDED]->           (Student)
  (StudentClass)   -[:ATTENDANCE_OF]->      (Class)
```

### Nós a criar neste DAG

```
(State)        ← novo, 1 por UF brasileira (27 total)
(Municipality) ← novo, 1 por município (ibge_id como id)
```

### Relacionamentos a criar neste DAG

```
(Municipality)   -[:BELONGS_TO_STATE]->         (State)
(SchoolGeograph) -[:LOCATED_IN_MUNICIPALITY]->   (Municipality)
```

### Caminho completo resultante

```
(Student) -[:ENROLLED_AT_SCHOOL]-> (School)
          -[:HAS_GEOGRAPHY]->       (SchoolGeograph)
          -[:LOCATED_IN_MUNICIPALITY]-> (Municipality)
          -[:BELONGS_TO_STATE]->    (State)
```

> O caminho usa `ENROLLED_AT_SCHOOL` diretamente ao `School`, que leva ao `SchoolGeograph`
> via `HAS_GEOGRAPHY`. Não existe nó intermediário `Enrollment` — esse é um relacionamento
> com propriedades (`status`, `updated_at`), conforme `queries.py`.

---

## 🗺️ Mapeamento: O Que Vem de Onde

| Schema | Tabela | Granularidade | Anos disponíveis | Destino no Neo4j |
|--------|--------|--------------|-----------------|-----------------|
| `BUF` | `City` | Município | — (lookup) | `Municipality.id`, `.name`, `.state_id` |
| `BUF` | `UF` | Estado | — (lookup) | `State.id`, `.name`, `.sigla` |
| `BUF` | `Atlas_todos_Municipios` | Município | 1991, 2000, 2010 | `Municipality.atl_*` |
| `raw` | `Atlas_PNAD_Estados_Total` | Estado | 1991, 2000, 2010 | `State.pnad_*` |
| `raw` | `Atlas_PNAD_Estados_Total_Cor` | Estado × Raça | 1991, 2000, 2010 | `State.branco_pnad_*`, `.preto_pnad_*`, `.pardo_pnad_*` |
| `raw` | `Atlas_PNAD_Estados_Total_Sexo` | Estado × Sexo | 1991, 2000, 2010 | `State.homem_pnad_*`, `.mulher_pnad_*` |
| `raw` | `QeduIDEBTodosAnos` | Município × Ciclo | 2005–2021 (bienal) | `Municipality.qedu_ideb_*` |
| `raw` | `QeduAprendizadoTodosAnos` | Município × Ciclo | 2013–2021 | `Municipality.qedu_lp_*`, `.qedu_mt_*` |
| `raw` | `QeduTaxaDeDistorcaoTodosAnos` | Município × Série | 2006–2021 | `Municipality.qedu_distorcao_*` |
| `raw` | `QeduTaxaDeRendimentoTodosAnos` | Município × Série | 2006–2021 | `Municipality.qedu_taxa_*` |
| `raw` | `QeduPermanenciaTodosAnos` | Município × Coorte | 2009–2021 | `Municipality.qedu_permanencia`, `.qedu_pct_fora` |

---

## 🗃️ Nó: `State`

### `SQL_STATE` — `BUF.UF` + `raw.Atlas_PNAD_Estados_Total` (ano=2010)

```sql
-- ibge_queries.py → SQL_STATE
SELECT
    u.UF_ID                        AS id,
    u.Nome                         AS name,
    u.Sigla_UF                     AS sigla,
    p.IDHM                         AS pnad_idhm,
    p.IDHM_E                       AS pnad_idhm_e,
    p.IDHM_L                       AS pnad_idhm_l,
    p.IDHM_R                       AS pnad_idhm_r,
    p.I_ESCOLARIDADE               AS pnad_i_escolaridade,
    p.I_FREQ_PROP                  AS pnad_i_freq_prop,
    p.RDPC                         AS pnad_rdpc,
    p.GINI                         AS pnad_gini,
    p.PPOB                         AS pnad_ppob,
    p.PIND                         AS pnad_pind,
    p.PMPOB                        AS pnad_pmpob,
    p.ESPVIDA                      AS pnad_espvida,
    p.MORT1                        AS pnad_mort1,
    p.T_ENV                        AS pnad_t_env,
    p.RAZDEP                       AS pnad_razdep,
    p.ANOSEST                      AS pnad_anosest,
    p.T_ANALF15M                   AS pnad_t_analf15m,
    p.T_ANALF18M                   AS pnad_t_analf18m,
    p.T_ANALF25M                   AS pnad_t_analf25m,
    p.T_FREQ5A6                    AS pnad_t_freq5a6,
    p.T_FREQ6A14                   AS pnad_t_freq6a14,
    p.T_FREQ15A17                  AS pnad_t_freq15a17,
    p.T_FREQ18A24                  AS pnad_t_freq18a24,
    p.T_FUND11A13                  AS pnad_t_fund11a13,
    p.T_FUND15A17                  AS pnad_t_fund15a17,
    p.T_MED18A20                   AS pnad_t_med18a20,
    p.T_FUND18M                    AS pnad_t_fund18m,
    p.T_FUND18A24                  AS pnad_t_fund18a24,
    p.T_FUND25M                    AS pnad_t_fund25m,
    p.T_MED25M                     AS pnad_t_med25m,
    p.T_SUPER25M                   AS pnad_t_super25m,
    p.T_ATRASO_2_BASICO            AS pnad_t_atraso_basico,
    p.T_ATRASO_2_FUND              AS pnad_t_atraso_fund,
    p.T_FLBAS                      AS pnad_t_flbas,
    p.T_FLFUND                     AS pnad_t_flfund,
    p.T_FLMED                      AS pnad_t_flmed,
    p.T_FLSUPER                    AS pnad_t_flsuper,
    p.POP_REAL                     AS pnad_pop_real
FROM BUF.UF u
LEFT JOIN raw.Atlas_PNAD_Estados_Total p
    ON u.UF_ID = CAST(p.CODIGO AS INT)
    AND p.ANO = 2010
```

### `MERGE_STATE` — Cypher

```cypher
-- ibge_cypher.py → MERGE_STATE
UNWIND $rows AS row
MERGE (s:State {id: row.id})
SET s.name                 = row.name,
    s.sigla                = row.sigla,
    s.pnad_idhm            = row.pnad_idhm,
    s.pnad_idhm_e          = row.pnad_idhm_e,
    s.pnad_idhm_l          = row.pnad_idhm_l,
    s.pnad_idhm_r          = row.pnad_idhm_r,
    s.pnad_i_escolaridade  = row.pnad_i_escolaridade,
    s.pnad_i_freq_prop     = row.pnad_i_freq_prop,
    s.pnad_rdpc            = row.pnad_rdpc,
    s.pnad_gini            = row.pnad_gini,
    s.pnad_ppob            = row.pnad_ppob,
    s.pnad_pind            = row.pnad_pind,
    s.pnad_pmpob           = row.pnad_pmpob,
    s.pnad_espvida         = row.pnad_espvida,
    s.pnad_mort1           = row.pnad_mort1,
    s.pnad_t_env           = row.pnad_t_env,
    s.pnad_razdep          = row.pnad_razdep,
    s.pnad_anosest         = row.pnad_anosest,
    s.pnad_t_analf15m      = row.pnad_t_analf15m,
    s.pnad_t_analf18m      = row.pnad_t_analf18m,
    s.pnad_t_analf25m      = row.pnad_t_analf25m,
    s.pnad_t_freq5a6       = row.pnad_t_freq5a6,
    s.pnad_t_freq6a14      = row.pnad_t_freq6a14,
    s.pnad_t_freq15a17     = row.pnad_t_freq15a17,
    s.pnad_t_freq18a24     = row.pnad_t_freq18a24,
    s.pnad_t_fund11a13     = row.pnad_t_fund11a13,
    s.pnad_t_fund15a17     = row.pnad_t_fund15a17,
    s.pnad_t_med18a20      = row.pnad_t_med18a20,
    s.pnad_t_fund18m       = row.pnad_t_fund18m,
    s.pnad_t_fund18a24     = row.pnad_t_fund18a24,
    s.pnad_t_fund25m       = row.pnad_t_fund25m,
    s.pnad_t_med25m        = row.pnad_t_med25m,
    s.pnad_t_super25m      = row.pnad_t_super25m,
    s.pnad_t_atraso_basico = row.pnad_t_atraso_basico,
    s.pnad_t_atraso_fund   = row.pnad_t_atraso_fund,
    s.pnad_t_flbas         = row.pnad_t_flbas,
    s.pnad_t_flfund        = row.pnad_t_flfund,
    s.pnad_t_flmed         = row.pnad_t_flmed,
    s.pnad_t_flsuper       = row.pnad_t_flsuper,
    s.pnad_pop_real        = row.pnad_pop_real
```

---

### `SQL_STATE_COR` — Desagregação por Raça (nó `State`)

Cada grupo racial recebe seu próprio prefixo de propriedade. O campo `COR` da tabela é mapeado
pelo transformer conforme a tabela abaixo — **pardo mantém `pardo_` separado de `preto_`**:

| Valor em `COR` | Prefixo no Neo4j |
|----------------|-----------------|
| `"Branca"` | `branco_` |
| `"Preta"` | `preto_` |
| `"Parda"` | `pardo_` |
| `"Amarela"` | `amarelo_` |
| `"Indígena"` | `indigena_` |

> Análises que precisem agregar preto + pardo podem somar em Cypher com
> `(s.preto_pnad_rdpc + s.pardo_pnad_rdpc) / 2` ou via Pandas no pipeline ML.

```sql
-- ibge_queries.py → SQL_STATE_COR
SELECT
    CAST(CODIGO AS INT)  AS state_id,
    COR,
    IDHM                 AS pnad_idhm,
    IDHM_E               AS pnad_idhm_e,
    IDHM_R               AS pnad_idhm_r,
    RDPC                 AS pnad_rdpc,
    GINI                 AS pnad_gini,
    PPOB                 AS pnad_ppob,
    PIND                 AS pnad_pind,
    T_ANALF15M           AS pnad_t_analf15m,
    T_ANALF18M           AS pnad_t_analf18m,
    T_ANALF25M           AS pnad_t_analf25m,
    T_FREQ5A6            AS pnad_t_freq5a6,
    T_FREQ6A14           AS pnad_t_freq6a14,
    T_FREQ15A17          AS pnad_t_freq15a17,
    T_FREQ18A24          AS pnad_t_freq18a24,
    T_FUND11A13          AS pnad_t_fund11a13,
    T_MED18A20           AS pnad_t_med18a20,
    T_SUPER25M           AS pnad_t_super25m,
    T_ATRASO_2_BASICO    AS pnad_t_atraso_basico,
    T_ATRASO_2_FUND      AS pnad_t_atraso_fund,
    T_FLBAS              AS pnad_t_flbas,
    T_FLFUND             AS pnad_t_flfund,
    T_FLMED              AS pnad_t_flmed,
    T_FLSUPER            AS pnad_t_flsuper,
    ANOSEST              AS pnad_anosest
FROM raw.Atlas_PNAD_Estados_Total_Cor
WHERE ANO = 2010
```

```cypher
-- ibge_cypher.py → ENRICH_STATE_COR
-- row.prefix vem do transformer (ex: "branco_", "preto_", "pardo_")
-- Gera props como: branco_pnad_idhm, preto_pnad_rdpc, pardo_pnad_t_analf15m ...
UNWIND $rows AS row
MATCH (s:State {id: row.state_id})
SET s[row.prefix + 'pnad_idhm']          = row.pnad_idhm,
    s[row.prefix + 'pnad_idhm_e']        = row.pnad_idhm_e,
    s[row.prefix + 'pnad_idhm_r']        = row.pnad_idhm_r,
    s[row.prefix + 'pnad_rdpc']          = row.pnad_rdpc,
    s[row.prefix + 'pnad_gini']          = row.pnad_gini,
    s[row.prefix + 'pnad_ppob']          = row.pnad_ppob,
    s[row.prefix + 'pnad_pind']          = row.pnad_pind,
    s[row.prefix + 'pnad_t_analf15m']    = row.pnad_t_analf15m,
    s[row.prefix + 'pnad_t_analf18m']    = row.pnad_t_analf18m,
    s[row.prefix + 'pnad_t_analf25m']    = row.pnad_t_analf25m,
    s[row.prefix + 'pnad_t_freq6a14']    = row.pnad_t_freq6a14,
    s[row.prefix + 'pnad_t_freq15a17']   = row.pnad_t_freq15a17,
    s[row.prefix + 'pnad_t_med18a20']    = row.pnad_t_med18a20,
    s[row.prefix + 'pnad_t_super25m']    = row.pnad_t_super25m,
    s[row.prefix + 'pnad_t_atraso_fund'] = row.pnad_t_atraso_fund,
    s[row.prefix + 'pnad_t_flbas']       = row.pnad_t_flbas,
    s[row.prefix + 'pnad_t_flfund']      = row.pnad_t_flfund,
    s[row.prefix + 'pnad_t_flmed']       = row.pnad_t_flmed,
    s[row.prefix + 'pnad_anosest']       = row.pnad_anosest
```

---

### `SQL_STATE_SEXO` — Desagregação por Sexo (nó `State`)

Prefixos: `"Homem"` → `homem_`, `"Mulher"` → `mulher_`.

```sql
-- ibge_queries.py → SQL_STATE_SEXO
SELECT
    CAST(CODIGO AS INT)  AS state_id,
    SEXO,
    IDHM                 AS pnad_idhm,
    IDHM_E               AS pnad_idhm_e,
    IDHM_R               AS pnad_idhm_r,
    IDHM_AJUSTADO        AS pnad_idhm_ajustado,
    IDHM_R_AJUSTADO      AS pnad_idhm_r_ajustado,
    RDPC                 AS pnad_rdpc,
    T_ANALF15M           AS pnad_t_analf15m,
    T_ANALF25M           AS pnad_t_analf25m,
    T_FREQ5A6            AS pnad_t_freq5a6,
    T_FREQ6A14           AS pnad_t_freq6a14,
    T_FREQ15A17          AS pnad_t_freq15a17,
    T_FUND11A13          AS pnad_t_fund11a13,
    T_MED18A20           AS pnad_t_med18a20,
    T_FUND18M            AS pnad_t_fund18m,
    T_SUPER25M           AS pnad_t_super25m,
    T_FLBAS              AS pnad_t_flbas,
    T_FLFUND             AS pnad_t_flfund,
    T_FLMED              AS pnad_t_flmed,
    T_FLSUPER            AS pnad_t_flsuper,
    ANOSEST              AS pnad_anosest
FROM raw.Atlas_PNAD_Estados_Total_Sexo
WHERE ANO = 2010
```

```cypher
-- ibge_cypher.py → ENRICH_STATE_SEXO
UNWIND $rows AS row
MATCH (s:State {id: row.state_id})
SET s[row.prefix + 'pnad_idhm']           = row.pnad_idhm,
    s[row.prefix + 'pnad_idhm_e']         = row.pnad_idhm_e,
    s[row.prefix + 'pnad_idhm_r']         = row.pnad_idhm_r,
    s[row.prefix + 'pnad_idhm_ajustado']  = row.pnad_idhm_ajustado,
    s[row.prefix + 'pnad_rdpc']           = row.pnad_rdpc,
    s[row.prefix + 'pnad_t_analf15m']     = row.pnad_t_analf15m,
    s[row.prefix + 'pnad_t_analf25m']     = row.pnad_t_analf25m,
    s[row.prefix + 'pnad_t_freq6a14']     = row.pnad_t_freq6a14,
    s[row.prefix + 'pnad_t_med18a20']     = row.pnad_t_med18a20,
    s[row.prefix + 'pnad_t_fund18m']      = row.pnad_t_fund18m,
    s[row.prefix + 'pnad_t_super25m']     = row.pnad_t_super25m,
    s[row.prefix + 'pnad_t_flbas']        = row.pnad_t_flbas,
    s[row.prefix + 'pnad_t_flfund']       = row.pnad_t_flfund,
    s[row.prefix + 'pnad_t_flmed']        = row.pnad_t_flmed,
    s[row.prefix + 'pnad_t_flsuper']      = row.pnad_t_flsuper,
    s[row.prefix + 'pnad_anosest']        = row.pnad_anosest
```

---

## 🗃️ Nó: `Municipality`

Carregado em duas etapas: primeiro o `MERGE_MUNICIPALITY` (cria o nó com dados do Atlas),
depois cinco tasks de enriquecimento QEdu independentes que fazem `MATCH` + `SET`.

### `SQL_MUNICIPALITY` — `BUF.City` + `BUF.Atlas_todos_Municipios` (ano=2010)

O join é por nome normalizado via view (ver seção de Views abaixo).

```sql
-- ibge_queries.py → SQL_MUNICIPALITY
SELECT
    CAST(c.CodigoDoMunicipio AS INT)        AS id,
    c.Municipio                              AS name,
    c.CodigoDaUF                             AS state_id,

    -- Analfabetismo por faixa etária
    a.TaxaDeAnalfabetismo11A14AnosDeIdade    AS atl_t_analf11a14,
    a.TaxaDeAnalfabetismo15A17AnosDeIdade    AS atl_t_analf15a17,
    a.TaxaDeAnalfabetismo18A24AnosDeIdade    AS atl_t_analf18a24,
    a.TaxaDeAnalfabetismo25A29AnosDeIdade    AS atl_t_analf25a29,
    a.TaxaDeAnalfabetismo25AnosOuMaisDeIdade AS atl_t_analf25m,
    a.TaxaDeAnalfabetismo15AnosOuMaisDeIdade AS atl_t_analf15m,
    a.TaxaDeAnalfabetismo18AnosOuMaisDeIdade AS atl_t_analf18m,

    -- Frequência escolar por faixa etária
    a.De0A5AnosDeIdadeNaEscola               AS atl_freq_0a5,
    a.De5A6AnosDeIdadeNaEscola               AS atl_freq_5a6,
    a.De6A14AnosDeIdadeNaEscola              AS atl_freq_6a14,
    a.De15A17AnosDeIdadeNaEscola             AS atl_freq_15a17,
    a.De6A17AnosDeIdadeNaEscola              AS atl_freq_6a17,
    a.De18A24AnosDeIdadeNaEscola             AS atl_freq_18a24,
    a.De25A29AnosDeIdadeNaEscola             AS atl_freq_25a29,

    -- Conclusão de nível por faixa
    a.De11A13AnosDeIdadeNosAnosFinaisDoEnsinoFundamentalOuComEnsinoFundamentalCompleto
                                             AS atl_fund_11a13,
    a.De12A14AnosDeIdadeNosAnosFinaisDoEnsinoFundamentalOuComEnsinoFundamentalCompleto
                                             AS atl_fund_12a14,
    a.De15A17AnosDeIdadeComEnsinoFundamentalCompleto  AS atl_fund_comp_15a17,
    a.De18A24AnosDeIdadeComEnsinoFundamentalCompleto  AS atl_fund_comp_18a24,
    a.De18AnosOuMaisDeIdadeComEnsinoFundamentalCompleto AS atl_fund_comp_18m,
    a.De25AnosOuMaisDeIdadeComEnsinoFundamentalCompleto AS atl_fund_comp_25m,
    a.De18A20AnosDeIdadeComEnsinoMdioCompleto           AS atl_medio_comp_18a20,
    a.De18AnosOuMaisDeIdadeComEnsinoMdioCompleto        AS atl_medio_comp_18m,
    a.De25AnosOuMaisDeIdadeComEnsinoMdioCompleto        AS atl_medio_comp_25m,
    a.De25AnosOuMaisDeIdadeComEnsinoSuperiorCompleto    AS atl_superior_comp_25m,

    -- Expectativa de estudo
    a.ExpectativaDeAnosDeEstudoAos18AnosDeIdade         AS atl_expectativa_estudo_18,

    -- Taxas de frequência brutas e líquidas por nível
    a.TaxaDeFrequnciaBrutaPrEscola                      AS atl_freq_bruta_pre,
    a.TaxaDeFrequnciaBrutaAoEnsinoFundamental           AS atl_freq_bruta_fund,
    a.TaxaDeFrequnciaBrutaAoEnsinoMdio                  AS atl_freq_bruta_medio,
    a.TaxaDeFrequnciaBrutaAoEnsinoBsico                 AS atl_freq_bruta_basico,
    a.TaxaDeFrequnciaBrutaAoEnsinoSuperior              AS atl_freq_bruta_superior,
    a.TaxaDeFrequnciaLquidaPrEscola                     AS atl_freq_liq_pre,
    a.TaxaDeFrequnciaLquidaAoEnsinoFundamental          AS atl_freq_liq_fund,
    a.TaxaDeFrequnciaLquidaAoEnsinoMdio                 AS atl_freq_liq_medio,
    a.TaxaDeFrequnciaLquidaAoEnsinoBsico                AS atl_freq_liq_basico,
    a.TaxaDeFrequnciaLquidaAoEnsinoSuperior             AS atl_freq_liq_superior,

    -- Atraso escolar (distorção idade-série ≥ 2 anos)
    a.De6A14AnosNoEnsinoFundamentalCom2AnosOuMaisDeAtrasoIdadeSrie  AS atl_atraso_2_fund,
    a.De6A17AnosNoEnsinoBsicoCom2AnosOuMaisDeAtrasoIdadeSrie        AS atl_atraso_2_basico,

    -- Adultos no EF — série histórica (proxy de progresso intergeracional)
    a.De18A24AnosDeIdadeFrequentandoOEnsinoFundamental1991          AS atl_ens_fund_18a24_1991,
    a.De18A24AnosDeIdadeFrequentandoOEnsinoFundamental2000          AS atl_ens_fund_18a24_2000,
    a.De18A24AnosDeIdadeFrequentandoOEnsinoFundamental2010          AS atl_ens_fund_18a24_2010,
    a.De18A24AnosDeIdadeFrequentandoOEnsinoFundamental20102000      AS atl_ens_fund_18a24_variacao,

    -- Desagregações por raça — Analfabetismo (Censo)
    a.DesagregaoBrancoTaxaDeAnalfabetismo15AnosOuMaisDeIdadeCenso   AS atl_branco_analf15m,
    a.DesagregaoNegroTaxaDeAnalfabetismo15AnosOuMaisDeIdadeCenso    AS atl_negro_analf15m,
    a.DesagregaoBrancoTaxaDeAnalfabetismo25AnosOuMaisDeIdadeCenso   AS atl_branco_analf25m,
    a.DesagregaoNegroTaxaDeAnalfabetismo25AnosOuMaisDeIdadeCenso    AS atl_negro_analf25m,

    -- Desagregações por raça — Frequência líquida (Censo)
    a.DesagregaoBrancoTaxaDeFrequnciaLquidaAoEnsinoFundamentalCenso AS atl_branco_freq_liq_fund,
    a.DesagregaoNegroTaxaDeFrequnciaLquidaAoEnsinoFundamentalCenso  AS atl_negro_freq_liq_fund,
    a.DesagregaoBrancoTaxaDeFrequnciaLquidaAoEnsinoMdioCenso        AS atl_branco_freq_liq_medio,
    a.DesagregaoNegroTaxaDeFrequnciaLquidaAoEnsinoMdioCenso         AS atl_negro_freq_liq_medio,
    a.DesagregaoBrancoTaxaDeFrequnciaLquidaAoEnsinoSuperiorCenso    AS atl_branco_freq_liq_superior,
    a.DesagregaoNegroTaxaDeFrequnciaLquidaAoEnsinoSuperiorCenso     AS atl_negro_freq_liq_superior,

    -- Desagregações por raça — Conclusão (Censo)
    a.DesagregaoBrancoDe25AnosOuMaisDeIdadeComEnsinoSuperiorCompletoCenso AS atl_branco_superior_25m,
    a.DesagregaoNegroDe25AnosOuMaisDeIdadeComEnsinoSuperiorCompletoCenso  AS atl_negro_superior_25m,
    a.DesagregaoBrancoDe18A20AnosDeIdadeComEnsinoMdioCompletoCenso        AS atl_branco_medio_18a20,
    a.DesagregaoNegroDe18A20AnosDeIdadeComEnsinoMdioCompletoCenso         AS atl_negro_medio_18a20,

    -- Desagregações por raça — Atraso (Censo)
    a.DesagregaoBrancoDe6A14AnosNoEnsinoFundamentalCom2AnosOuMaisDeAtrasoIdadeSrieCenso AS atl_branco_atraso_fund,
    a.DesagregaoNegroDe6A14AnosNoEnsinoFundamentalCom2AnosOuMaisDeAtrasoIdadeSrieCenso  AS atl_negro_atraso_fund,

    -- Desagregações por raça — Matrículas e internet (Censo Escolar)
    a.DesagregaoBrancoDeMatrculasDaRedePblicaNoEnsinoFundamentalCensoEscolar  AS atl_branco_mat_pub_fund,
    a.DesagregaoNegroDeMatrculasDaRedePblicaNoEnsinoFundamentalCensoEscolar   AS atl_negro_mat_pub_fund,
    a.DesagregaoBrancoDeMatrculasDaRedePrivadaNoEnsinoFundamentalCensoEscolar AS atl_branco_mat_priv_fund,
    a.DesagregaoNegroDeMatrculasDaRedePrivadaNoEnsinoFundamentalCensoEscolar  AS atl_negro_mat_priv_fund,
    a.DesagregaoBrancoDeAlunosDoEnsinoFundamentalEmEscolasComInternetCensoEscolar  AS atl_branco_internet_fund,
    a.DesagregaoNegroDeAlunosDoEnsinoFundamentalEmEscolasComInternetCensoEscolar   AS atl_negro_internet_fund,
    a.DesagregaoBrancoDeAlunosDoEnsinoFundamentalEmEscolasComLaboratrioDeInformticaCensoEscolar AS atl_branco_lab_info_fund,
    a.DesagregaoNegroDeAlunosDoEnsinoFundamentalEmEscolasComLaboratrioDeInformticaCensoEscolar  AS atl_negro_lab_info_fund,

    -- Desagregações por sexo — Analfabetismo (Censo)
    a.DesagregaoHomemTaxaDeAnalfabetismo15AnosOuMaisDeIdadeCenso    AS atl_homem_analf15m,
    a.DesagregaoMulherTaxaDeAnalfabetismo15AnosOuMaisDeIdadeCenso   AS atl_mulher_analf15m,

    -- Desagregações por sexo — Frequência líquida (Censo)
    a.DesagregaoHomemTaxaDeFrequnciaLquidaAoEnsinoFundamentalCenso  AS atl_homem_freq_liq_fund,
    a.DesagregaoMulherTaxaDeFrequnciaLquidaAoEnsinoFundamentalCenso AS atl_mulher_freq_liq_fund,
    a.DesagregaoHomemTaxaDeFrequnciaLquidaAoEnsinoMdioCenso         AS atl_homem_freq_liq_medio,
    a.DesagregaoMulherTaxaDeFrequnciaLquidaAoEnsinoMdioCenso        AS atl_mulher_freq_liq_medio,

    -- Desagregações por sexo — Conclusão e anos de estudo (PNAD)
    a.DesagregaoHomemDe25AnosOuMaisDeIdadeComEnsinoSuperiorCompletoCenso  AS atl_homem_superior_25m,
    a.DesagregaoMulherDe25AnosOuMaisDeIdadeComEnsinoSuperiorCompletoCenso AS atl_mulher_superior_25m,
    a.DesagregaoHomemMdiaDeAnosDeEstudoPnad                               AS atl_homem_anosest,
    a.DesagregaoMulherMdiaDeAnosDeEstudoPnad                              AS atl_mulher_anosest,

    -- Desagregações Urbano vs Rural — Frequência e atraso (Censo)
    a.DesagregaoUrbanoDe6A14AnosDeIdadeNaEscolaCenso                AS atl_urbano_freq_6a14,
    a.DesagregaoRuralDe6A14AnosDeIdadeNaEscolaCenso                 AS atl_rural_freq_6a14,
    a.DesagregaoUrbanoTaxaDeFrequnciaLquidaAoEnsinoFundamentalCenso AS atl_urbano_freq_liq_fund,
    a.DesagregaoRuralTaxaDeFrequnciaLquidaAoEnsinoFundamentalCenso  AS atl_rural_freq_liq_fund,
    a.DesagregaoUrbanoTaxaDeFrequnciaLquidaAoEnsinoMdioCenso        AS atl_urbano_freq_liq_medio,
    a.DesagregaoRuralTaxaDeFrequnciaLquidaAoEnsinoMdioCenso         AS atl_rural_freq_liq_medio,
    a.DesagregaoUrbanoTaxaDeAnalfabetismo15AnosOuMaisDeIdadeCenso   AS atl_urbano_analf15m,
    a.DesagregaoRuralTaxaDeAnalfabetismo15AnosOuMaisDeIdadeCenso    AS atl_rural_analf15m,
    a.DesagregaoUrbanoDe6A14AnosNoEnsinoFundamentalCom2AnosOuMaisDeAtrasoIdadeSrieCenso AS atl_urbano_atraso_fund,
    a.DesagregaoRuralDe6A14AnosNoEnsinoFundamentalCom2AnosOuMaisDeAtrasoIdadeSrieCenso  AS atl_rural_atraso_fund,

    a.ano                                                           AS atl_ano

FROM BUF.City c
LEFT JOIN BUF.vw_Atlas_Municipios_Normalized a
    ON a.nome_norm = UPPER(c.Municipio) COLLATE Latin1_General_CI_AI
    AND a.ano = 2010
```

### `MERGE_MUNICIPALITY` — Cypher

```cypher
-- ibge_cypher.py → MERGE_MUNICIPALITY
UNWIND $rows AS row
MERGE (m:Municipality {id: row.id})
SET m.name                        = row.name,
    m.state_id                    = row.state_id,
    m.atl_ano                     = row.atl_ano,
    m.atl_t_analf11a14            = row.atl_t_analf11a14,
    m.atl_t_analf15m              = row.atl_t_analf15m,
    m.atl_t_analf18m              = row.atl_t_analf18m,
    m.atl_t_analf25m              = row.atl_t_analf25m,
    m.atl_freq_0a5                = row.atl_freq_0a5,
    m.atl_freq_5a6                = row.atl_freq_5a6,
    m.atl_freq_6a14               = row.atl_freq_6a14,
    m.atl_freq_15a17              = row.atl_freq_15a17,
    m.atl_freq_6a17               = row.atl_freq_6a17,
    m.atl_freq_18a24              = row.atl_freq_18a24,
    m.atl_fund_11a13              = row.atl_fund_11a13,
    m.atl_fund_comp_15a17         = row.atl_fund_comp_15a17,
    m.atl_fund_comp_25m           = row.atl_fund_comp_25m,
    m.atl_medio_comp_18a20        = row.atl_medio_comp_18a20,
    m.atl_medio_comp_25m          = row.atl_medio_comp_25m,
    m.atl_superior_comp_25m       = row.atl_superior_comp_25m,
    m.atl_expectativa_estudo_18   = row.atl_expectativa_estudo_18,
    m.atl_freq_bruta_fund         = row.atl_freq_bruta_fund,
    m.atl_freq_bruta_medio        = row.atl_freq_bruta_medio,
    m.atl_freq_liq_fund           = row.atl_freq_liq_fund,
    m.atl_freq_liq_medio          = row.atl_freq_liq_medio,
    m.atl_freq_liq_basico         = row.atl_freq_liq_basico,
    m.atl_freq_liq_superior       = row.atl_freq_liq_superior,
    m.atl_atraso_2_fund           = row.atl_atraso_2_fund,
    m.atl_atraso_2_basico         = row.atl_atraso_2_basico,
    m.atl_ens_fund_18a24_1991     = row.atl_ens_fund_18a24_1991,
    m.atl_ens_fund_18a24_2000     = row.atl_ens_fund_18a24_2000,
    m.atl_ens_fund_18a24_2010     = row.atl_ens_fund_18a24_2010,
    m.atl_ens_fund_18a24_variacao = row.atl_ens_fund_18a24_variacao,
    m.atl_branco_analf15m         = row.atl_branco_analf15m,
    m.atl_negro_analf15m          = row.atl_negro_analf15m,
    m.atl_branco_analf25m         = row.atl_branco_analf25m,
    m.atl_negro_analf25m          = row.atl_negro_analf25m,
    m.atl_branco_freq_liq_fund    = row.atl_branco_freq_liq_fund,
    m.atl_negro_freq_liq_fund     = row.atl_negro_freq_liq_fund,
    m.atl_branco_freq_liq_medio   = row.atl_branco_freq_liq_medio,
    m.atl_negro_freq_liq_medio    = row.atl_negro_freq_liq_medio,
    m.atl_branco_superior_25m     = row.atl_branco_superior_25m,
    m.atl_negro_superior_25m      = row.atl_negro_superior_25m,
    m.atl_branco_medio_18a20      = row.atl_branco_medio_18a20,
    m.atl_negro_medio_18a20       = row.atl_negro_medio_18a20,
    m.atl_branco_atraso_fund      = row.atl_branco_atraso_fund,
    m.atl_negro_atraso_fund       = row.atl_negro_atraso_fund,
    m.atl_branco_mat_pub_fund     = row.atl_branco_mat_pub_fund,
    m.atl_negro_mat_pub_fund      = row.atl_negro_mat_pub_fund,
    m.atl_branco_mat_priv_fund    = row.atl_branco_mat_priv_fund,
    m.atl_negro_mat_priv_fund     = row.atl_negro_mat_priv_fund,
    m.atl_branco_internet_fund    = row.atl_branco_internet_fund,
    m.atl_negro_internet_fund     = row.atl_negro_internet_fund,
    m.atl_branco_lab_info_fund    = row.atl_branco_lab_info_fund,
    m.atl_negro_lab_info_fund     = row.atl_negro_lab_info_fund,
    m.atl_homem_analf15m          = row.atl_homem_analf15m,
    m.atl_mulher_analf15m         = row.atl_mulher_analf15m,
    m.atl_homem_freq_liq_fund     = row.atl_homem_freq_liq_fund,
    m.atl_mulher_freq_liq_fund    = row.atl_mulher_freq_liq_fund,
    m.atl_homem_freq_liq_medio    = row.atl_homem_freq_liq_medio,
    m.atl_mulher_freq_liq_medio   = row.atl_mulher_freq_liq_medio,
    m.atl_homem_superior_25m      = row.atl_homem_superior_25m,
    m.atl_mulher_superior_25m     = row.atl_mulher_superior_25m,
    m.atl_homem_anosest           = row.atl_homem_anosest,
    m.atl_mulher_anosest          = row.atl_mulher_anosest,
    m.atl_urbano_freq_6a14        = row.atl_urbano_freq_6a14,
    m.atl_rural_freq_6a14         = row.atl_rural_freq_6a14,
    m.atl_urbano_freq_liq_fund    = row.atl_urbano_freq_liq_fund,
    m.atl_rural_freq_liq_fund     = row.atl_rural_freq_liq_fund,
    m.atl_urbano_freq_liq_medio   = row.atl_urbano_freq_liq_medio,
    m.atl_rural_freq_liq_medio    = row.atl_rural_freq_liq_medio,
    m.atl_urbano_analf15m         = row.atl_urbano_analf15m,
    m.atl_rural_analf15m          = row.atl_rural_analf15m,
    m.atl_urbano_atraso_fund      = row.atl_urbano_atraso_fund,
    m.atl_rural_atraso_fund       = row.atl_rural_atraso_fund
```

---

### Enriquecimentos QEdu — 5 tasks independentes por tema

Cada task faz `MATCH` + `SET` no nó `Municipality` já criado, buscando por `ibge_id`.

#### `SQL_MUNICIPALITY_IDEB` + `ENRICH_MUNICIPALITY_IDEB`

Gera propriedades dinâmicas por ciclo: `qedu_ideb_ai`, `qedu_ideb_af`, `qedu_ideb_em`, etc.

```sql
-- ibge_queries.py → SQL_MUNICIPALITY_IDEB
SELECT i.ibge_id, i.ciclo_id, i.dependencia_id, i.ano,
       i.ideb, i.fluxo, i.aprendizado, i.nota_mt, i.nota_lp
FROM raw.QeduIDEBTodosAnos i
INNER JOIN (
    SELECT ibge_id, ciclo_id, dependencia_id, MAX(ano) AS max_ano
    FROM raw.QeduIDEBTodosAnos
    GROUP BY ibge_id, ciclo_id, dependencia_id
) latest ON i.ibge_id = latest.ibge_id
         AND i.ciclo_id = latest.ciclo_id
         AND i.dependencia_id = latest.dependencia_id
         AND i.ano = latest.max_ano
WHERE i.dependencia_id IN (2, 3)  -- Estadual + Municipal
```

```cypher
-- ibge_cypher.py → ENRICH_MUNICIPALITY_IDEB
-- ciclo_id normalizado pelo transformer: 'AI' → 'ai', 'AF' → 'af', 'EM' → 'em'
UNWIND $rows AS row
MATCH (m:Municipality {id: row.ibge_id})
SET m['qedu_ideb_'        + toLower(row.ciclo_id)] = row.ideb,
    m['qedu_fluxo_'       + toLower(row.ciclo_id)] = row.fluxo,
    m['qedu_aprendizado_' + toLower(row.ciclo_id)] = row.aprendizado,
    m['qedu_nota_mt_'     + toLower(row.ciclo_id)] = row.nota_mt,
    m['qedu_nota_lp_'     + toLower(row.ciclo_id)] = row.nota_lp,
    m['qedu_ideb_ano_'    + toLower(row.ciclo_id)] = row.ano
```

#### `SQL_MUNICIPALITY_APRENDIZADO` + `ENRICH_MUNICIPALITY_APRENDIZADO`

```sql
-- ibge_queries.py → SQL_MUNICIPALITY_APRENDIZADO
SELECT a.ibge_id, a.ciclo_id, a.ano,
       a.lp_adequado, a.mt_adequado,
       a.lp_insuficiente, a.lp_basico, a.lp_proficiente, a.lp_avancado,
       a.mt_insuficiente, a.mt_basico, a.mt_proficiente, a.mt_avancado
FROM raw.QeduAprendizadoTodosAnos a
INNER JOIN (
    SELECT ibge_id, ciclo_id, MAX(ano) AS max_ano
    FROM raw.QeduAprendizadoTodosAnos
    GROUP BY ibge_id, ciclo_id
) latest ON a.ibge_id = latest.ibge_id
         AND a.ciclo_id = latest.ciclo_id
         AND a.ano = latest.max_ano
WHERE a.dependencia_id IN (2, 3)
```

```cypher
-- ibge_cypher.py → ENRICH_MUNICIPALITY_APRENDIZADO
UNWIND $rows AS row
MATCH (m:Municipality {id: row.ibge_id})
SET m['qedu_lp_adequado_'     + toLower(row.ciclo_id)] = row.lp_adequado,
    m['qedu_mt_adequado_'     + toLower(row.ciclo_id)] = row.mt_adequado,
    m['qedu_lp_insuficiente_' + toLower(row.ciclo_id)] = row.lp_insuficiente,
    m['qedu_lp_basico_'       + toLower(row.ciclo_id)] = row.lp_basico,
    m['qedu_lp_proficiente_'  + toLower(row.ciclo_id)] = row.lp_proficiente,
    m['qedu_lp_avancado_'     + toLower(row.ciclo_id)] = row.lp_avancado,
    m['qedu_mt_insuficiente_' + toLower(row.ciclo_id)] = row.mt_insuficiente,
    m['qedu_mt_basico_'       + toLower(row.ciclo_id)] = row.mt_basico,
    m['qedu_mt_proficiente_'  + toLower(row.ciclo_id)] = row.mt_proficiente,
    m['qedu_mt_avancado_'     + toLower(row.ciclo_id)] = row.mt_avancado
```

#### `SQL_MUNICIPALITY_DISTORCAO` + `ENRICH_MUNICIPALITY_DISTORCAO`

```sql
-- ibge_queries.py → SQL_MUNICIPALITY_DISTORCAO
SELECT d.ibge_id, d.ano, d.localizacao_id,
       d.ef_1ano, d.ef_2ano, d.ef_3ano, d.ef_4ano, d.ef_5ano,
       d.ef_6ano, d.ef_7ano, d.ef_8ano, d.ef_9ano,
       d.ef_total_ai, d.ef_total_af, d.ef_total,
       d.em_1ano, d.em_2ano, d.em_3ano, d.em_total
FROM raw.QeduTaxaDeDistorcaoTodosAnos d
INNER JOIN (
    SELECT ibge_id, MAX(ano) AS max_ano
    FROM raw.QeduTaxaDeDistorcaoTodosAnos
    GROUP BY ibge_id
) latest ON d.ibge_id = latest.ibge_id AND d.ano = latest.max_ano
WHERE d.localizacao_id = 1   -- Urbana
```

```cypher
-- ibge_cypher.py → ENRICH_MUNICIPALITY_DISTORCAO
UNWIND $rows AS row
MATCH (m:Municipality {id: row.ibge_id})
SET m.qedu_distorcao_ef1      = row.ef_1ano,
    m.qedu_distorcao_ef2      = row.ef_2ano,
    m.qedu_distorcao_ef3      = row.ef_3ano,
    m.qedu_distorcao_ef4      = row.ef_4ano,
    m.qedu_distorcao_ef5      = row.ef_5ano,
    m.qedu_distorcao_ef6      = row.ef_6ano,
    m.qedu_distorcao_ef7      = row.ef_7ano,
    m.qedu_distorcao_ef8      = row.ef_8ano,
    m.qedu_distorcao_ef9      = row.ef_9ano,
    m.qedu_distorcao_ef_ai    = row.ef_total_ai,
    m.qedu_distorcao_ef_af    = row.ef_total_af,
    m.qedu_distorcao_ef_total = row.ef_total,
    m.qedu_distorcao_em1      = row.em_1ano,
    m.qedu_distorcao_em2      = row.em_2ano,
    m.qedu_distorcao_em3      = row.em_3ano,
    m.qedu_distorcao_em_total = row.em_total,
    m.qedu_distorcao_ano      = row.ano
```

#### `SQL_MUNICIPALITY_RENDIMENTO` + `ENRICH_MUNICIPALITY_RENDIMENTO`

```sql
-- ibge_queries.py → SQL_MUNICIPALITY_RENDIMENTO
-- Média ponderada por matrículas para agregar todas as séries do município
SELECT r.ibge_id, r.ano,
       SUM(r.matriculas)                                                AS total_matriculas,
       SUM(r.aprovados  * r.matriculas) / NULLIF(SUM(r.matriculas), 0) AS taxa_aprovacao,
       SUM(r.reprovados * r.matriculas) / NULLIF(SUM(r.matriculas), 0) AS taxa_reprovacao,
       SUM(r.abandonos  * r.matriculas) / NULLIF(SUM(r.matriculas), 0) AS taxa_abandono
FROM raw.QeduTaxaDeRendimentoTodosAnos r
INNER JOIN (
    SELECT ibge_id, MAX(ano) AS max_ano
    FROM raw.QeduTaxaDeRendimentoTodosAnos
    GROUP BY ibge_id
) latest ON r.ibge_id = latest.ibge_id AND r.ano = latest.max_ano
GROUP BY r.ibge_id, r.ano
```

```cypher
-- ibge_cypher.py → ENRICH_MUNICIPALITY_RENDIMENTO
UNWIND $rows AS row
MATCH (m:Municipality {id: row.ibge_id})
SET m.qedu_total_matriculas = row.total_matriculas,
    m.qedu_taxa_aprovacao   = row.taxa_aprovacao,
    m.qedu_taxa_reprovacao  = row.taxa_reprovacao,
    m.qedu_taxa_abandono    = row.taxa_abandono,
    m.qedu_rendimento_ano   = row.ano
```

#### `SQL_MUNICIPALITY_PERMANENCIA` + `ENRICH_MUNICIPALITY_PERMANENCIA`

```sql
-- ibge_queries.py → SQL_MUNICIPALITY_PERMANENCIA
SELECT p.ibge_id, p.ano_nascimento, p.ano_censo, p.permanencia, p.fora
FROM raw.QeduPermanenciaTodosAnos p
INNER JOIN (
    SELECT ibge_id, MAX(ano_censo) AS max_ano_censo
    FROM raw.QeduPermanenciaTodosAnos
    GROUP BY ibge_id
) latest ON p.ibge_id = latest.ibge_id AND p.ano_censo = latest.max_ano_censo
```

```cypher
-- ibge_cypher.py → ENRICH_MUNICIPALITY_PERMANENCIA
UNWIND $rows AS row
MATCH (m:Municipality {id: row.ibge_id})
SET m.qedu_permanencia     = row.permanencia,
    m.qedu_pct_fora_escola = row.fora,
    m.qedu_permanencia_ano = row.ano_censo
```

---

## 🔗 Relacionamentos

### `SQL_MUNICIPALITY_STATE_REL` + `LINK_MUNICIPALITY_STATE`

```sql
-- ibge_queries.py → SQL_MUNICIPALITY_STATE_REL
SELECT
    CAST(CodigoDoMunicipio AS INT) AS municipality_id,
    CodigoDaUF                     AS state_id
FROM BUF.City
```

```cypher
-- ibge_cypher.py → LINK_MUNICIPALITY_STATE
UNWIND $rows AS row
MATCH (m:Municipality {id: row.municipality_id})
MATCH (s:State        {id: row.state_id})
MERGE (m)-[:BELONGS_TO_STATE]->(s)
```

### `SQL_SCHOOL_GEOGRAPH_IBGE_JOIN` + `LINK_SCHOOL_GEOGRAPH_MUNICIPALITY`

O join usa `city` e `uf` já presentes no nó `SchoolGeograph` (propriedades `g.city` e `g.uf`
conforme `MERGE_SCHOOL_GEOGRAPH` em `queries.py`). A query cruza com `BUF.City` e `BUF.UF`
para obter o `ibge_id`.

```sql
-- ibge_queries.py → SQL_SCHOOL_GEOGRAPH_IBGE_JOIN
SELECT
    sg.HASH_ID                        AS school_geograph_id,
    CAST(c.CodigoDoMunicipio AS INT)  AS municipality_id
FROM dbo_tia.d_school_geograph sg
JOIN BUF.City c
    ON UPPER(sg.city) COLLATE Latin1_General_CI_AI
     = UPPER(c.Municipio) COLLATE Latin1_General_CI_AI
    AND UPPER(sg.uf) = (
        SELECT UPPER(u.Sigla_UF)
        FROM BUF.UF u
        WHERE u.UF_ID = c.CodigoDaUF
    )
```

```cypher
-- ibge_cypher.py → LINK_SCHOOL_GEOGRAPH_MUNICIPALITY
UNWIND $rows AS row
MATCH (sg:SchoolGeograph {id: row.school_geograph_id})
MATCH (m:Municipality    {id: row.municipality_id})
MERGE (sg)-[:LOCATED_IN_MUNICIPALITY]->(m)
```

---

## 🔧 `ibge_transformers.py`

```python
# src/utils/neo4j/ibge_transformers.py
"""
Transformers for IBGE data ingestion into Neo4j.
Same interface as src/utils/neo4j/transformers.py:
  - Each function receives a dict (one row) and returns a dict or None.
  - Returning None causes stream_to_neo4j to skip the row silently.
"""

import unicodedata
import re

# Each racial group keeps its own prefix.
# Grouping preto + pardo into "negro" is done at query time, not at ingest,
# to preserve full granularity.
COR_TO_PREFIX: dict[str, str] = {
    "branca":   "branco_",
    "preta":    "preto_",
    "parda":    "pardo_",
    "amarela":  "amarelo_",
    "indígena": "indigena_",
    "indigena": "indigena_",   # fallback without accent
}

SEXO_TO_PREFIX: dict[str, str] = {
    "homem":  "homem_",
    "mulher": "mulher_",
}


def normalize_city_name(name: str) -> str:
    """
    Strips accents, normalizes whitespace, and uppercases.
    Used as a Python fallback when SQL Server views are unavailable.
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(name))
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_str).strip().upper()


def transform_state_cor(row: dict) -> dict | None:
    """
    Maps COR field to a property prefix for dynamic SET in Cypher.
    Returns None for unmapped values — row is silently skipped.

    Output example: {..., 'prefix': 'pardo_', 'state_id': 28}
    """
    cor_key = str(row.get("COR", "")).strip().lower()
    prefix = COR_TO_PREFIX.get(cor_key)
    if not prefix:
        return None
    return {**row, "prefix": prefix, "state_id": int(row["state_id"])}


def transform_state_sexo(row: dict) -> dict | None:
    """
    Maps SEXO field to a property prefix.
    Output example: {..., 'prefix': 'mulher_', 'state_id': 28}
    """
    sexo_key = str(row.get("SEXO", "")).strip().lower()
    prefix = SEXO_TO_PREFIX.get(sexo_key)
    if not prefix:
        return None
    return {**row, "prefix": prefix, "state_id": int(row["state_id"])}


def transform_ideb_by_ciclo(row: dict) -> dict:
    """
    Uppercases ciclo_id ('ai', 'af', 'em' → 'AI', 'AF', 'EM') so the
    Cypher toLower() call produces consistent property names:
      qedu_ideb_ai, qedu_ideb_af, qedu_ideb_em
    """
    return {**row, "ciclo_id": str(row.get("ciclo_id", "")).strip().upper()}
```

---

## 🏗️ Estrutura de Arquivos

```
src/utils/neo4j/
├── airflow_tasks.py          ✅ Existente — zero alterações
├── ingestor.py               ✅ Existente — zero alterações
├── queries.py                ✅ Existente — NÃO tocar
├── transformers.py           ✅ Existente — NÃO tocar
│
├── ibge_queries.py           🆕 Todas as SQL queries do BUF/raw
│   # SQL_STATE
│   # SQL_STATE_COR
│   # SQL_STATE_SEXO
│   # SQL_MUNICIPALITY
│   # SQL_MUNICIPALITY_IDEB
│   # SQL_MUNICIPALITY_APRENDIZADO
│   # SQL_MUNICIPALITY_DISTORCAO
│   # SQL_MUNICIPALITY_RENDIMENTO
│   # SQL_MUNICIPALITY_PERMANENCIA
│   # SQL_MUNICIPALITY_STATE_REL
│   # SQL_SCHOOL_GEOGRAPH_IBGE_JOIN
│
├── ibge_cypher.py            🆕 Todos os Cypher MERGE/SET/LINK
│   # MERGE_STATE
│   # ENRICH_STATE_COR
│   # ENRICH_STATE_SEXO
│   # MERGE_MUNICIPALITY
│   # ENRICH_MUNICIPALITY_IDEB
│   # ENRICH_MUNICIPALITY_APRENDIZADO
│   # ENRICH_MUNICIPALITY_DISTORCAO
│   # ENRICH_MUNICIPALITY_RENDIMENTO
│   # ENRICH_MUNICIPALITY_PERMANENCIA
│   # LINK_MUNICIPALITY_STATE
│   # LINK_SCHOOL_GEOGRAPH_MUNICIPALITY
│
└── ibge_transformers.py      🆕 transform_state_cor, transform_state_sexo, transform_ideb_by_ciclo

dags/
├── dag__neo4j_full_migration.py          ✅ Existente
├── dag__neo4j_incremental_migration.py   ✅ Existente
└── dag__neo4j_ibge_migration.py          🆕 Novo DAG
```

---

## ⚠️ Ponto de Atenção: Join por Nome de Município

O join entre `BUF.Atlas_todos_Municipios.Territorialidades` e `BUF.City.Municipio` é por nome,
não por código. Criar a view abaixo uma única vez elimina o problema de encoding:

```sql
-- Rodar uma vez no SQL Server (requer permissão DDL no schema BUF)
CREATE VIEW BUF.vw_Atlas_Municipios_Normalized AS
SELECT UPPER(Territorialidades) COLLATE Latin1_General_CI_AI AS nome_norm, *
FROM BUF.Atlas_todos_Municipios;
```

Se não houver permissão, `normalize_city_name` em `ibge_transformers.py` resolve em Python —
com custo de trazer as ~5.570 linhas em memória antes do merge, aceitável dado o volume.

---

## ✈️ DAG: `dag__neo4j_ibge_migration.py`

```python
"""
DAG: Neo4j IBGE Migration.

Enriches Neo4j with external socioeconomic and educational data
from SQL Server BUF and raw schemas.

Strategy (3 Stages):
  Stage 0 – Indexes:       State, Municipality
  Stage 1 – Base Nodes:    State (PNAD), Municipality (Atlas)  — parallel
  Stage 2 – Enrichments:   State (Cor, Sexo) + Municipality (IDEB, Aprendizado,
                            Distorcao, Rendimento, Permanencia)  — all parallel
  Stage 3 – Relationships: Municipality->State, SchoolGeograph->Municipality
"""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.utils.neo4j.airflow_tasks import stream_to_neo4j
import src.utils.neo4j.ibge_queries as q
import src.utils.neo4j.ibge_cypher as c
import src.utils.neo4j.ibge_transformers as t

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


def create_ibge_indexes():
    from src.utils.neo4j.ingestor import Neo4jIngestor
    ingestor = Neo4jIngestor()
    for cypher in [
        "CREATE INDEX state_id IF NOT EXISTS FOR (s:State) ON (s.id)",
        "CREATE INDEX state_sigla IF NOT EXISTS FOR (s:State) ON (s.sigla)",
        "CREATE INDEX municipality_id IF NOT EXISTS FOR (m:Municipality) ON (m.id)",
        "CREATE INDEX municipality_name IF NOT EXISTS FOR (m:Municipality) ON (m.name)",
    ]:
        ingestor.run(cypher)


with DAG(
    'neo4j_ibge_migration',
    default_args=default_args,
    description='Enriches Neo4j with IBGE/QEdu data (State + Municipality nodes)',
    schedule=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['neo4j', 'ibge', 'migration'],
) as dag:

    # ----------------------------------------------------------
    # Stage 0: Indexes
    # ----------------------------------------------------------
    task_create_ibge_indexes = PythonOperator(
        task_id='create_ibge_indexes',
        python_callable=create_ibge_indexes,
    )

    # ----------------------------------------------------------
    # Stage 1: Nós base (paralelo)
    # ----------------------------------------------------------
    load_states = PythonOperator(
        task_id='load_states',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': q.SQL_STATE, 'cypher_query': c.MERGE_STATE},
    )

    load_municipalities = PythonOperator(
        task_id='load_municipalities',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': q.SQL_MUNICIPALITY, 'cypher_query': c.MERGE_MUNICIPALITY},
    )

    # ----------------------------------------------------------
    # Stage 2: Enriquecimentos (paralelo dentro de cada grupo)
    # ----------------------------------------------------------
    enrich_state_cor = PythonOperator(
        task_id='enrich_state_cor',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_STATE_COR,
            'cypher_query': c.ENRICH_STATE_COR,
            'transformer': t.transform_state_cor,
        },
    )

    enrich_state_sexo = PythonOperator(
        task_id='enrich_state_sexo',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_STATE_SEXO,
            'cypher_query': c.ENRICH_STATE_SEXO,
            'transformer': t.transform_state_sexo,
        },
    )

    enrich_municipality_ideb = PythonOperator(
        task_id='enrich_municipality_ideb',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_MUNICIPALITY_IDEB,
            'cypher_query': c.ENRICH_MUNICIPALITY_IDEB,
            'transformer': t.transform_ideb_by_ciclo,
        },
    )

    enrich_municipality_aprendizado = PythonOperator(
        task_id='enrich_municipality_aprendizado',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_MUNICIPALITY_APRENDIZADO,
            'cypher_query': c.ENRICH_MUNICIPALITY_APRENDIZADO,
            'transformer': t.transform_ideb_by_ciclo,
        },
    )

    enrich_municipality_distorcao = PythonOperator(
        task_id='enrich_municipality_distorcao',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_MUNICIPALITY_DISTORCAO,
            'cypher_query': c.ENRICH_MUNICIPALITY_DISTORCAO,
        },
    )

    enrich_municipality_rendimento = PythonOperator(
        task_id='enrich_municipality_rendimento',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_MUNICIPALITY_RENDIMENTO,
            'cypher_query': c.ENRICH_MUNICIPALITY_RENDIMENTO,
        },
    )

    enrich_municipality_permanencia = PythonOperator(
        task_id='enrich_municipality_permanencia',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_MUNICIPALITY_PERMANENCIA,
            'cypher_query': c.ENRICH_MUNICIPALITY_PERMANENCIA,
        },
    )

    # ----------------------------------------------------------
    # Stage 3: Relacionamentos
    # ----------------------------------------------------------
    link_municipality_state = PythonOperator(
        task_id='link_municipality_state',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_MUNICIPALITY_STATE_REL,
            'cypher_query': c.LINK_MUNICIPALITY_STATE,
        },
    )

    link_school_geograph_municipality = PythonOperator(
        task_id='link_school_geograph_municipality',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': q.SQL_SCHOOL_GEOGRAPH_IBGE_JOIN,
            'cypher_query': c.LINK_SCHOOL_GEOGRAPH_MUNICIPALITY,
        },
    )

    # ================================================================
    # Dependency Graph
    # ================================================================

    task_create_ibge_indexes >> [load_states, load_municipalities]

    load_states >> [enrich_state_cor, enrich_state_sexo]

    load_municipalities >> [
        enrich_municipality_ideb,
        enrich_municipality_aprendizado,
        enrich_municipality_distorcao,
        enrich_municipality_rendimento,
        enrich_municipality_permanencia,
    ]

    all_enrichments = [
        enrich_state_cor, enrich_state_sexo,
        enrich_municipality_ideb, enrich_municipality_aprendizado,
        enrich_municipality_distorcao, enrich_municipality_rendimento,
        enrich_municipality_permanencia,
    ]
    all_enrichments >> [link_municipality_state, link_school_geograph_municipality]
```

---

## ✅ Critérios de Verificação

```cypher
// 1. States criados
MATCH (s:State)
RETURN count(s) AS total, avg(s.pnad_idhm) AS media_idhm
// Esperado: 27 estados, IDHM médio entre 0.55 e 0.82

// 2. States com os três grupos raciais distintos
MATCH (s:State)
WHERE s.branco_pnad_idhm IS NOT NULL
  AND s.preto_pnad_idhm  IS NOT NULL
  AND s.pardo_pnad_idhm  IS NOT NULL
RETURN count(s) AS states_com_tres_grupos
// Esperado: próximo de 27

// 3. Gap de renda por raça por estado (branco vs preto vs pardo)
MATCH (s:State)
WHERE s.branco_pnad_rdpc IS NOT NULL
RETURN s.sigla,
       round(s.branco_pnad_rdpc, 0) AS rdpc_branco,
       round(s.preto_pnad_rdpc,  0) AS rdpc_preto,
       round(s.pardo_pnad_rdpc,  0) AS rdpc_pardo
ORDER BY s.sigla

// 4. Municipalities criados
MATCH (m:Municipality)
RETURN count(m) AS total
// Esperado: ~5.570

// 5. Cobertura de IDEB por ciclo
MATCH (m:Municipality)
WHERE m.qedu_ideb_af IS NOT NULL
RETURN count(m) AS com_ideb_af, avg(m.qedu_ideb_af) AS media
// Esperado: IDEB médio entre 3.5 e 5.5

// 6. SchoolGeograph ligadas a Municipality
MATCH (sg:SchoolGeograph)-[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
RETURN count(sg) AS linked, count(DISTINCT m) AS municipalities_touched
// Cruzar com: MATCH (sg:SchoolGeograph) RETURN count(sg)

// 7. Caminho completo Student → State usando relacionamentos reais do grafo
MATCH (s:Student)-[:ENROLLED_AT_SCHOOL]->(sc:School)
    -[:HAS_GEOGRAPHY]->(g:SchoolGeograph)
    -[:LOCATED_IN_MUNICIPALITY]->(m:Municipality)
    -[:BELONGS_TO_STATE]->(st:State)
RETURN count(s) AS students_com_contexto_completo

// 8. Brecha de infraestrutura digital por raça
MATCH (m:Municipality)
WHERE m.atl_branco_internet_fund IS NOT NULL
  AND m.atl_negro_internet_fund  IS NOT NULL
RETURN avg(m.atl_branco_internet_fund)                              AS media_branco_internet,
       avg(m.atl_negro_internet_fund)                               AS media_negro_internet,
       avg(m.atl_branco_internet_fund - m.atl_negro_internet_fund)  AS gap_medio
// Esperado: gap positivo (brancos com maior acesso)
```

---

## 📌 Pré-requisito: `dag__neo4j_full_migration`

Este DAG depende dos nós `SchoolGeograph` já existirem (criados por `link_school_geograph`
no DAG principal). Executar sempre **após** `dag__neo4j_full_migration` completar com sucesso.

Na interface do Airflow, usar trigger manual ou configurar um `ExternalTaskSensor` apontando
para a task `link_school_geograph` do DAG pai antes de liberar `load_states`.
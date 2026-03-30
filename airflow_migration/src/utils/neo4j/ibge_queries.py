"""
Neo4j Queries Module for IBGE Enrichment.

This module contains the SQL queries used to read data from SQL Server
BUF and raw schemas to ingest into Neo4j's State and Municipality nodes.
"""

SQL_STATE = """
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
"""

SQL_STATE_COR = """
SELECT
    CAST(t.CODIGO AS INT)  AS state_id,
    t.COR,
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
FROM raw.Atlas_PNAD_Estados_Total_Cor t
INNER JOIN (
    SELECT CODIGO, COR, MAX(ANO) AS max_ano
    FROM raw.Atlas_PNAD_Estados_Total_Cor
    GROUP BY CODIGO, COR
) latest ON t.CODIGO = latest.CODIGO AND t.COR = latest.COR AND t.ANO = latest.max_ano
WHERE TRY_CAST(t.CODIGO AS INT) IS NOT NULL AND CAST(t.CODIGO AS INT) > 10
"""

SQL_STATE_SEXO = """
SELECT
    CAST(t.CODIGO AS INT)  AS state_id,
    t.SEXO,
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
FROM raw.Atlas_PNAD_Estados_Total_Sexo t
INNER JOIN (
    SELECT CODIGO, SEXO, MAX(ANO) AS max_ano
    FROM raw.Atlas_PNAD_Estados_Total_Sexo
    GROUP BY CODIGO, SEXO
) latest ON t.CODIGO = latest.CODIGO AND t.SEXO = latest.SEXO AND t.ANO = latest.max_ano
WHERE TRY_CAST(t.CODIGO AS INT) IS NOT NULL AND CAST(t.CODIGO AS INT) > 10
"""

SQL_MUNICIPALITY = """
WITH PagedMunicipality AS (
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
    
        a.ano                                                           AS atl_ano,
        ROW_NUMBER() OVER(PARTITION BY c.CodigoDoMunicipio ORDER BY a.Territorialidades) as rn
    
    FROM BUF.City c
    LEFT JOIN BUF.Atlas_todos_Municipios a
        ON UPPER(a.Territorialidades) COLLATE Latin1_General_CI_AI = UPPER(c.Municipio) COLLATE Latin1_General_CI_AI
        AND a.ano = 2010
)
SELECT * FROM PagedMunicipality WHERE rn = 1
"""

SQL_MUNICIPALITY_IDEB = """
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
"""

SQL_MUNICIPALITY_APRENDIZADO = """
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
"""

SQL_MUNICIPALITY_DISTORCAO = """
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
"""

SQL_MUNICIPALITY_RENDIMENTO = """
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
"""

SQL_MUNICIPALITY_PERMANENCIA = """
SELECT p.ibge_id, p.ano_nascimento, p.ano_censo, p.permanencia, p.fora
FROM raw.QeduPermanenciaTodosAnos p
INNER JOIN (
    SELECT ibge_id, MAX(ano_censo) AS max_ano_censo
    FROM raw.QeduPermanenciaTodosAnos
    GROUP BY ibge_id
) latest ON p.ibge_id = latest.ibge_id AND p.ano_censo = latest.max_ano_censo
"""

SQL_MUNICIPALITY_STATE_REL = """
SELECT
    CAST(CodigoDoMunicipio AS INT) AS municipality_id,
    CodigoDaUF                     AS state_id
FROM BUF.City
"""

SQL_SCHOOL_GEOGRAPH_IBGE_JOIN = """
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
"""

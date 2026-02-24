"""
Neo4j Cypher Module for IBGE Enrichment.

This module contains the Cypher queries used to ingest data into the Neo4j graph using the UNWIND pattern.
"""

MERGE_STATE = """
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
"""

ENRICH_STATE_COR = """
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
"""

ENRICH_STATE_SEXO = """
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
"""

MERGE_MUNICIPALITY = """
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
"""

ENRICH_MUNICIPALITY_IDEB = """
UNWIND $rows AS row
MATCH (s:State {id: row.ibge_id})
SET s['qedu_ideb_'        + toLower(row.ciclo_id)] = row.ideb,
    s['qedu_fluxo_'       + toLower(row.ciclo_id)] = row.fluxo,
    s['qedu_aprendizado_' + toLower(row.ciclo_id)] = row.aprendizado,
    s['qedu_nota_mt_'     + toLower(row.ciclo_id)] = row.nota_mt,
    s['qedu_nota_lp_'     + toLower(row.ciclo_id)] = row.nota_lp,
    s['qedu_ideb_ano_'    + toLower(row.ciclo_id)] = row.ano
"""

ENRICH_MUNICIPALITY_APRENDIZADO = """
UNWIND $rows AS row
MATCH (s:State {id: row.ibge_id})
SET s['qedu_lp_adequado_'     + toLower(row.ciclo_id)] = row.lp_adequado,
    s['qedu_mt_adequado_'     + toLower(row.ciclo_id)] = row.mt_adequado,
    s['qedu_lp_insuficiente_' + toLower(row.ciclo_id)] = row.lp_insuficiente,
    s['qedu_lp_basico_'       + toLower(row.ciclo_id)] = row.lp_basico,
    s['qedu_lp_proficiente_'  + toLower(row.ciclo_id)] = row.lp_proficiente,
    s['qedu_lp_avancado_'     + toLower(row.ciclo_id)] = row.lp_avancado,
    s['qedu_mt_insuficiente_' + toLower(row.ciclo_id)] = row.mt_insuficiente,
    s['qedu_mt_basico_'       + toLower(row.ciclo_id)] = row.mt_basico,
    s['qedu_mt_proficiente_'  + toLower(row.ciclo_id)] = row.mt_proficiente,
    s['qedu_mt_avancado_'     + toLower(row.ciclo_id)] = row.mt_avancado
"""

ENRICH_MUNICIPALITY_DISTORCAO = """
UNWIND $rows AS row
MATCH (s:State {id: row.ibge_id})
SET s.qedu_distorcao_ef1      = row.ef_1ano,
    s.qedu_distorcao_ef2      = row.ef_2ano,
    s.qedu_distorcao_ef3      = row.ef_3ano,
    s.qedu_distorcao_ef4      = row.ef_4ano,
    s.qedu_distorcao_ef5      = row.ef_5ano,
    s.qedu_distorcao_ef6      = row.ef_6ano,
    s.qedu_distorcao_ef7      = row.ef_7ano,
    s.qedu_distorcao_ef8      = row.ef_8ano,
    s.qedu_distorcao_ef9      = row.ef_9ano,
    s.qedu_distorcao_ef_ai    = row.ef_total_ai,
    s.qedu_distorcao_ef_af    = row.ef_total_af,
    s.qedu_distorcao_ef_total = row.ef_total,
    s.qedu_distorcao_em1      = row.em_1ano,
    s.qedu_distorcao_em2      = row.em_2ano,
    s.qedu_distorcao_em3      = row.em_3ano,
    s.qedu_distorcao_em_total = row.em_total,
    s.qedu_distorcao_ano      = row.ano
"""

ENRICH_MUNICIPALITY_RENDIMENTO = """
UNWIND $rows AS row
MATCH (s:State {id: row.ibge_id})
SET s.qedu_total_matriculas = row.total_matriculas,
    s.qedu_taxa_aprovacao   = row.taxa_aprovacao,
    s.qedu_taxa_reprovacao  = row.taxa_reprovacao,
    s.qedu_taxa_abandono    = row.taxa_abandono,
    s.qedu_rendimento_ano   = row.ano
"""

ENRICH_MUNICIPALITY_PERMANENCIA = """
UNWIND $rows AS row
MATCH (s:State {id: row.ibge_id})
SET s.qedu_permanencia     = row.permanencia,
    s.qedu_pct_fora_escola = row.fora,
    s.qedu_permanencia_ano = row.ano_censo
"""

LINK_MUNICIPALITY_STATE = """
UNWIND $rows AS row
MATCH (m:Municipality {id: row.municipality_id})
MATCH (s:State        {id: row.state_id})
MERGE (m)-[:BELONGS_TO_STATE]->(s)
"""

LINK_SCHOOL_GEOGRAPH_MUNICIPALITY = """
UNWIND $rows AS row
MATCH (sg:SchoolGeograph {id: row.school_geograph_id})
MATCH (m:Municipality    {id: row.municipality_id})
MERGE (sg)-[:LOCATED_IN_MUNICIPALITY]->(m)
"""

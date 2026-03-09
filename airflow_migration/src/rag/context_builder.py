import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_CHARS = 16_000


def _truncate(text: str) -> str:
    if len(text) > _MAX_CHARS:
        logger.warning("Contexto truncado de %d para %d chars", len(text), _MAX_CHARS)
        return text[:_MAX_CHARS] + "\n[contexto truncado por limite de tokens]"
    return text


def build_student_context(
    student_ctx: dict[str, Any],
    similar: list[dict],
    include_ibge: bool = True,
) -> str:
    """
    Serializa contexto de aluno para o prompt.

    Args:
        student_ctx: Saída de Retriever.get_student_context().
        similar: Saída de Retriever.find_similar_students().
        include_ibge: Se False, omite seção IBGE (reduz tokens).

    Returns:
        String ≤ 16.000 chars.
    """
    parts: list[str] = []

    p = student_ctx.get("perfil", {})
    risk_str = ""
    if p.get("risk_score") is not None:
        risk_str = f", risco_predito={p['risk_score']:.0f}%, cluster={p.get('risk_cluster', '?')}"
    parts.append(
        f"[PERFIL] gênero={p.get('gender','?')}, etnia={p.get('ethnicity','não declarada')}, "
        f"bolsa_família={p.get('bolsa_familia', False)}, PCD={p.get('has_deficiency', False)}, "
        f"zona={p.get('residence_zone','?')}{risk_str}"
    )

    f = student_ctx.get("frequencia", {})
    if not f.get("tem_diario"):
        parts.append("[FREQUÊNCIA] escola sem diário eletrônico — dado ausente")
    elif f.get("taxa_ausencia") is not None:
        alerta = " ⚠️ CRÍTICO: acima de 25%" if f["taxa_ausencia"] > 25 else ""
        parts.append(
            f"[FREQUÊNCIA] ausência={f['taxa_ausencia']}% dos dias "
            f"({f.get('total_faltas', 0)} faltas / {f.get('total_dias', 200)} dias){alerta}"
        )

    notas = [n for n in (student_ctx.get("notas") or []) if n.get("nota_final") is not None]
    if not notas:
        parts.append("[NOTAS] sem notas cadastradas no sistema")
    else:
        nota_lines = []
        for n in notas:
            traj = ""
            if n.get("nota_g1") is not None and n.get("nota_final") is not None:
                delta = n["nota_final"] - n["nota_g1"]
                traj  = f" (Δ1ºbim: {'+' if delta >= 0 else ''}{delta:.1f})"
            alerta = " ⚠️" if n.get("nota_final", 10) < 5 else ""
            nota_lines.append(f"  {n['disciplina']}: {n['nota_final']:.1f}{traj}{alerta}")
        parts.append("[NOTAS]\n" + "\n".join(nota_lines))

    s = student_ctx.get("saude", {})
    if s.get("tem_registro"):
        conds = [k for k in ["malnutrition","diabetes","obesity","hypertension","celiac","anemia"] if s.get(k)]
        parts.append(f"[SAÚDE] condições: {', '.join(conds) or 'nenhuma registrada'}")
    else:
        parts.append("[SAÚDE] sem registro de saúde para este aluno")

    if include_ibge:
        ei = student_ctx.get("escola_ibge", {})
        if ei.get("nome"):
            fonte = ei.get("fonte_freq_ibge", "?")
            ibge_parts = [
                f"escola={ei.get('nome','?')}, município={ei.get('municipio','?')}, UF={ei.get('uf','?')}"
            ]
            if ei.get("muni_freq_liq"):
                ibge_parts.append(f"IBGE_freq_liq_muni={ei['muni_freq_liq']:.1f}% [{fonte}]")
            if ei.get("muni_analf_adulto"):
                ibge_parts.append(f"analf_adulto_muni={ei['muni_analf_adulto']:.1f}%")
            if ei.get("est_ideb_af"):
                ibge_parts.append(f"IDEB_AF_estado={ei['est_ideb_af']}")
            if ei.get("est_taxa_abandono"):
                ibge_parts.append(f"abandono_estado={ei['est_taxa_abandono']:.1f}%")
            parts.append("[CONTEXTO IBGE] " + ", ".join(ibge_parts))

    t = student_ctx.get("turma", {})
    if t.get("nome"):
        parts.append(f"[TURMA] {t.get('nome','?')} | {t.get('grade_level','?')} | ano={t.get('ano_letivo','?')}")

    if similar:
        sim_lines = [
            f"  similarity={s['similarity']:.2f}: cluster={s.get('cluster','?')}, "
            f"escola={s.get('escola','?')}, desfecho={s.get('desfecho','?')}"
            for s in similar[:5]
        ]
        parts.append("[ALUNOS SIMILARES — o que aconteceu com perfis parecidos]\n" + "\n".join(sim_lines))

    return _truncate("\n".join(parts))


def build_classroom_context(classroom_ctx: dict[str, Any]) -> str:
    """
    Serializa contexto de turma para o prompt.

    Inclui Q15 features + Q8 composite risk + IBGE com fonte.
    """
    if not classroom_ctx:
        return "[TURMA] dados não encontrados"

    c = classroom_ctx
    n = c.get("n_alunos", 0)

    alerta_risco = ""
    risco = c.get("soma_sinais_risco")
    if risco is not None:
        nivel = "CRÍTICO ⚠️" if risco > 0.6 else "ALERTA" if risco > 0.35 else "MODERADO"
        alerta_risco = f" → risco composto={risco:.2f} ({nivel})"

    parts = [
        f"[TURMA] {c.get('classroom_name','?')} | {c.get('grade_level','?')} | {c.get('stage','?')}",
        f"[COMPOSIÇÃO] {n} alunos: BF={c.get('n_bolsistas',0)} ({c.get('n_bolsistas',0)/max(n,1)*100:.0f}%), "
        f"PCD={c.get('n_pcd',0)}, rural={c.get('n_rural',0)}, risco_saúde={c.get('n_risco_saude',0)}",
        f"[FREQUÊNCIA] ausência={c.get('taxa_ausencia_pct','?')}%, "
        f"alunos_com_falta={c.get('pct_com_falta','?')}%, "
        f"diário={'disponível' if c.get('tem_diario') else '⚠️ SEM DIÁRIO'}",
        f"[NOTAS] média={c.get('media_nota','?')}, dispersão={c.get('dispersao_nota','?')}, "
        f"CV%={c.get('cv_nota_pct','?')}%, "
        f"abaixo_5={c.get('pct_abaixo5','?')}%, "
        f"notas={'disponíveis' if c.get('tem_notas') else '⚠️ SEM NOTAS'}",
        f"[RISCO COMPOSTO Q8]{alerta_risco}",
        f"[IBGE] freq_liq_muni={c.get('muni_freq_liq','?')} [{c.get('fonte_freq_ibge','?')}], "
        f"abandono_estado={c.get('est_abandono','?')}, IDEB_AF={c.get('est_ideb_af','?')}",
    ]
    return _truncate("\n".join(parts))


def build_school_context(
    school_ctx: dict[str, Any],
    similar_schools: list[dict] | None = None,
) -> str:
    """
    Serializa contexto de escola em 4 dimensões + IBGE + escolas similares.
    """
    if not school_ctx:
        return "[ESCOLA] não encontrada"

    s = school_ctx
    n = s.get("n_alunos", 0)

    parts = [
        f"[ESCOLA] {s.get('school_name','?')} | município={s.get('municipio','?')}, UF={s.get('uf','?')}",
        f"[ESCOPO] {n} alunos em {s.get('n_turmas','?')} turmas",
    ]

    aus = s.get("taxa_ausencia_pct")
    aus_str = f"{aus:.1f}%" if aus is not None else "sem diário"
    freq_ibge = s.get("muni_freq_liq")
    delta_freq = ""
    if aus is not None and freq_ibge is not None:
        delta = aus - (100 - freq_ibge)
        delta_str = f"+{delta:.1f}pp acima" if delta > 0 else f"{delta:.1f}pp abaixo"
        delta_freq = f" ({delta_str} da ref. IBGE [{s.get('fonte_freq_ibge','?')}])"
    parts.append(
        f"[PRESENÇA] ausência={aus_str}{delta_freq} | "
        f"diário={'disponível' if s.get('tem_diario') else '⚠️ SEM DIÁRIO'} | "
        f"falta_crítica(>25%)={s.get('n_falta_critica',0)} alunos"
    )

    nota = s.get("media_nota")
    nota_str = f"{nota:.1f}" if nota is not None else "sem notas"
    parts.append(
        f"[DESEMPENHO] média={nota_str}, dispersão={s.get('dispersao_nota','?')}, "
        f"abaixo_5={s.get('pct_abaixo5','?')}% | "
        f"notas={'disponíveis' if s.get('tem_notas') else '⚠️ SEM NOTAS'}"
    )

    gap_bf = s.get("gap_bf")
    gap_str = f"{gap_bf:+.2f}" if gap_bf is not None else "N/A"
    parts.append(
        f"[EQUIDADE] BF={s.get('pct_bolsa_familia','?')}% dos alunos | "
        f"nota_BF={s.get('media_nota_bf','?')} vs nota_não-BF={s.get('media_nota_nobf','?')} (gap={gap_str}) | "
        f"PCD={s.get('n_pcd',0)}, rural={s.get('n_rural',0)}"
    )

    parts.append(
        f"[SAÚDE] com_registro={s.get('n_com_saude',0)} | "
        f"desnutrição={s.get('n_desnutridos',0)}, diabetes={s.get('n_diabetes',0)}, obesidade={s.get('n_obesidade',0)}"
    )

    parts.append(
        f"[IBGE] freq_liq_muni={s.get('muni_freq_liq','?')} [{s.get('fonte_freq_ibge','?')}], "
        f"analf_adulto={s.get('muni_analf','?')}, atraso_2anos={s.get('muni_atraso','?')}, "
        f"expectativa_estudo={s.get('muni_expectativa','?')} anos"
    )

    parts.append(
        f"[BENCHMARKS ESTADO] IDEB_AF={s.get('est_ideb_af','?')}, "
        f"abandono={s.get('est_abandono','?')}%, reprovação={s.get('est_reprovacao','?')}%, "
        f"distorção_AF={s.get('est_distorcao_af','?')}%, "
        f"LP_adequado={s.get('est_lp_adequado','?')}%, Mat_adequado={s.get('est_mat_adequado','?')}%"
    )

    if similar_schools:
        sim_lines = [
            f"  similarity={sc['similarity']:.2f}: {sc.get('escola','?')} "
            f"({sc.get('municipio','?')}-{sc.get('uf','?')}), nível={sc.get('nivel_saude','?')}"
            for sc in similar_schools[:3]
        ]
        parts.append("[ESCOLAS SIMILARES — referência comparativa]\n" + "\n".join(sim_lines))

    return _truncate("\n".join(parts))


def build_municipality_context(municipio_ctx: dict[str, Any]) -> str:
    """
    Serializa contexto de município: ranking escolas + IBGE + benchmarks.
    Ordena escolas por taxa de ausência desc para destacar as mais críticas.
    """
    if not municipio_ctx:
        return "[MUNICÍPIO] não encontrado"

    m = municipio_ctx
    escolas = sorted(
        [e for e in (m.get("escolas") or []) if e.get("taxa_ausencia") is not None],
        key=lambda e: e.get("taxa_ausencia", 0), reverse=True,
    )
    sem_diario = [e for e in (m.get("escolas") or []) if not e.get("tem_diario", True)]

    parts = [
        f"[MUNICÍPIO] {m.get('municipio','?')} — UF {m.get('uf','?')}",
        f"[ESCOPO] {m.get('n_escolas','?')} escolas, {m.get('total_alunos','?')} alunos",
    ]

    if sem_diario:
        nomes = ", ".join(e.get("school_name", e.get("school_id", "?")) for e in sem_diario[:5])
        parts.append(f"[COBERTURA DIGITAL] {len(sem_diario)} escola(s) sem diário eletrônico: {nomes}")

    parts.append(
        f"[RESUMO MUNICÍPIO] ausência_média={m.get('media_ausencia_muni','?')}%, "
        f"nota_média={m.get('media_nota_muni','?')}"
    )

    if escolas:
        escola_lines = [
            f"  {e.get('school_name', e.get('school_id','?'))}: "
            f"ausência={e.get('taxa_ausencia','?')}%, nota={e.get('media_nota','?')}, "
            f"BF={e.get('pct_bf','?')}%, alunos={e.get('n_alunos','?')}"
            for e in escolas[:5]
        ]
        parts.append("[TOP ESCOLAS — MAIOR AUSÊNCIA]\n" + "\n".join(escola_lines))

    fonte = m.get("fonte_freq_ibge", "?")
    parts.append(
        f"[IBGE MUNICIPAL] freq_liq={m.get('muni_freq_liq','?')} [{fonte}], "
        f"atraso_2anos={m.get('muni_atraso_2anos','?')}%, analf_adulto={m.get('muni_analf','?')}%, "
        f"expectativa_estudo={m.get('muni_expectativa','?')} anos"
    )

    if m.get("muni_negro_pub") or m.get("muni_negro_internet"):
        parts.append(
            f"[EQUIDADE RACIAL MUNI] negro_mat_pub_fund={m.get('muni_negro_pub','?')}%, "
            f"negro_internet_fund={m.get('muni_negro_internet','?')}%"
        )

    parts.append(
        f"[BENCHMARKS ESTADO] IDEB_AF={m.get('est_ideb_af','?')}, "
        f"abandono={m.get('est_abandono','?')}%, reprovação={m.get('est_reprovacao','?')}%, "
        f"distorção_AF={m.get('est_distorcao_af','?')}%, "
        f"fora_escola={m.get('est_pct_fora_escola','?')}%"
    )

    if m.get("est_analf_negro") or m.get("est_analf_branco"):
        parts.append(
            f"[PNAD RACIAL ESTADO] analf_negro={m.get('est_analf_negro','?')}%, "
            f"analf_branco={m.get('est_analf_branco','?')}%, "
            f"atraso_negro={m.get('est_atraso_negro','?')}%, atraso_branco={m.get('est_atraso_branco','?')}%"
        )

    return _truncate("\n".join(parts))


def build_state_context(state_ctx: dict[str, Any]) -> str:
    """
    Serializa contexto de estado: QEdu + PNAD racial + PNAD gênero + municípios.
    """
    if not state_ctx:
        return "[ESTADO] não encontrado"

    s = state_ctx

    municipios = [m for m in (s.get("municipios") or []) if m.get("muni_analf") is not None]
    municipios_sorted = sorted(municipios, key=lambda m: m.get("muni_analf", 0), reverse=True)

    parts = [
        f"[ESTADO] {s.get('nome_estado','?')} — UF {s.get('uf','?')}",
        f"[ESCOPO] {s.get('n_municipios','?')} municípios | {s.get('total_matriculas','?')} matrículas",

        f"[IDEB] AI={s.get('ideb_ai','?')}, AF={s.get('ideb_af','?')}, EM={s.get('ideb_em','?')}",
        f"[FLUXO] fluxo_AI={s.get('fluxo_ai','?')}, fluxo_AF={s.get('fluxo_af','?')}",
        f"[DISTORÇÃO] EF_AI={s.get('distorcao_ai','?')}%, EF_AF={s.get('distorcao_af','?')}%",
        f"[ABANDONO/REPROVAÇÃO] abandono={s.get('abandono','?')}%, reprovação={s.get('reprovacao','?')}%, "
        f"fora_escola={s.get('pct_fora_escola','?')}%",

        f"[PROFICIÊNCIA] LP_adequado_AI={s.get('lp_adequado_ai','?')}%, Mat_adequado_AI={s.get('mat_adequado_ai','?')}%, "
        f"LP_adequado_AF={s.get('lp_adequado_af','?')}%, Mat_adequado_AF={s.get('mat_adequado_af','?')}%, "
        f"LP_insuf_AF={s.get('lp_insuf_af','?')}%, Mat_insuf_AF={s.get('mat_insuf_af','?')}%",

        f"[PNAD RACIAL] analf_negro={s.get('analf_negro','?')}% vs analf_branco={s.get('analf_branco','?')}% | "
        f"atraso_negro={s.get('atraso_negro','?')}% vs atraso_branco={s.get('atraso_branco','?')}% | "
        f"IDHM_e_negro={s.get('idhm_e_negro','?')} vs IDHM_e_branco={s.get('idhm_e_branco','?')} | "
        f"freq_fund_negro={s.get('freq_fund_negro','?')}% vs freq_fund_branco={s.get('freq_fund_branco','?')}% | "
        f"médio_completo(18–20)_negro={s.get('med18_negro','?')}% vs branco={s.get('med18_branco','?')}%",

        f"[PNAD GÊNERO] analf_homem={s.get('analf_homem','?')}% vs analf_mulher={s.get('analf_mulher','?')}% | "
        f"anos_estudo_homem={s.get('anosest_homem','?')} vs mulher={s.get('anosest_mulher','?')} | "
        f"freq_fund_homem={s.get('freq_fund_homem','?')}% vs mulher={s.get('freq_fund_mulher','?')}%",
    ]

    if municipios_sorted:
        muni_lines = [
            f"  {m.get('municipio','?')}: analf={m.get('muni_analf','?')}%, "
            f"atraso={m.get('muni_atraso','?')}%, expectativa={m.get('muni_expectativa','?')} anos"
            for m in municipios_sorted[:5]
        ]
        parts.append("[MUNICÍPIOS COM MAIOR FRAGILIDADE (top 5 por analfabetismo adulto)]\n" + "\n".join(muni_lines))

    return _truncate("\n".join(parts))

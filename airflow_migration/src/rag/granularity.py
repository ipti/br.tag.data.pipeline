from enum import Enum


class Granularity(str, Enum):
    ALUNO     = "aluno"
    TURMA     = "turma"
    ESCOLA    = "escola"
    MUNICIPIO = "municipio"
    ESTADO    = "estado"


_KEYWORDS: dict[Granularity, list[str]] = {
    Granularity.ALUNO:     ["aluno", "estudante", "criança", "ele", "ela", "matrícula"],
    Granularity.TURMA:     ["turma", "sala", "classe", "7º ano", "8º ano", "9º ano",
                            "6º ano", "1º ano", "2º ano", "3º ano", "4º ano", "5º ano"],
    Granularity.ESCOLA:    ["escola", "unidade", "colégio", "instituição", "estabelecimento"],
    Granularity.MUNICIPIO: ["município", "municipio", "cidade", "prefeitura",
                            "secretaria municipal"],
    Granularity.ESTADO:    ["estado", "uf", "seduc", "secretaria estadual", "governo estadual",
                            "nordeste", "sudeste", "sul", "norte", "centro-oeste"],
}


def identify_granularity(question: str, hint: str | None = None) -> Granularity:
    """
    Identifica a granularidade da pergunta por palavras-chave.

    Args:
        question: Pergunta do gestor em texto livre.
        hint: Granularidade explícita se o frontend já sabe (ex: 'escola').
              Sobrescreve a detecção automática.

    Returns:
        Granularity enum.
    """
    if hint:
        try:
            return Granularity(hint.lower())
        except ValueError:
            pass

    q = question.lower()
    for gran in [Granularity.ALUNO, Granularity.TURMA, Granularity.MUNICIPIO,
                 Granularity.ESTADO, Granularity.ESCOLA]:
        if any(kw in q for kw in _KEYWORDS[gran]):
            return gran

    return Granularity.ESCOLA

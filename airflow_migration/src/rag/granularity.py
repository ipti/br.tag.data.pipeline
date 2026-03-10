from enum import Enum


class Granularity(str, Enum):
    """
    Educational entity granularity levels.

    Enumeration of five hierarchical scopes for question routing in the RAG pipeline.
    Each level corresponds to a distinct context retrieval strategy and LLM template.
    """

    ALUNO = "aluno"
    TURMA = "turma"
    ESCOLA = "escola"
    MUNICIPIO = "municipio"
    ESTADO = "estado"


_KEYWORDS: dict[Granularity, list[str]] = {
    Granularity.ALUNO: ["aluno", "estudante", "criança", "ele", "ela", "matrícula"],
    Granularity.TURMA: [
        "turma",
        "sala",
        "classe",
        "7º ano",
        "8º ano",
        "9º ano",
        "6º ano",
        "1º ano",
        "2º ano",
        "3º ano",
        "4º ano",
        "5º ano",
    ],
    Granularity.ESCOLA: [
        "escola",
        "unidade",
        "colégio",
        "instituição",
        "estabelecimento",
    ],
    Granularity.MUNICIPIO: [
        "município",
        "municipio",
        "cidade",
        "prefeitura",
        "secretaria municipal",
    ],
    Granularity.ESTADO: [
        "estado",
        "uf",
        "seduc",
        "secretaria estadual",
        "governo estadual",
        "nordeste",
        "sudeste",
        "sul",
        "norte",
        "centro-oeste",
    ],
}


def identify_granularity(question: str, hint: str | None = None) -> Granularity:
    """
    Identify the granularity level of a question using keyword detection and optional hints.

    This function routes educational management questions to appropriate context retrieval
    by matching keywords against five granularity levels. If an explicit hint is provided
    (e.g., from the frontend), it overrides keyword-based detection. Falls back to ESCOLA
    (school) if no keywords match, as it is the most common analysis scope.

    Args:
        question (str): Free-form question text from an educational manager or administrator,
            in Portuguese. May span multiple sentences.
        hint (str, optional): Explicit granularity hint (e.g., 'aluno', 'escola', 'estado').
            If provided and valid, overrides keyword detection. Defaults to None.

    Returns:
        Granularity: Detected or hinted granularity enum value (ALUNO, TURMA, ESCOLA,
            MUNICIPIO, or ESTADO).

    Examples:
        >>> identify_granularity("Como vai o João?", hint="aluno")
        <Granularity.ALUNO: 'aluno'>
        >>> identify_granularity("A turma 7A está com muita falta")
        <Granularity.TURMA: 'turma'>
        >>> identify_granularity("?")  # No matches, defaults to ESCOLA
        <Granularity.ESCOLA: 'escola'>
    """
    if hint:
        try:
            return Granularity(hint.lower())
        except ValueError:
            pass

    q = question.lower()
    for gran in [
        Granularity.ALUNO,
        Granularity.TURMA,
        Granularity.MUNICIPIO,
        Granularity.ESTADO,
        Granularity.ESCOLA,
    ]:
        if any(kw in q for kw in _KEYWORDS[gran]):
            return gran

    return Granularity.ESCOLA

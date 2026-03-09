import logging
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """Carrega modelo uma vez (singleton). Thread-safe para uso em API."""
    global _model
    if _model is None:
        logger.info("Carregando modelo de embedding: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def student_to_text(row: pd.Series) -> str:
    """
    Serializa uma linha de features de aluno em texto descritivo.

    Valores nulos são substituídos por frases neutras — ausência de dado é
    informação diferente de condição negativa.

    Args:
        row: Series com colunas do DEMO_FEATURES + HEALTH_FEATURES + FREQ_FEATURES.

    Returns:
        String de ~100–200 palavras descrevendo o perfil do aluno.
    """
    def fmt_nota(v) -> str:
        if pd.isna(v): return "sem nota registrada"
        return f"{v:.1f}"

    def fmt_ausencia(taxa, tem_diario) -> str:
        if not tem_diario: return "sem diário eletrônico na escola"
        if pd.isna(taxa): return "ausência não informada"
        return f"{taxa * 100:.0f}% de faltas"

    health_flags = []
    for cond in ["has_malnutrition", "has_diabetes", "has_hypertension", "has_obesity", "has_anemia", "has_celiac"]:
        if row.get(cond, 0):
            health_flags.append(cond.replace("has_", ""))
    health_str = ", ".join(health_flags) if health_flags else "sem condições registradas"

    return (
        f"Aluno: gênero {'feminino' if row.get('gender_bin') else 'masculino'}, "
        f"etnia {row.get('ethnicity_raw', 'não declarada')}, "
        f"zona {'rural' if row.get('residence_zone_enc', 1) == 0 else 'urbana'}, "
        f"bolsa família {'sim' if row.get('bolsa_familia') else 'não'}, "
        f"deficiência {'sim' if row.get('has_deficiency') else 'não'}. "
        f"Frequência: {fmt_ausencia(row.get('taxa_ausencia'), row.get('tem_diario', 0))}. "
        f"Nota: {fmt_nota(row.get('nota_final_norm'))}. "
        f"Saúde: {health_str}. "
        f"Contexto: UF {row.get('uf', '?')}, "
        f"IBGE freq_liq_muni {row.get('muni_freq_liq_fund', '?')}, "
        f"IDEB estadual {row.get('est_ideb_af', '?')}, "
        f"abandono estadual {row.get('est_taxa_abandono', 0):.1%}. "
        f"Cluster de risco: {row.get('risk_cluster', 'não atribuído')}."
    )


def embed_students(df: pd.DataFrame, batch_size: int = 256) -> np.ndarray:
    """
    Gera embeddings para todos os alunos no DataFrame.

    Args:
        df: DataFrame com colunas de features de aluno.
        batch_size: Tamanho do batch para controle de memória.

    Returns:
        ndarray shape (N, 384) com embeddings normalizados.
    """
    model = get_model()
    texts = [student_to_text(row) for _, row in df.iterrows()]
    logger.info("Gerando embeddings para %d alunos (batch_size=%d)", len(texts), batch_size)
    embeddings = model.encode(texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True)
    logger.info("Embeddings gerados: shape=%s", embeddings.shape)
    return embeddings

"""
Student embedding generation module.

This module converts student demographic, health, and academic records into
normalized vector embeddings for semantic search and similarity analysis. It provides
utilities to serialize student data into narrative text and batch-encode the text
using a multilingual sentence transformer model. The embeddings enable downstream
applications like student clustering, risk assessment matching, and similarity-based
recommendations.
"""

import logging
import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    """
    Load and cache the sentence transformer model as a singleton.

    This function loads the multilingual embedding model once and reuses it
    across all calls, ensuring thread-safe access to a shared model instance.
    The model is cached in module-level state to avoid expensive reload operations.

    Returns:
        SentenceTransformer: The paraphrase-multilingual-MiniLM-L12-v2 model instance.
    """
    global _model
    if _model is None:
        logger.info("Carregando modelo de embedding: %s", _MODEL_NAME)
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def student_to_text(row: pd.Series) -> str:
    """
    Convert a student feature row into a natural language profile text.

    This function serializes a student record containing demographic, health, and
    attendance features into a structured narrative description. Null values are
    replaced with contextually appropriate neutral phrases to distinguish missing
    data from negative conditions. The output text is optimized for sentence
    transformer embedding.

    Args:
        row (pd.Series): A pandas Series containing student demographic features
            (gender, ethnicity, residence zone, social programs), health conditions
            (malnutrition, diabetes, hypertension, obesity, anemia, celiac),
            attendance metrics, grades, and contextual geographic/institutional data
            (state, municipality, IBGE liquid enrollment, IDEB index, risk cluster).

    Returns:
        str: A narrative description of the student profile (approximately 100-200 words)
            including demographic attributes, academic performance, health status,
            and educational context metrics.
    """

    def fmt_nota(v) -> str:
        if pd.isna(v):
            return "sem nota registrada"
        return f"{v:.1f}"

    def fmt_ausencia(taxa, tem_diario) -> str:
        if not tem_diario:
            return "sem diário eletrônico na escola"
        if pd.isna(taxa):
            return "ausência não informada"
        return f"{taxa * 100:.0f}% de faltas"

    health_flags = []
    for cond in [
        "has_malnutrition",
        "has_diabetes",
        "has_hypertension",
        "has_obesity",
        "has_anemia",
        "has_celiac",
    ]:
        if row.get(cond, 0):
            health_flags.append(cond.replace("has_", ""))
    health_str = (
        ", ".join(health_flags) if health_flags else "sem condições registradas"
    )

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
    Generate normalized embeddings for all students in a DataFrame.

    This function orchestrates the embedding generation pipeline for a batch of
    students. It converts each student record to narrative text using `student_to_text()`,
    loads the shared model via `get_model()`, and invokes the sentence transformer
    encoder with batch processing to control memory consumption. All embeddings are
    L2-normalized for use in vector similarity search.

    Args:
        df (pd.DataFrame): A DataFrame containing student feature columns compatible
            with `student_to_text()` (demographic, health, attendance, grade features).
        batch_size (int, optional): Number of sentences to encode in each model batch.
            Defaults to 256. Larger batches improve throughput but increase peak memory.

    Returns:
        np.ndarray: A 2D array of shape (N, 384) containing L2-normalized embeddings
            for each student, where N is the number of rows in the input DataFrame.
    """
    model = get_model()
    texts = [student_to_text(row) for _, row in df.iterrows()]
    logger.info(
        "Gerando embeddings para %d alunos (batch_size=%d)", len(texts), batch_size
    )
    embeddings = model.encode(
        texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True
    )
    logger.info("Embeddings gerados: shape=%s", embeddings.shape)
    return embeddings

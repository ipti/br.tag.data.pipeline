"""
School embedding generation module.

This module converts school-level metrics and institutional data into normalized
vector embeddings for semantic search and institutional clustering. It provides utilities
to serialize aggregated school performance indicators, health program status, and
socioeconomic enrollment data into narrative text for encoding by a multilingual sentence
transformer model. The embeddings enable downstream applications such as school similarity
search, performance benchmarking, and policy target matching.
"""

import logging
import numpy as np
import pandas as pd
from .student_embedder import get_model

logger = logging.getLogger(__name__)


def school_to_text(row: pd.Series) -> str:
    """
    Convert a school metrics row into a natural language institutional profile text.

    This function serializes aggregated school-level metrics including health program
    status, attendance rates, academic performance, and enrollment composition into a
    structured narrative description. It formats numeric indicators with appropriate
    precision and handles missing values with domain-specific neutral phrases. The output
    text is optimized for sentence transformer embedding.

    Args:
        row (pd.Series): A pandas Series containing aggregated school metrics, typically
            produced by a `compute_school_metrics()` function. Expected columns include:
            `uf` (state), `municipio` (municipality), `nivel_saude` (health program level),
            `score_saude` (health score), `taxa_ausencia_pct` (attendance rate percentage),
            `media_nota_escola` (mean school grade), `pct_bolsa_familia` (percentage
            receiving social assistance), `pct_pcd` (percentage with disabilities),
            `muni_freq_liq_fund` (IBGE liquid enrollment), `est_ideb_af` (state IDEB index),
            `est_taxa_abandono` (state dropout rate), and `data_quality` (data completeness flag).

    Returns:
        str: A narrative description of the school profile (approximately 80-120 words)
            including geographic location, health program status, academic metrics,
            enrollment composition, and institutional context indicators.
    """
    ausencia = row.get("taxa_ausencia_pct", None)
    ausencia_str = f"{ausencia:.1f}%" if ausencia is not None else "sem diário"
    nota = row.get("media_nota_escola", None)
    nota_str = f"{nota:.1f}" if nota is not None else "sem notas"
    bf_pct = row.get("pct_bolsa_familia", None)
    bf_str = f"{bf_pct:.0f}%" if bf_pct is not None else "não informado"
    pcd_pct = row.get("pct_pcd", None)
    pcd_str = f"{pcd_pct:.1f}%" if pcd_pct is not None else "não informado"

    flags = row.get("data_quality", "completo")

    return (
        f"Escola: UF {row.get('uf', '?')}, município {row.get('municipio', '?')}, "
        f"saúde {row.get('nivel_saude', '?')} (score {row.get('score_saude', '?')}), "
        f"ausência {ausencia_str}, nota média {nota_str}, "
        f"Bolsa Família {bf_str}, PCD {pcd_str}, "
        f"IBGE freq_liq {row.get('muni_freq_liq_fund', '?')}, "
        f"IDEB EF-AF {row.get('est_ideb_af', '?')}, "
        f"abandono estadual {row.get('est_taxa_abandono', '?')}, "
        f"qualidade dos dados: {flags}."
    )


def embed_schools(df: pd.DataFrame, batch_size: int = 64) -> np.ndarray:
    """
    Generate normalized embeddings for all schools in a DataFrame.

    This function orchestrates the embedding generation pipeline for a batch of schools.
    It converts each school record to narrative text using `school_to_text()`, loads the
    shared model via `get_model()`, and invokes the sentence transformer encoder with
    batch processing to control memory consumption. All embeddings are L2-normalized for
    use in vector similarity search and institutional clustering.

    Args:
        df (pd.DataFrame): A DataFrame containing aggregated school metrics compatible
            with `school_to_text()`. Typically the output of a `compute_school_metrics()`
            aggregation function.
        batch_size (int, optional): Number of sentences to encode in each model batch.
            Defaults to 64. Smaller batch size reduces memory peak but increases encoding time.

    Returns:
        np.ndarray: A 2D array of shape (N, 384) containing L2-normalized embeddings
            for each school, where N is the number of rows in the input DataFrame.
    """
    model = get_model()
    texts = [school_to_text(row) for _, row in df.iterrows()]
    logger.info("Gerando embeddings para %d escolas", len(texts))
    return model.encode(
        texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True
    )

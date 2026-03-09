import logging
import numpy as np
import pandas as pd
from .student_embedder import get_model

logger = logging.getLogger(__name__)


def school_to_text(row: pd.Series) -> str:
    """
    Serializa métricas de escola em texto descritivo para embedding.

    Args:
        row: Series com saída de compute_school_metrics() — inclui score_saude,
             taxa_ausencia_pct, media_nota_escola, pct_bolsa_familia, etc.

    Returns:
        String descrevendo perfil da escola (~80–120 palavras).
    """
    ausencia = row.get("taxa_ausencia_pct", None)
    ausencia_str = f"{ausencia:.1f}%" if ausencia is not None else "sem diário"
    nota     = row.get("media_nota_escola", None)
    nota_str = f"{nota:.1f}" if nota is not None else "sem notas"
    bf_pct   = row.get("pct_bolsa_familia", None)
    bf_str   = f"{bf_pct:.0f}%" if bf_pct is not None else "não informado"
    pcd_pct  = row.get("pct_pcd", None)
    pcd_str  = f"{pcd_pct:.1f}%" if pcd_pct is not None else "não informado"

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
    Gera embeddings para todas as escolas no DataFrame.

    Args:
        df: DataFrame com saída de compute_school_metrics().
        batch_size: Tamanho do batch.

    Returns:
        ndarray shape (N, 384).
    """
    model = get_model()
    texts = [school_to_text(row) for _, row in df.iterrows()]
    logger.info("Gerando embeddings para %d escolas", len(texts))
    return model.encode(texts, batch_size=batch_size, show_progress_bar=False, normalize_embeddings=True)

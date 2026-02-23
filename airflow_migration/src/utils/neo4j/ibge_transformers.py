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
    "branco":   "branco_",
    "negro":    "negro_",
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

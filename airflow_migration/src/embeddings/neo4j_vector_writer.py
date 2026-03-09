import logging
import numpy as np
from neo4j import Driver

logger = logging.getLogger(__name__)

_WRITE_STUDENT = """
UNWIND $rows AS row
MATCH (stu:Student {id: row.student_id})
SET stu.embedding = row.embedding
"""

_WRITE_SCHOOL = """
UNWIND $rows AS row
MATCH (sch:School {id: row.school_id})
SET sch.embedding = row.embedding
"""


def write_embeddings(
    driver: Driver,
    ids: list[str],
    embeddings: np.ndarray,
    entity: str = "student",
    batch_size: int = 500,
) -> None:
    """
    Escreve embeddings em lote no Neo4j.

    Args:
        driver: Neo4j driver (de Neo4jExtractor.from_env() ou dep injection).
        ids: Lista de student_id ou school_id correspondendo às linhas de embeddings.
        embeddings: ndarray shape (N, 384).
        entity: 'student' ou 'school'.
        batch_size: Tamanho do batch — 500 é o limite seguro para evitar OOM no Neo4j.

    Raises:
        ValueError: se entity não for 'student' nem 'school'.
    """
    if entity not in ("student", "school"):
        raise ValueError(f"entity deve ser 'student' ou 'school', recebido '{entity}'")

    query  = _WRITE_STUDENT if entity == "student" else _WRITE_SCHOOL
    id_key = "student_id" if entity == "student" else "school_id"
    total  = len(ids)

    with driver.session() as session:
        for start in range(0, total, batch_size):
            end  = min(start + batch_size, total)
            rows = [
                {id_key: ids[i], "embedding": embeddings[i].tolist()}
                for i in range(start, end)
            ]
            session.run(query, rows=rows)
            logger.info("Embeddings escritos: %d/%d (%s)", end, total, entity)

    logger.info("Writeback completo: %d embeddings de %s", total, entity)

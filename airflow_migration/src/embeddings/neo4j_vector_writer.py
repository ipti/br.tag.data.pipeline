"""
Neo4j vector embedding writeback module.

This module provides batch write operations to persist vector embeddings and their
cryptographic hashes into Neo4j graph database nodes. It supports writing embeddings
for both student and school entities, with configurable batch sizes and optional
incremental update tracking via embedding hashes. The module handles Neo4j session
lifecycle management and logs writeback progress for operational monitoring.
"""

import logging
import numpy as np
from neo4j import Driver

logger = logging.getLogger(__name__)

_WRITE_STUDENT = """
UNWIND $rows AS row
MATCH (stu:Student {id: row.student_id})
SET stu.embedding = row.embedding,
    stu.embedding_hash = row.embedding_hash
"""

_WRITE_SCHOOL = """
UNWIND $rows AS row
MATCH (sch:School {id: row.school_id})
SET sch.embedding = row.embedding,
    sch.embedding_hash = row.embedding_hash
"""


def write_embeddings(
    driver: Driver,
    ids: list[str],
    embeddings: np.ndarray,
    entity: str = "student",
    batch_size: int = 500,
    hashes: list[str] | None = None,
) -> None:
    """
    Write vector embeddings and optional hashes to Neo4j nodes in batches.

    This function performs batch write operations to persist embeddings into the Neo4j
    graph database. It matches nodes by entity ID (student or school), sets the embedding
    vector and hash properties, and commits changes in configurable batches to prevent
    out-of-memory errors on the Neo4j server. Progress is logged after each batch completion.
    The batch size of 500 is optimized to avoid OOM conditions while maintaining throughput.

    Args:
        driver (neo4j.Driver): An active Neo4j driver instance for session management,
            typically obtained from `Neo4jExtractor.from_env()` or dependency injection.
        ids (list[str]): A list of entity identifiers (student_id or school_id) corresponding
            to rows in the embeddings array. Must have the same length as embeddings.
        embeddings (np.ndarray): A 2D numpy array of shape (N, 384) containing vector
            embeddings to be written to Neo4j. Typically produced by sentence transformer
            encoding via `embed_students()` or `embed_schools()`.
        entity (str, optional): Entity type to write embeddings for. Accepted values are
            `"student"` or `"school"`. Determines the Cypher query and property key mapping.
            Defaults to `"student"`.
        batch_size (int, optional): Maximum number of nodes to update in a single Cypher
            query invocation. Defaults to 500. Higher values increase throughput but risk
            Neo4j OOM; lower values are safer but slower. Recommended range: 250-1000.
        hashes (list[str] | None, optional): Optional list of text hashes (e.g., MD5 digests)
            for incremental update tracking. If provided, must match the length of ids and
            embeddings. Used to detect data changes and skip redundant writes. Defaults to None
            (no hashes written).

    Raises:
        ValueError: If `entity` is not one of the accepted values (`"student"` or `"school"`).
            This validation prevents silent node matching failures.
    """
    if entity not in ("student", "school"):
        raise ValueError(f"entity deve ser 'student' ou 'school', recebido '{entity}'")

    query = _WRITE_STUDENT if entity == "student" else _WRITE_SCHOOL
    id_key = "student_id" if entity == "student" else "school_id"
    total = len(ids)

    with driver.session() as session:
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            rows = []
            for i in range(start, end):
                row_dict = {id_key: ids[i], "embedding": embeddings[i].tolist()}
                if hashes:
                    row_dict["embedding_hash"] = hashes[i]
                else:
                    row_dict["embedding_hash"] = None
                rows.append(row_dict)

            session.run(query, rows=rows)
            logger.info("Embeddings escritos: %d/%d (%s)", end, total, entity)

    logger.info("Writeback completo: %d embeddings de %s", total, entity)

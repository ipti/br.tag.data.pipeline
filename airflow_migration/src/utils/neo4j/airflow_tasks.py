import logging
from sqlalchemy import text
from src.utils.connections.connection_manager import DatabaseConnectionManager
from src.utils.neo4j.ingestor import Neo4jIngestor
import src.utils.neo4j.queries as q


def create_indexes(**kwargs):
    """Create all Neo4j indexes before data loading."""
    logger = logging.getLogger(__name__)
    ingestor = Neo4jIngestor()
    try:
        for idx_query in q.ALL_INDEXES:
            logger.info(f"Creating index: {idx_query}")
            ingestor.run_query(idx_query)
        logger.info("All indexes created successfully.")
    finally:
        ingestor.close()


def stream_to_neo4j(
    sql_query: str,
    cypher_query: str,
    batch_size: int = 5000,
    transformer: callable = None,
    **kwargs,
):
    """
    Generic function to stream from SQL Server Warehouse (dbo_tia) and load to Neo4j.

    Args:
        sql_query: SQL query to execute on the source database.
        cypher_query: Cypher query for ingestion into Neo4j.
        batch_size: Number of records per batch.
        transformer: Optional function to transform each row (dict) before ingestion.
    """
    logger = logging.getLogger(__name__)

    env = kwargs.get("environment", "prod")
    logger.info(f"Connecting to SQL Server using environment: {env}")
    db_manager = DatabaseConnectionManager(environment=env)
    ingestor = Neo4jIngestor(batch_size=batch_size)

    logger.info(f"Executing SQL on Warehouse:\n{sql_query}")

    try:
        with db_manager.sqlserver_connection() as conn:
            result = conn.execute(text(sql_query))
            columns = list(result.keys())

            while True:
                rows = result.fetchmany(batch_size)
                if not rows:
                    break

                data = [dict(zip(columns, row)) for row in rows]

                if transformer:
                    data = [transformer(row) for row in data]

                ingestor.ingest_data(cypher_query, data)

    except Exception as e:
        logger.error(f"Error during streaming: {e}")
        raise e
    finally:
        ingestor.close()

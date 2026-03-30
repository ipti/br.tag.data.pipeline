"""
Neo4j Ingestion Module.

This module handles efficient batch loading of data from Python lists (e.g., from SQL cursors) to Neo4j.
It implements batching logic to ensure memory stability during large transfers.
"""

import logging
from typing import List, Dict, Any
from neo4j.exceptions import Neo4jError
from src.utils.neo4j.connector import Neo4jConnector

logger = logging.getLogger(__name__)


class Neo4jIngestor:
    """
    Handles data ingestion into Neo4j.
    """

    def __init__(self, batch_size: int = 2000):
        """
        Initialize the ingestor.

        Args:
            batch_size (int): Number of records to commit per transaction. Defaults to 2000.
        """
        self.batch_size = batch_size
        self.connector = Neo4jConnector()

    def ingest_data(
        self, cypher_query: str, data: List[Dict[str, Any]], max_retries: int = 5
    ) -> int:
        """
        Push data to Neo4j in batches using the UNWIND pattern.

        Includes retry with exponential backoff for transient errors (e.g., deadlocks)
        which occur when parallel tasks write to the same nodes simultaneously.

        Args:
            cypher_query (str): The parameterized Cypher query.
            data (list): List of dictionaries containing the data to load.
            max_retries (int): Maximum retry attempts per batch on transient errors.

        Returns:
            int: Total number of records processed.

        Raises:
            Neo4jError: If a batch fails after all retries.
        """
        import time
        import random

        driver = self.connector.get_driver()
        total_processed = 0

        if not data:
            logger.warning("No data provided to ingest.")
            return 0

        logger.info(
            f"Starting ingestion of {len(data)} records with batch size {self.batch_size}..."
        )

        for i in range(0, len(data), self.batch_size):
            batch = data[i : i + self.batch_size]
            batch_idx = i // self.batch_size + 1

            for attempt in range(1, max_retries + 1):
                try:
                    with driver.session() as session:
                        session.run(cypher_query, rows=batch)
                    total_processed += len(batch)
                    logger.debug(f"Batch {batch_idx}: Processed {len(batch)} records.")
                    break  # Success, move to next batch
                except Neo4jError as e:
                    is_transient = "TransientError" in str(
                        type(e).__name__
                    ) or "Deadlock" in str(e)
                    if is_transient and attempt < max_retries:
                        wait_time = (2**attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"Batch {batch_idx}: Transient error (attempt {attempt}/{max_retries}). "
                            f"Retrying in {wait_time:.1f}s... Error: {e}"
                        )
                        time.sleep(wait_time)
                    else:
                        logger.error(
                            f"Batch {batch_idx} failed after {attempt} attempts: {e}"
                        )
                        raise e

        logger.info(f"Ingestion complete. Total processed: {total_processed}")
        return total_processed

    def run_query(self, cypher_query: str, **params):
        """
        Execute a standalone Cypher query (e.g., index creation).

        Args:
            cypher_query: The Cypher query to execute.
            **params: Optional parameters for the query.
        """
        driver = self.connector.get_driver()
        try:
            with driver.session() as session:
                session.run(cypher_query, **params)
                logger.info(f"Query executed: {cypher_query[:80]}...")
        except Neo4jError as e:
            logger.error(f"Error executing query: {e}")
            raise e

    def close(self):
        """Closes the underlying connector."""
        self.connector.close()

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

    def ingest_data(self, cypher_query: str, data: List[Dict[str, Any]]) -> int:
        """
        Push data to Neo4j in batches using the UNWIND pattern.
        
        The Cypher query must expect a parameter named $rows which is a list of maps.
        Example Query:
            UNWIND $rows AS row
            MERGE (n:Node {id: row.id})
            SET n += row
        
        Args:
            cypher_query (str): The parameterized Cypher query.
            data (list): List of dictionaries containing the data to load.
            
        Returns:
            int: Total number of records processed.
            
        Raises:
            Neo4jError: If a batch fails to commit.
        """
        driver = self.connector.get_driver()
        total_processed = 0
        
        if not data:
            logger.warning("No data provided to ingest.")
            return 0
        
        logger.info(f"Starting ingestion of {len(data)} records with batch size {self.batch_size}...")
        
        try:
            with driver.session() as session:
                for i in range(0, len(data), self.batch_size):
                    batch = data[i : i + self.batch_size]
                    batch_idx = i // self.batch_size + 1
                    
                    try:
                        # Execute the query with the current batch
                        session.run(cypher_query, rows=batch)
                        total_processed += len(batch)
                        logger.debug(f"Batch {batch_idx}: Processed {len(batch)} records.")
                    except Neo4jError as e:
                        logger.error(f"Error committing batch {batch_idx} (records {i} to {i+len(batch)}): {e}")
                        raise e
                        
        except Exception as e:
            logger.error(f"Critical error during ingestion: {e}")
            raise e
            
        logger.info(f"Ingestion complete. Total processed: {total_processed}")
        return total_processed

    def close(self):
        """Closes the underlying connector."""
        self.connector.close()

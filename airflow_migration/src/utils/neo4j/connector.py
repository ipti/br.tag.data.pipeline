"""
Neo4j Connector Module.

This module is responsible for managing the connection lifecycle to the Neo4j database.
It implements a Singleton-like pattern to ensure efficient driver usage.
"""
import logging
import os
from threading import Lock
from typing import Optional

from neo4j import GraphDatabase, Driver

class Neo4jConnector:
    """
    Manages the Neo4j driver connection.
    
    This class is designed to be used within Airflow tasks to obtain a valid
    Neo4j driver instance. It handles connection initialization and verification.
    
    Usage:
        connector = Neo4jConnector()
        driver = connector.get_driver()
        with driver.session() as session:
            ...
        connector.close()
    """
    _instance: Optional['Neo4jConnector'] = None
    _lock: Lock = Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(Neo4jConnector, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
            
        self.uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        self.user = os.getenv("NEO4J_USER", "neo4j")
        self.password = os.getenv("NEO4J_PASSWORD", "password")
        self._driver: Optional[Driver] = None
        self.logger = logging.getLogger(__name__)
        self._initialized = True

    def get_driver(self) -> Driver:
        """
        Creates or returns an existing driver instance.
        
        Returns:
            neo4j.Driver: The active driver instance.
            
        Raises:
            Exception: If connection to Neo4j fails.
        """
        if not self._driver:
            try:
                self.logger.info(f"Connecting to Neo4j at {self.uri}")
                self._driver = GraphDatabase.driver(
                    self.uri, 
                    auth=(self.user, self.password)
                )
                # Verify connectivity
                self._driver.verify_connectivity()
                self.logger.info("Successfully connected to Neo4j.")
            except Exception as e:
                self.logger.error(f"Failed to connect to Neo4j: {e}")
                raise e
        return self._driver

    def close(self):
        """Closes the driver connection if it exists."""
        if self._driver:
            self._driver.close()
            self._driver = None
            self.logger.info("Neo4j driver connection closed.")

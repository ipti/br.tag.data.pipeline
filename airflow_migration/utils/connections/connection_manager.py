import os
import subprocess
import pymysql
import pyodbc
import sqlalchemy
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from typing import Optional, Dict, Any, Union, Generator
import time
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

# Import the logger we created
from airflow_logger import get_logger


@dataclass
class DatabaseConfig:
    """Database configuration dataclass."""
    host: str
    port: int
    database: str
    username: str
    password: str
    driver: Optional[str] = None
    schema: Optional[str] = None


class DatabaseConnectionManager:
    """
    Manages database connections for MySQL sources and SQL Server warehouse.
    Automatically switches between prod/dev based on git branch.
    """
    
    def __init__(self, hotfix_mode: bool = False, connection_timeout: int = 720):
        """
        Initialize the connection manager.
        
        Args:
            hotfix_mode: If True, always use production warehouse even in dev branches
            connection_timeout: Connection timeout in seconds (default 12 minutes)
        """
        self.logger = get_logger("db_connections")
        self.hotfix_mode = hotfix_mode
        self.connection_timeout = connection_timeout
        
        # Load environment variables
        self._load_environment()
        
        # Detect current branch
        self.current_branch = self._get_current_branch()
        self.is_production = self._is_production_branch()
        
        # Log environment detection
        self.logger.info(
            f"Environment detected",
            {
                "branch": self.current_branch,
                "is_production": self.is_production,
                "hotfix_mode": self.hotfix_mode
            }
        )
        
        # Initialize connection pools
        self._mysql_engines: Dict[str, sqlalchemy.Engine] = {}
        self._sqlserver_engine: Optional[sqlalchemy.Engine] = None
        
        # Setup configurations
        self._setup_database_configs()
    
    def _load_environment(self):
        """Load environment variables from .env file."""
        env_path = Path(__file__).parent / '.env'
        if env_path.exists():
            load_dotenv(env_path)
            self.logger.info("Environment variables loaded from .env file")
        else:
            # Try loading from root directory
            root_env = Path.cwd() / '.env'
            if root_env.exists():
                load_dotenv(root_env)
                self.logger.info("Environment variables loaded from root .env file")
            else:
                self.logger.warning("No .env file found, using system environment variables")
    
    def _get_current_branch(self) -> str:
        """
        Get the current git branch.
        
        Returns:
            Current branch name or 'unknown' if not in a git repository
        """
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                branch = result.stdout.strip()
                self.logger.debug(f"Current git branch detected: {branch}")
                return branch
            else:
                self.logger.warning("Failed to get git branch, assuming production")
                return "main"
                
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            self.logger.warning(f"Error detecting git branch", exception=e)
            return "unknown"
    
    def _is_production_branch(self) -> bool:
        """
        Check if current branch is production.
        
        Returns:
            True if current branch is main/master
        """
        return self.current_branch.lower() in ['main', 'master']
    
    def _setup_database_configs(self):
        """Setup database configurations based on environment."""
        try:
            # MySQL configurations - supports multiple sources including local Docker
            self.mysql_configs = {}
            
            # Airflow MySQL (for metadata or other operations)
            if all([os.getenv('MYSQL_HOST'), os.getenv('MYSQL_USER'), os.getenv('MYSQL_PASSWORD')]):
                self.mysql_configs['airflow_mysql'] = DatabaseConfig(
                    host=os.getenv('MYSQL_HOST'),
                    port=int(os.getenv('MYSQL_PORT', 3306)),
                    database=os.getenv('MYSQL_DATABASE'),
                    username=os.getenv('MYSQL_USER'),
                    password=os.getenv('MYSQL_PASSWORD')
                )
            
            # Additional MySQL sources - dynamically discover from environment
            source_counter = 1
            while True:
                host_key = f'MYSQL_SOURCE{source_counter}_HOST'
                if not os.getenv(host_key):
                    break
                
                self.mysql_configs[f'mysql_source_{source_counter}'] = DatabaseConfig(
                    host=os.getenv(host_key),
                    port=int(os.getenv(f'MYSQL_SOURCE{source_counter}_PORT', 3306)),
                    database=os.getenv(f'MYSQL_SOURCE{source_counter}_DATABASE'),
                    username=os.getenv(f'MYSQL_SOURCE{source_counter}_USER'),
                    password=os.getenv(f'MYSQL_SOURCE{source_counter}_PASSWORD')
                )
                source_counter += 1
            
            # SQL Server warehouse configuration - flexible schema handling
            self._setup_sqlserver_config()
            
        except (ValueError, TypeError) as e:
            self.logger.error("Error setting up database configurations", exception=e)
            raise
    
    def _setup_sqlserver_config(self):
        """Setup SQL Server configuration with intelligent schema selection."""
        # Base SQL Server connection (same for prod and dev)
        base_config = {
            'host': os.getenv('SQLSERVER_HOST'),
            'port': int(os.getenv('SQLSERVER_PORT', 1433)),
            'database': os.getenv('SQLSERVER_DATABASE'),
            'username': os.getenv('SQLSERVER_USER'),
            'password': os.getenv('SQLSERVER_PASSWORD'),
            'driver': os.getenv('SQLSERVER_DRIVER', 'ODBC Driver 18 for SQL Server')
        }
        
        # Determine schema based on environment and hotfix mode
        if self.is_production or self.hotfix_mode:
            # Production: use production schema or fallback to main schema
            schema = os.getenv('SQLSERVER_PROD_SCHEMA') or os.getenv('AIRFLOW_SCHEMA', 'dbo')
            env_type = "PRODUCTION"
        else:
            # Development: prioritize dev schema, fallback to airflow schema, then dbo
            dev_schema = os.getenv('SQLSERVER_DEV_SCHEMA')
            airflow_schema = os.getenv('AIRFLOW_SCHEMA')
            
            if dev_schema:
                schema = dev_schema
            elif airflow_schema and airflow_schema != 'dbo':
                # Use airflow schema if it's not the default dbo
                schema = airflow_schema
            else:
                # Fallback to a dev-specific schema or dbo
                schema = 'dev_schema'
            
            env_type = "DEVELOPMENT"
        
        self.sqlserver_config = DatabaseConfig(
            schema=schema,
            **base_config
        )
        
        self.logger.info(
            f"Using {env_type} SQL Server warehouse",
            {
                "host": base_config['host'],
                "database": base_config['database'],
                "schema": schema,
                "hotfix_mode": self.hotfix_mode
            }
        )
    
    def _create_mysql_engine(self, source_name: str) -> sqlalchemy.Engine:
        """
        Create MySQL engine with connection pooling.
        
        Args:
            source_name: Name of the MySQL source
        
        Returns:
            SQLAlchemy engine
        """
        config = self.mysql_configs.get(source_name)
        if not config:
            raise ValueError(f"MySQL source '{source_name}' not configured")
        
        connection_string = (
            f"mysql+pymysql://{config.username}:{config.password}@"
            f"{config.host}:{config.port}/{config.database}"
        )
        
        engine = create_engine(
            connection_string,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,  # Recycle connections every hour
            connect_args={
                'connect_timeout': 30,
                'read_timeout': self.connection_timeout,
                'write_timeout': self.connection_timeout
            }
        )
        
        self.logger.info(
            f"MySQL engine created for source: {source_name}",
            {"host": config.host, "database": config.database}
        )
        
        return engine
    
    def _create_sqlserver_engine(self) -> sqlalchemy.Engine:
        """
        Create SQL Server engine with connection pooling.
        
        Returns:
            SQLAlchemy engine
        """
        config = self.sqlserver_config
        
        connection_string = (
            f"mssql+pyodbc://{config.username}:{config.password}@"
            f"{config.host}:{config.port}/{config.database}?"
            f"driver={config.driver}&timeout={self.connection_timeout}"
        )
        
        engine = create_engine(
            connection_string,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={
                'timeout': self.connection_timeout
            }
        )
        
        self.logger.info(
            f"SQL Server engine created",
            {
                "host": config.host,
                "database": config.database,
                "schema": config.schema,
                "environment": "PROD" if (self.is_production or self.hotfix_mode) else "DEV"
            }
        )
        
        return engine
    
    def get_mysql_engine(self, source_name: str) -> sqlalchemy.Engine:
        """
        Get MySQL engine for specified source.
        
        Args:
            source_name: Name of the MySQL source
        
        Returns:
            SQLAlchemy engine
        """
        if source_name not in self._mysql_engines:
            self._mysql_engines[source_name] = self._create_mysql_engine(source_name)
        
        return self._mysql_engines[source_name]
    
    def get_sqlserver_engine(self) -> sqlalchemy.Engine:
        """
        Get SQL Server engine.
        
        Returns:
            SQLAlchemy engine
        """
        if self._sqlserver_engine is None:
            self._sqlserver_engine = self._create_sqlserver_engine()
        
        return self._sqlserver_engine
    
    @contextmanager
    def mysql_connection(self, source_name: str) -> Generator[sqlalchemy.Connection, None, None]:
        """
        Context manager for MySQL connections.
        
        Args:
            source_name: Name of the MySQL source
        
        Yields:
            SQLAlchemy connection
        """
        engine = self.get_mysql_engine(source_name)
        connection = None
        
        try:
            start_time = time.time()
            connection = engine.connect()
            
            self.logger.debug(f"MySQL connection established for source: {source_name}")
            
            yield connection
            
            execution_time = time.time() - start_time
            self.logger.debug(
                f"MySQL connection closed for source: {source_name}",
                {"execution_time_seconds": round(execution_time, 2)}
            )
            
        except Exception as e:
            self.logger.error(
                f"MySQL connection error for source: {source_name}",
                exception=e
            )
            raise
        finally:
            if connection:
                connection.close()
    
    @contextmanager
    def sqlserver_connection(self) -> Generator[sqlalchemy.Connection, None, None]:
        """
        Context manager for SQL Server connections.
        
        Yields:
            SQLAlchemy connection
        """
        engine = self.get_sqlserver_engine()
        connection = None
        
        try:
            start_time = time.time()
            connection = engine.connect()
            
            self.logger.debug("SQL Server connection established")
            
            yield connection
            
            execution_time = time.time() - start_time
            self.logger.debug(
                "SQL Server connection closed",
                {"execution_time_seconds": round(execution_time, 2)}
            )
            
        except Exception as e:
            self.logger.error("SQL Server connection error", exception=e)
            raise
        finally:
            if connection:
                connection.close()
    
    def test_mysql_connection(self, source_name: str) -> bool:
        """
        Test MySQL connection health.
        
        Args:
            source_name: Name of the MySQL source
        
        Returns:
            True if connection is healthy
        """
        try:
            with self.mysql_connection(source_name) as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
                
            self.logger.info(f"MySQL connection test successful for source: {source_name}")
            return True
            
        except Exception as e:
            self.logger.error(
                f"MySQL connection test failed for source: {source_name}",
                exception=e
            )
            return False
    
    def test_sqlserver_connection(self) -> bool:
        """
        Test SQL Server connection health.
        
        Returns:
            True if connection is healthy
        """
        try:
            with self.sqlserver_connection() as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
                
            self.logger.info("SQL Server connection test successful")
            return True
            
        except Exception as e:
            self.logger.error("SQL Server connection test failed", exception=e)
            return False
    
    def execute_mysql_query(
        self,
        source_name: str,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Execute query on MySQL source.
        
        Args:
            source_name: Name of the MySQL source
            query: SQL query to execute
            params: Query parameters
        
        Returns:
            Query result
        """
        start_time = time.time()
        
        try:
            with self.mysql_connection(source_name) as conn:
                if params:
                    result = conn.execute(text(query), params)
                else:
                    result = conn.execute(text(query))
                
                # Fetch results if it's a SELECT query
                if query.strip().upper().startswith('SELECT'):
                    rows = result.fetchall()
                    execution_time = time.time() - start_time
                    
                    self.logger.info(
                        f"MySQL query executed successfully",
                        {
                            "source": source_name,
                            "rows_returned": len(rows),
                            "execution_time_seconds": round(execution_time, 2)
                        }
                    )
                    return rows
                else:
                    # For INSERT, UPDATE, DELETE queries
                    affected_rows = result.rowcount
                    execution_time = time.time() - start_time
                    
                    self.logger.info(
                        f"MySQL query executed successfully",
                        {
                            "source": source_name,
                            "affected_rows": affected_rows,
                            "execution_time_seconds": round(execution_time, 2)
                        }
                    )
                    return affected_rows
                    
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(
                f"MySQL query execution failed",
                exception=e,
                extra_data={
                    "source": source_name,
                    "execution_time_seconds": round(execution_time, 2)
                }
            )
            raise
    
    def execute_sqlserver_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Execute query on SQL Server warehouse.
        
        Args:
            query: SQL query to execute
            params: Query parameters
        
        Returns:
            Query result
        """
        start_time = time.time()
        
        try:
            with self.sqlserver_connection() as conn:
                if params:
                    result = conn.execute(text(query), params)
                else:
                    result = conn.execute(text(query))
                
                # Fetch results if it's a SELECT query
                if query.strip().upper().startswith('SELECT'):
                    rows = result.fetchall()
                    execution_time = time.time() - start_time
                    
                    self.logger.info(
                        f"SQL Server query executed successfully",
                        {
                            "rows_returned": len(rows),
                            "execution_time_seconds": round(execution_time, 2),
                            "schema": self.sqlserver_config.schema
                        }
                    )
                    return rows
                else:
                    # For INSERT, UPDATE, DELETE queries
                    affected_rows = result.rowcount
                    execution_time = time.time() - start_time
                    
                    self.logger.info(
                        f"SQL Server query executed successfully",
                        {
                            "affected_rows": affected_rows,
                            "execution_time_seconds": round(execution_time, 2),
                            "schema": self.sqlserver_config.schema
                        }
                    )
                    return affected_rows
                    
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(
                f"SQL Server query execution failed",
                exception=e,
                extra_data={
                    "execution_time_seconds": round(execution_time, 2),
                    "schema": self.sqlserver_config.schema
                }
            )
            raise
    
    def copy_data(
        self,
        source_name: str,
        source_query: str,
        target_table: str,
        batch_size: int = 10000,
        truncate_target: bool = False
    ):
        """
        Copy data from MySQL source to SQL Server warehouse.
        
        Args:
            source_name: Name of the MySQL source
            source_query: SQL query to extract data from source
            target_table: Target table name in SQL Server
            batch_size: Number of rows to process in each batch
            truncate_target: Whether to truncate target table before insert
        """
        start_time = time.time()
        total_rows_copied = 0
        
        try:
            self.logger.info(
                f"Starting data copy operation",
                {
                    "source": source_name,
                    "target_table": target_table,
                    "batch_size": batch_size,
                    "truncate_target": truncate_target
                }
            )
            
            # Truncate target table if requested
            if truncate_target:
                truncate_query = f"TRUNCATE TABLE {self.sqlserver_config.schema}.{target_table}"
                self.execute_sqlserver_query(truncate_query)
                self.logger.info(f"Target table truncated: {target_table}")
            
            # Get source data
            source_rows = self.execute_mysql_query(source_name, source_query)
            
            if not source_rows:
                self.logger.info("No data found in source query")
                return
            
            # Get column names from first row
            columns = list(source_rows[0].keys())
            
            # Process data in batches
            for i in range(0, len(source_rows), batch_size):
                batch = source_rows[i:i + batch_size]
                
                # Prepare insert query
                placeholders = ', '.join([f':{col}' for col in columns])
                insert_query = (
                    f"INSERT INTO {self.sqlserver_config.schema}.{target_table} "
                    f"({', '.join(columns)}) VALUES ({placeholders})"
                )
                
                # Execute batch insert
                with self.sqlserver_connection() as conn:
                    conn.execute(text(insert_query), [dict(row) for row in batch])
                    conn.commit()
                
                total_rows_copied += len(batch)
                
                self.logger.debug(
                    f"Batch processed",
                    {
                        "batch_number": (i // batch_size) + 1,
                        "rows_in_batch": len(batch),
                        "total_copied": total_rows_copied
                    }
                )
            
            execution_time = time.time() - start_time
            
            self.logger.info(
                f"Data copy completed successfully",
                {
                    "source": source_name,
                    "target_table": target_table,
                    "total_rows_copied": total_rows_copied,
                    "execution_time_seconds": round(execution_time, 2)
                }
            )
            
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(
                f"Data copy failed",
                exception=e,
                extra_data={
                    "source": source_name,
                    "target_table": target_table,
                    "rows_copied": total_rows_copied,
                    "execution_time_seconds": round(execution_time, 2)
                }
            )
            raise
    
    def close_all_connections(self):
        """Close all database connections and dispose engines."""
        try:
            # Close MySQL engines
            for source_name, engine in self._mysql_engines.items():
                engine.dispose()
                self.logger.info(f"MySQL engine disposed for source: {source_name}")
            
            # Close SQL Server engine
            if self._sqlserver_engine:
                self._sqlserver_engine.dispose()
                self.logger.info("SQL Server engine disposed")
            
            # Clear engine references
            self._mysql_engines.clear()
            self._sqlserver_engine = None
            
            self.logger.info("All database connections closed")
            
        except Exception as e:
            self.logger.error("Error closing database connections", exception=e)
    
    def get_available_mysql_sources(self) -> list:
        """
        Get list of available MySQL sources.
        
        Returns:
            List of available MySQL source names
        """
        return list(self.mysql_configs.keys())
    
    def mysql_connection_exists(self, source_name: str) -> bool:
        """
        Check if MySQL source exists.
        
        Args:
            source_name: Name of the MySQL source
        
        Returns:
            True if source exists
        """
        return source_name in self.mysql_configs
        """
        Get current connection configuration info.
        
        Returns:
            Dictionary with connection information
        """
        return {
            "current_branch": self.current_branch,
            "is_production": self.is_production,
            "hotfix_mode": self.hotfix_mode,
            "connection_timeout": self.connection_timeout,
            "sqlserver_environment": "PROD" if (self.is_production or self.hotfix_mode) else "DEV",
            "sqlserver_schema": self.sqlserver_config.schema,
            "mysql_sources": list(self.mysql_configs.keys())
        }


# Utility function to create database manager instance
def get_db_manager(hotfix_mode: bool = False, connection_timeout: int = 720) -> DatabaseConnectionManager:
    """
    Create and return a DatabaseConnectionManager instance.
    
    Args:
        hotfix_mode: If True, use production warehouse even in dev branches
        connection_timeout: Connection timeout in seconds
    
    Returns:
        DatabaseConnectionManager instance
    """
    return DatabaseConnectionManager(
        hotfix_mode=hotfix_mode,
        connection_timeout=connection_timeout
    )
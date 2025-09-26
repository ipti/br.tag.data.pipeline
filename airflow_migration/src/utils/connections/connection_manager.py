import os
import subprocess
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.engine import Engine, Connection
from contextlib import contextmanager
from typing import Optional, Dict, Any, Generator
import time
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv
from airflow_migration.src.utils.logs.logging_functions import get_logger
import urllib
import socket


@dataclass
class DatabaseConfig:
    """
    Dataclass for storing database configuration parameters.
    """

    host: str
    port: int
    database: str
    username: str
    password: str
    driver: Optional[str] = None
    schema: Optional[str] = None


class DatabaseConnectionManager:
    """
    Handles connections to MySQL sources and SQL Server warehouse.
    Automatically switches between production and development environments based on the current git branch.
    """

    def __init__(self, hotfix_mode: bool = False, connection_timeout: int = 720):
        """
        Initializes the connection manager, loads environment variables, detects the current git branch,
        and sets up database configurations.

        Args:
            hotfix_mode: If True, always use production warehouse even on development branches.
            connection_timeout: Connection timeout in seconds (default is 12 minutes).
        """
        self.logger = get_logger("db_connections")
        self.hotfix_mode = hotfix_mode
        self.connection_timeout = connection_timeout
        self._load_environment()
        self.current_branch = self._get_current_branch()
        self.is_production = self._is_production_branch()
        self.logger.info(
            "Environment detected",
            {
                "branch": self.current_branch,
                "is_production": self.is_production,
                "hotfix_mode": self.hotfix_mode,
            },
        )
        self._mysql_engines: Dict[str, Engine] = {}
        self._sqlserver_engine: Optional[Engine] = None
        self._setup_database_configs()

    def _load_environment(self):
        root_path = Path(__file__).parents[3]
        env_path = root_path / ".env"

        if env_path.exists():
            load_dotenv(env_path)
            self.logger.info(f"Environment variables loaded from {env_path}")
        else:
            self.logger.warning(
                "No .env file found, using system environment variables"
            )

    def _get_current_branch(self) -> str:
        """
        Returns the current git branch name, or 'main' if not in a git repository.
        """
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                branch = result.stdout.strip()
                self.logger.debug(f"Current git branch detected: {branch}")
                return branch
            else:
                self.logger.warning("Failed to get git branch, assuming production")
                return "main"
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            self.logger.warning("Error detecting git branch", exception=e)
            return "unknown"

    def _is_production_branch(self) -> bool:
        """
        Determines if the current branch is a production branch ('main' or 'master').
        """
        return self.current_branch.lower() in ["main", "master"]

    def _is_local_environment(self) -> bool:
        """
        Checks if the code is running outside Docker by attempting to resolve 'host.docker.internal'.
        Returns True if running locally (Mac/Windows), otherwise False.
        """
        try:
            import socket

            socket.gethostbyname("host.docker.internal")
            return True
        except socket.error:
            return False

    def _is_running_in_docker(self) -> bool:
        """
        Determines if the code is running inside a Docker container using several detection methods.
        """
        try:
            if os.path.exists("/.dockerenv"):
                return True
            if os.path.exists("/proc/1/cgroup"):
                with open("/proc/1/cgroup", "r") as f:
                    content = f.read()
                    if "docker" in content or "containerd" in content:
                        return True
            docker_env_vars = [
                "DOCKER_CONTAINER",
                "CONTAINER",
                "KUBERNETES_SERVICE_HOST",
            ]
            if any(os.getenv(var) for var in docker_env_vars):
                return True
            return False
        except Exception as e:
            self.logger.warning(f"Error detecting Docker environment: {e}")
            return False

    def _resolve_mysql_host(self, configured_host: str) -> str:
        """
        Resolves the MySQL host based on the current environment.
        Returns the appropriate host for connection.
        """
        if configured_host not in ["mysql-container", "mysql", "db"]:
            return configured_host
        if self._is_running_in_docker():
            self.logger.info(
                f"Running inside Docker, using container name: {configured_host}"
            )
            return configured_host
        try:
            socket.gethostbyname(configured_host)
            self.logger.info(f"Container name {configured_host} resolved successfully")
            return configured_host
        except socket.gaierror:
            self.logger.info(
                f"Container name {configured_host} not resolvable, using localhost"
            )
            return "localhost"

    def _setup_database_configs(self):
        """
        Sets up database configurations for MySQL sources and SQL Server warehouse
        based on the current environment and available environment variables.
        """
        try:
            self.mysql_configs = {}
            if all(
                [
                    os.getenv("MYSQL_HOST"),
                    os.getenv("MYSQL_USER"),
                    os.getenv("MYSQL_PASSWORD"),
                ]
            ):
                raw_host = os.getenv("MYSQL_HOST")
                mysql_host = self._resolve_mysql_host(raw_host)
                self.mysql_configs["airflow_mysql"] = DatabaseConfig(
                    host=mysql_host,
                    port=int(os.getenv("MYSQL_PORT", 3306)),
                    database=os.getenv("MYSQL_DATABASE"),
                    username=os.getenv("MYSQL_USER"),
                    password=os.getenv("MYSQL_PASSWORD"),
                )
            source_counter = 1
            while True:
                host_key = f"MYSQL_SOURCE{source_counter}_HOST"
                raw_source_host = os.getenv(host_key)
                if not raw_source_host:
                    break
                resolved_source_host = self._resolve_mysql_host(raw_source_host)
                self.mysql_configs[f"mysql_source_{source_counter}"] = DatabaseConfig(
                    host=resolved_source_host,
                    port=int(os.getenv(f"MYSQL_SOURCE{source_counter}_PORT", 3306)),
                    database=os.getenv(f"MYSQL_SOURCE{source_counter}_DATABASE"),
                    username=os.getenv(f"MYSQL_SOURCE{source_counter}_USER"),
                    password=os.getenv(f"MYSQL_SOURCE{source_counter}_PASSWORD"),
                )
                source_counter += 1
            self._setup_sqlserver_config()
        except (ValueError, TypeError) as e:
            self.logger.error("Error setting up database configurations", exception=e)
            raise

    def _setup_sqlserver_config(self):
        """
        Sets up the SQL Server configuration, selecting the appropriate schema
        based on the environment and hotfix mode.
        """
        base_config = {
            "host": os.getenv("SQLSERVER_HOST"),
            "port": int(os.getenv("SQLSERVER_PORT", 1433)),
            "database": os.getenv("SQLSERVER_DATABASE"),
            "driver": os.getenv("SQLSERVER_DRIVER", "ODBC Driver 18 for SQL Server"),
        }

        if self.is_production or self.hotfix_mode:
            base_config["username"] = os.getenv("SQLSERVER_USER_PRD") or os.getenv(
                "SQLSERVER_USER"
            )
            base_config["password"] = os.getenv("SQLSERVER_PASSWORD_PRD") or os.getenv(
                "SQLSERVER_PASSWORD"
            )

            schema = os.getenv("SQLSERVER_PROD_SCHEMA") or os.getenv(
                "AIRFLOW_SCHEMA", "dbo"
            )
            env_type = "PRODUCTION"
        else:
            base_config["username"] = os.getenv("SQLSERVER_USER_DEV") or os.getenv(
                "SQLSERVER_USER"
            )
            base_config["password"] = os.getenv("SQLSERVER_PASSWORD_DEV") or os.getenv(
                "SQLSERVER_PASSWORD"
            )

            dev_schema = os.getenv("SQLSERVER_DEV_SCHEMA")
            airflow_schema = os.getenv("AIRFLOW_SCHEMA")
            if dev_schema:
                schema = dev_schema
            elif airflow_schema and airflow_schema != "dbo":
                schema = airflow_schema
            else:
                schema = "dev_schema"
            env_type = "DEVELOPMENT"

        if not base_config["username"] or not base_config["password"]:
            missing_vars = []
            if not base_config["username"]:
                expected_user_var = (
                    "SQLSERVER_USER_PRD"
                    if (self.is_production or self.hotfix_mode)
                    else "SQLSERVER_USER_DEV"
                )
                missing_vars.append(expected_user_var)
            if not base_config["password"]:
                expected_pass_var = (
                    "SQLSERVER_PASSWORD_PRD"
                    if (self.is_production or self.hotfix_mode)
                    else "SQLSERVER_PASSWORD_DEV"
                )
                missing_vars.append(expected_pass_var)

            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        self.sqlserver_config = DatabaseConfig(schema=schema, **base_config)
        self.logger.info(
            f"Using {env_type} SQL Server warehouse",
            {
                "host": base_config["host"],
                "database": base_config["database"],
                "schema": schema,
                "hotfix_mode": self.hotfix_mode,
            },
        )

    def _create_mysql_engine(
        self, source_name: str, database_override: str = None
    ) -> Engine:
        """
        Creates a SQLAlchemy engine for a MySQL source with connection pooling.

        Args:
            source_name: Name of the MySQL source.

        Returns:
            SQLAlchemy engine instance.
        """
        config = self.mysql_configs.get(source_name)
        if not config:
            raise ValueError(f"MySQL source '{source_name}' not configured")

        database_to_connect = (
            database_override if database_override else config.database
        )

        db_path = f"/{database_to_connect}" if database_to_connect else ""

        connection_string = (
            f"mysql+pymysql://{config.username}:{config.password}@"
            f"{config.host}:{config.port}{db_path}"
        )
        engine = create_engine(
            connection_string,
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            connect_args={
                "connect_timeout": 30,
                "read_timeout": self.connection_timeout,
                "write_timeout": self.connection_timeout,
            },
        )
        self.logger.info(
            f"MySQL engine created for source: {source_name}",
            {"host": config.host, "database": config.database},
        )
        return engine

    def _create_sqlserver_engine(self) -> Engine:
        """
        Creates a SQLAlchemy engine for SQL Server using a reliable ODBC connection string.

        Returns:
            SQLAlchemy engine instance.
        """
        config = self.sqlserver_config
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={config.host},{config.port};"
            f"DATABASE={config.database};"
            f"UID={config.username};"
            f"PWD={config.password};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=yes;"
            f"Connection Timeout={self.connection_timeout};"
        )
        odbc_url = urllib.parse.quote_plus(conn_str)
        engine = create_engine(
            f"mssql+pyodbc:///?odbc_connect={odbc_url}",
            poolclass=QueuePool,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            fast_executemany=True,
        )
        self.logger.info(
            "SQL Server engine created",
            {
                "host": config.host,
                "database": config.database,
                "schema": config.schema,
                "environment": (
                    "PROD" if (self.is_production or self.hotfix_mode) else "DEV"
                ),
            },
        )
        return engine

    def get_mysql_engine(self, source_name: str) -> Engine:
        """
        Retrieves the SQLAlchemy engine for the specified MySQL source.

        Args:
            source_name: Name of the MySQL source.

        Returns:
            SQLAlchemy engine instance.
        """
        if source_name not in self._mysql_engines:
            self._mysql_engines[source_name] = self._create_mysql_engine(source_name)
        return self._mysql_engines[source_name]

    def get_sqlserver_engine(self) -> Engine:
        """
        Retrieves the SQLAlchemy engine for SQL Server.

        Returns:
            SQLAlchemy engine instance.
        """
        if self._sqlserver_engine is None:
            self._sqlserver_engine = self._create_sqlserver_engine()
        return self._sqlserver_engine

    @contextmanager
    def mysql_connection(self, source_name: str) -> Generator[Connection, None, None]:
        """
        Context manager for establishing and closing a MySQL connection.

        Args:
            source_name: Name of the MySQL source.

        Yields:
            SQLAlchemy connection object.
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
                {"execution_time_seconds": round(execution_time, 2)},
            )
        except Exception as e:
            self.logger.error(
                f"MySQL connection error for source: {source_name}", exception=e
            )
            raise
        finally:
            if connection:
                connection.close()

    @contextmanager
    def sqlserver_connection(self) -> Generator[Connection, None, None]:
        """
        Context manager for establishing and closing a SQL Server connection.

        Yields:
            SQLAlchemy connection object.
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
                {"execution_time_seconds": round(execution_time, 2)},
            )
        except Exception as e:
            self.logger.error("SQL Server connection error", exception=e)
            raise
        finally:
            if connection:
                connection.close()

    def test_mysql_connection(self, source_name: str) -> bool:
        """
        Tests the health of a MySQL connection by executing a simple query.

        Args:
            source_name: Name of the MySQL source.

        Returns:
            True if the connection is healthy, False otherwise.
        """
        try:
            with self.mysql_connection(source_name) as conn:
                result = conn.execute(text("SELECT 1"))
                result.fetchone()
            self.logger.info(
                f"MySQL connection test successful for source: {source_name}"
            )
            return True
        except Exception as e:
            self.logger.error(
                f"MySQL connection test failed for source: {source_name}", exception=e
            )
            return False

    def test_sqlserver_connection(self) -> bool:
        """
        Tests the health of a SQL Server connection by executing a simple query.

        Returns:
            True if the connection is healthy, False otherwise.
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
        params: Optional[Dict[str, Any]] = None,
        database_override: Optional[str] = None,
    ) -> Any:
        """
        Executes a SQL query on a MySQL source, optionally targeting a specific database.

        This method obtains a connection engine configured for the specified
        'database_override'. If no override is provided, it uses the default
        database from the source configuration. This approach is safe for use with
        connection pooling as it does not change a connection's state with 'USE'
        commands, preventing state leakage between tasks.

        Args:
            source_name (str): The logical name of the MySQL source configuration.
            query (str): The SQL query string to execute.
            params (Optional[Dict[str, Any]]): Parameters for the query, if any.
            database_override (Optional[str]): The specific database/schema to
                connect to, overriding the default in the source's configuration.

        Returns:
            Any: For SELECT queries, returns a list of rows. For DML statements
                (INSERT, UPDATE, DELETE), returns the number of affected rows.

        Raises:
            ValueError: If the specified source_name is not configured.
            Exception: Propagates underlying exceptions from the database driver.
        """
        start_time = time.time()
        source_config = self.mysql_configs.get(source_name)
        if not source_config:
            raise ValueError(f"MySQL source '{source_name}' not found")

        target_database = database_override or source_config.database

        try:
            with self.mysql_connection(
                source_name, database_override=database_override
            ) as conn:

                execution_params = params or {}
                result = conn.execute(text(query), execution_params)

                if query.strip().upper().startswith("SELECT"):
                    rows = result.fetchall()
                    execution_time = time.time() - start_time
                    self.logger.info(
                        "MySQL query executed successfully",
                        {
                            "source": source_name,
                            "database": target_database,
                            "rows_returned": len(rows),
                            "execution_time_seconds": round(execution_time, 2),
                            "query_type": "SELECT",
                        },
                    )
                    return rows
                else:
                    affected_rows = result.rowcount
                    execution_time = time.time() - start_time
                    operation = query.strip().split()[0].upper()
                    self.logger.info(
                        "MySQL query executed successfully",
                        {
                            "source": source_name,
                            "database": target_database,
                            "affected_rows": affected_rows,
                            "execution_time_seconds": round(execution_time, 2),
                            "query_type": operation,
                        },
                    )
                    return affected_rows
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(
                "MySQL query execution failed",
                exc_info=True,  # Usando exc_info=True para logar o traceback completo
                extra_data={
                    "source": source_name,
                    "database": target_database,
                    "execution_time_seconds": round(execution_time, 2),
                    "query_preview": query[:200] + "..." if len(query) > 200 else query,
                },
            )
            raise

    def execute_sqlserver_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        schema: Optional[str] = None,
        top_n: Optional[int] = None,
    ) -> Any:
        """
        Executes a SQL query on SQL Server, optionally specifying schema and limiting results.

        Args:
            query: SQL query to execute.
            params: Optional query parameters.
            schema: Optional schema name.
            top_n: Optional limit for SELECT queries.

        Returns:
            Query result (rows for SELECT, affected row count for DML).
        """
        start_time = time.time()
        target_schema = schema or self.sqlserver_config.schema
        try:
            with self.sqlserver_connection() as conn:
                safe_query = query
                if top_n and query.strip().upper().startswith("SELECT"):
                    safe_query = query.replace("SELECT", f"SELECT TOP {top_n}", 1)
                result = conn.execute(text(safe_query), params or {})
                if query.strip().upper().startswith("SELECT"):
                    rows = result.fetchall()
                    execution_time = time.time() - start_time
                    self.logger.info(
                        "SQL Server query executed successfully",
                        {
                            "rows_returned": len(rows),
                            "execution_time_seconds": round(execution_time, 2),
                            "database": self.sqlserver_config.database,
                            "schema": target_schema,
                            "query_type": "SELECT",
                        },
                    )
                    return rows
                else:
                    affected_rows = result.rowcount
                    execution_time = time.time() - start_time
                    operation = query.strip().split()[0].upper()
                    self.logger.info(
                        "SQL Server query executed successfully",
                        {
                            "affected_rows": affected_rows,
                            "execution_time_seconds": round(execution_time, 2),
                            "database": self.sqlserver_config.database,
                            "schema": target_schema,
                            "query_type": operation,
                        },
                    )
                    return affected_rows
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(
                "SQL Server query execution failed",
                exception=e,
                extra_data={
                    "execution_time_seconds": round(execution_time, 2),
                    "database": self.sqlserver_config.database,
                    "schema": target_schema,
                    "query_preview": query[:100] + "..." if len(query) > 100 else query,
                },
            )
            raise

    def get_connection_info(self) -> Dict[str, Any]:
        """
        Returns a dictionary containing the current connection configuration information.
        """
        return {
            "current_branch": self.current_branch,
            "is_production": self.is_production,
            "hotfix_mode": self.hotfix_mode,
            "connection_timeout": self.connection_timeout,
            "environment_type": (
                "PROD" if (self.is_production or self.hotfix_mode) else "DEV"
            ),
            "sqlserver_host": self.sqlserver_config.host,
            "sqlserver_database": self.sqlserver_config.database,
            "sqlserver_schema": self.sqlserver_config.schema,
            "mysql_sources": list(self.mysql_configs.keys()),
            "mysql_sources_count": len(self.mysql_configs),
        }

    def fetch_data(
        self,
        source_type: str,
        query: str,
        source_name: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        top_n: Optional[int] = None,
    ):
        """
        Fetch data from either MySQL or SQL Server.

        Args:
            source_type: "mysql" or "sqlserver".
            query: SQL query to execute.
            source_name: MySQL source name (ignored if sqlserver).
            params: Optional query parameters.
            database: Optional override database (MySQL only).
            schema: Optional schema (SQL Server only).
            top_n: Optional limit for SELECT queries (SQL Server only).

        Returns:
            List of rows (dict-like objects).
        """
        if source_type.lower() == "mysql":
            if not source_name:
                raise ValueError("For MySQL, 'source_name' must be provided.")
            return self.execute_mysql_query(
                source_name=source_name,
                query=query,
                params=params,
                database=database,
            )
        elif source_type.lower() == "sqlserver":
            return self.execute_sqlserver_query(
                query=query,
                params=params,
                schema=schema,
                top_n=top_n,
            )
        else:
            raise ValueError(f"Unsupported source_type: {source_type}")

    @contextmanager
    def get_connection(self, source_type: str, source_name: Optional[str] = None):
        """
        Generic context manager to open connection to MySQL or SQL Server.
        """
        if source_type.lower() == "mysql":
            if not source_name:
                raise ValueError("For MySQL, 'source_name' must be provided.")
            with self.mysql_connection(source_name) as conn:
                yield conn
        elif source_type.lower() == "sqlserver":
            with self.sqlserver_connection() as conn:
                yield conn
        else:
            raise ValueError(f"Unsupported source_type: {source_type}")


def get_db_manager(
    hotfix_mode: bool = False, connection_timeout: int = 720
) -> DatabaseConnectionManager:
    """
    Creates and returns a DatabaseConnectionManager instance.

    Args:
        hotfix_mode: If True, use production warehouse even on development branches.
        connection_timeout: Connection timeout in seconds.

    Returns:
        DatabaseConnectionManager instance.
    """
    return DatabaseConnectionManager(
        hotfix_mode=hotfix_mode, connection_timeout=connection_timeout
    )

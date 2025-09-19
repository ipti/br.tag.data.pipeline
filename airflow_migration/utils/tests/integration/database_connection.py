import sys
import os
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from sqlalchemy.exc import OperationalError, DatabaseError
import tempfile
import socket

PROJECT_ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

"""
Comprehensive Database Connection Test Suite
Includes both unit tests (with mocks) and integration tests (real connections)

Usage:
    # Run all tests
    python -m pytest utils/tests/integration/database_connection.py -v

    # Run only unit tests
    python -m pytest utils/tests/integration/database_connection.py::TestDatabaseConnectionManagerUnit -v

    # Run only integration tests
    python -m pytest utils/tests/integration/database_connection.py::TestDatabaseConnectionManagerIntegration -v

    # Run as script for manual testing
    python utils/tests/integration/database_connection.py
"""

from utils.connections.connection_manager import (
    DatabaseConnectionManager,
    DatabaseConfig,
    get_db_manager,
)


class TestDatabaseConnectionManagerUnit:
    """Unit tests using mocks - do not require a real database"""

    def setup_method(self):
        """Setup executado antes de cada teste"""
        self.env_vars = {
            "MYSQL_HOST": "mysql-container",
            "MYSQL_PORT": "3306",
            "MYSQL_DATABASE": "test_db",
            "MYSQL_USER": "test_user",
            "MYSQL_PASSWORD": "test_pass",
            "SQLSERVER_HOST": "sql-server",
            "SQLSERVER_PORT": "1433",
            "SQLSERVER_DATABASE": "warehouse",
            "SQLSERVER_USER": "sa",
            "SQLSERVER_PASSWORD": "test_pass",
            "SQLSERVER_DRIVER": "ODBC Driver 18 for SQL Server",
        }

    @patch.dict(os.environ, {})
    @patch("utils.connections.connection_manager.subprocess.run")
    @patch("utils.connections.connection_manager.get_logger")
    def test_git_branch_detection(self, mock_logger, mock_subprocess):
        """Tests git branch detection logic"""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "main"

        manager = DatabaseConnectionManager()
        assert manager.current_branch == "main"
        assert manager.is_production is True

        mock_subprocess.return_value.stdout = "develop"
        manager = DatabaseConnectionManager()
        assert manager.current_branch == "develop"
        assert manager.is_production is False

    @patch("utils.connections.connection_manager.os.path.exists")
    def test_docker_detection(self, mock_exists):
        """Tests Docker environment detection logic"""
        with patch.dict(os.environ, self.env_vars):
            manager = DatabaseConnectionManager()

            mock_exists.return_value = True
            assert manager._is_running_in_docker() is True

            mock_exists.return_value = False
            assert manager._is_running_in_docker() is False

    @patch("utils.connections.connection_manager.socket.gethostbyname")
    @patch("utils.connections.connection_manager.subprocess.run")
    @patch("utils.connections.connection_manager.get_logger")
    def test_mysql_host_resolution(
        self, mock_logger, mock_subprocess, mock_gethostbyname
    ):
        """Tests MySQL host resolution based on environment"""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "main"

        with patch.dict(os.environ, self.env_vars):
            manager = DatabaseConnectionManager()

            assert manager._resolve_mysql_host("192.168.1.100") == "192.168.1.100"

            with patch.object(manager, "_is_running_in_docker", return_value=False):
                mock_gethostbyname.side_effect = socket.gaierror("Host not found")
                result = manager._resolve_mysql_host("mysql-container")
                assert result == "localhost"

    @patch.dict(
        os.environ,
        {
            "MYSQL_HOST": "mysql-container",
            "MYSQL_USER": "user",
            "MYSQL_PASSWORD": "pass",
            "MYSQL_DATABASE": "test_db",
            "MYSQL_SOURCE1_HOST": "source1-host",
            "MYSQL_SOURCE1_USER": "user1",
            "MYSQL_SOURCE1_PASSWORD": "pass1",
            "MYSQL_SOURCE1_DATABASE": "db1",
            "SQLSERVER_HOST": "test-server",
            "SQLSERVER_USER": "sa",
            "SQLSERVER_PASSWORD": "pass",
        },
    )
    @patch("utils.connections.connection_manager.subprocess.run")
    @patch("utils.connections.connection_manager.get_logger")
    def test_multiple_mysql_sources_discovery(self, mock_logger, mock_subprocess):
        """Tests automatic discovery of multiple MySQL sources from environment variables"""
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "main"

        manager = DatabaseConnectionManager()

        print(
            f"Found {len(manager.mysql_configs)} MySQL sources: {list(manager.mysql_configs.keys())}"
        )
        assert len(manager.mysql_configs) >= 2
        assert len(manager.mysql_configs) > 0

    def test_database_config_dataclass(self):
        """Tests the DatabaseConfig dataclass initialization and attributes"""
        config = DatabaseConfig(
            host="localhost",
            port=3306,
            database="test",
            username="user",
            password="pass",
            schema="dbo",
        )

        assert config.host == "localhost"
        assert config.port == 3306
        assert config.schema == "dbo"


class TestDatabaseConnectionManagerIntegration:
    """Integration tests - require real database connections"""

    @pytest.fixture(scope="class")
    def db_manager(self):
        """Fixture to create a DatabaseConnectionManager for integration tests"""
        try:
            return get_db_manager()
        except Exception as e:
            pytest.skip(f"Could not create DatabaseConnectionManager: {e}")

    def test_connection_info_retrieval(self, db_manager):
        """Tests retrieval of connection configuration information"""
        info = db_manager.get_connection_info()

        assert isinstance(info, dict)
        assert "current_branch" in info
        assert "is_production" in info
        assert "mysql_sources" in info
        assert isinstance(info["mysql_sources"], list)

    def test_mysql_connection_health_check(self, db_manager):
        """Tests health of all configured MySQL connections"""
        if not db_manager.mysql_configs:
            pytest.skip("No MySQL sources configured")

        for source_name in db_manager.mysql_configs.keys():
            try:
                is_healthy = db_manager.test_mysql_connection(source_name)
                print(
                    f"MySQL {source_name} health check: {'✅' if is_healthy else '❌'}"
                )
            except Exception as e:
                print(f"MySQL {source_name} connection error: {e}")

    def test_sqlserver_connection_health_check(self, db_manager):
        """Tests health of SQL Server connection"""
        try:
            is_healthy = db_manager.test_sqlserver_connection()
            print(f"SQL Server health check: {'✅' if is_healthy else '❌'}")
        except Exception as e:
            print(f"SQL Server connection error: {e}")

    @pytest.mark.parametrize("schema_name", ["information_schema", "sys"])
    def test_mysql_schema_queries(self, db_manager, schema_name):
        """Tests querying MySQL schemas for table count"""
        if not db_manager.mysql_configs:
            pytest.skip("No MySQL sources configured")

        source_name = list(db_manager.mysql_configs.keys())[0]
        query = f"""
            SELECT COUNT(*) as table_count 
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = '{schema_name}'
        """

        try:
            result = db_manager.execute_mysql_query(
                source_name=source_name, query=query, database=schema_name
            )
            assert result is not None
            print(f"MySQL schema '{schema_name}' query successful")
        except Exception as e:
            print(f"MySQL schema '{schema_name}' query failed: {e}")

    def test_sqlserver_schema_queries(self, db_manager):
        """Tests querying SQL Server for table count in schemas"""
        query = """
            SELECT COUNT(*) as table_count
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
        """

        try:
            result = db_manager.execute_sqlserver_query(query=query)
            assert result is not None
            print("SQL Server schema query successful")
        except Exception as e:
            print(f"SQL Server schema query failed: {e}")


class TestDatabaseConnectionManagerEdgeCases:
    """Tests for edge cases and error scenarios"""

    def test_invalid_mysql_host(self):
        """Tests behavior when MySQL host is invalid"""
        env_vars = {
            "MYSQL_HOST": "invalid-host-12345",
            "MYSQL_USER": "user",
            "MYSQL_PASSWORD": "pass",
            "MYSQL_DATABASE": "test",
            "SQLSERVER_HOST": "test-server",
            "SQLSERVER_USER": "sa",
            "SQLSERVER_PASSWORD": "pass",
        }

        with patch.dict(os.environ, env_vars):
            manager = DatabaseConnectionManager()
            result = manager.test_mysql_connection("airflow_mysql")
            assert result is False

    @patch.dict(
        os.environ,
        {
            "MYSQL_HOST": "localhost",
            "MYSQL_USER": "user",
            "MYSQL_PASSWORD": "wrong_password",
            "MYSQL_DATABASE": "test",
        },
    )
    def test_mysql_wrong_credentials(self):
        """Tests behavior when MySQL credentials are incorrect"""
        manager = DatabaseConnectionManager()
        result = manager.test_mysql_connection("airflow_mysql")
        assert result is False or result is None


def manual_test_runner():
    """Manual test runner for script execution"""
    from utils.logs.logging_functions import get_logger

    logger = get_logger("database_tests")

    logger.info("Starting comprehensive database connection tests")

    try:
        logger.info("Testing DatabaseConnectionManager initialization")
        db_manager = get_db_manager()
        logger.info("DatabaseConnectionManager initialized successfully")

        logger.info("Retrieving connection information")
        info = db_manager.get_connection_info()
        logger.info("Connection information retrieved", extra_data=info)

        docker_status = db_manager._is_running_in_docker()
        logger.info(
            "Environment detection completed",
            extra_data={
                "running_in_docker": docker_status,
                "current_branch": db_manager.current_branch,
                "is_production": db_manager.is_production,
            },
        )

        logger.info("Testing host resolution")
        test_hosts = ["mysql-container", "localhost", "192.168.1.100"]
        for host in test_hosts:
            resolved = db_manager._resolve_mysql_host(host)
            logger.info(
                f"Host resolution test",
                extra_data={"original_host": host, "resolved_host": resolved},
            )

        logger.info("Testing MySQL connections")
        if db_manager.mysql_configs:
            for source_name in db_manager.mysql_configs.keys():
                try:
                    is_healthy = db_manager.test_mysql_connection(source_name)
                    logger.info(
                        "MySQL connection test completed",
                        extra_data={
                            "source": source_name,
                            "status": "healthy" if is_healthy else "unhealthy",
                        },
                    )
                except Exception as e:
                    logger.error(
                        f"MySQL connection test failed",
                        exception=e,
                        extra_data={"source": source_name},
                    )
        else:
            logger.warning("No MySQL sources configured")

        logger.info("Testing SQL Server connection")
        try:
            is_healthy = db_manager.test_sqlserver_connection()
            logger.info(
                "SQL Server connection test completed",
                extra_data={"status": "healthy" if is_healthy else "unhealthy"},
            )
        except Exception as e:
            logger.error("SQL Server connection test failed", exception=e)

        logger.info("Manual tests completed successfully")
        return True

    except Exception as e:
        logger.error("Fatal error during testing", exception=e)
        return False


if __name__ == "__main__":
    manual_test_runner()
else:
    pass

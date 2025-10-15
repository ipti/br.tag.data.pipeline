import pytest
import os
from unittest.mock import patch

# Importe as classes do seu projeto
from utils.connections.connection_manager import (
    DatabaseConnectionManager,
)


@pytest.fixture
def base_env_vars() -> dict:
    """Provides a base set of environment variables for testing."""
    return {
        "MYSQL_DEV_HOST": "dev-mysql",
        "MYSQL_DEV_USER": "dev_user",
        "MYSQL_DEV_PASSWORD": "dev_password",
        "MYSQL_SOURCE1_HOST": "prod-mysql",
        "MYSQL_SOURCE1_USER": "prod_user",
        "MYSQL_SOURCE1_PASSWORD": "prod_password",
        "SQLSERVER_HOST": "sql-server",
        "SQLSERVER_USER_DEV": "dev_sql_user",
        "SQLSERVER_PASSWORD_DEV": "dev_sql_pw",
        "SQLSERVER_DEV_SCHEMA": "my_dev_schema",
        "SQLSERVER_USER_PRD": "prd_sql_user",
        "SQLSERVER_PASSWORD_PRD": "prd_sql_pw",
        "SQLSERVER_PROD_SCHEMA": "my_prd_schema",
    }


class TestDatabaseConnectionManager:
    """
    Unit tests for the DatabaseConnectionManager, focusing on its core
    configuration and environment-switching logic without real DB connections.
    """

    def test_dev_environment_config(self, base_env_vars: dict):
        """
        Ensures that when initialized with 'dev', the manager correctly loads
        the development-specific configurations.
        """
        with patch.dict(os.environ, base_env_vars, clear=True):
            manager = DatabaseConnectionManager(environment="dev")

        assert manager.is_production is False
        assert manager.sqlserver_config.username == "dev_sql_user"
        assert manager.sqlserver_config.schema == "my_dev_schema"
        assert "airflow_mysql" in manager.mysql_configs

        assert manager.mysql_configs["airflow_mysql"].host == "localhost"

    def test_prod_environment_config(self, base_env_vars: dict):
        """
        Ensures that when initialized with 'prod', the manager correctly loads
        the production-specific configurations.
        """
        with patch.dict(os.environ, base_env_vars, clear=True):
            manager = DatabaseConnectionManager(environment="prod")

        assert manager.is_production is True
        assert manager.sqlserver_config.username == "prd_sql_user"
        assert manager.sqlserver_config.schema == "my_prd_schema"
        assert "mysql_source_1" in manager.mysql_configs
        assert manager.mysql_configs["mysql_source_1"].host == "prod-mysql"

    def test_hotfix_mode_overrides_to_prod_config(self, base_env_vars: dict):
        """
        Validates the critical business rule that 'hotfix_mode=True' forces
        the use of production configurations, even if the environment is 'dev'.
        """
        with patch.dict(os.environ, base_env_vars, clear=True):
            manager = DatabaseConnectionManager(environment="dev", hotfix_mode=True)

        assert manager.hotfix_mode is True
        assert manager.sqlserver_config.username == "prd_sql_user"
        assert manager.sqlserver_config.schema == "my_prd_schema"

    def test_invalid_environment_raises_value_error(self):
        """

        Ensures the constructor fails gracefully by raising a ValueError if
        an unsupported environment string is provided.
        """
        with pytest.raises(ValueError):
            DatabaseConnectionManager(environment="staging")

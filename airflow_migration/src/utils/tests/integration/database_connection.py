import pytest
import os
from unittest.mock import patch

# Importe as classes do seu projeto
from utils.connections.connection_manager import (
    DatabaseConnectionManager,
)

# --- Testes Unitários para a Lógica de Configuração (Refatorados) ---


class TestDatabaseConnectionManagerUnit:
    """
    Unit tests for the DatabaseConnectionManager, focusing on configuration
    logic without making real database connections.
    """

    def setup_method(self):
        """Setup common environment variables for tests."""
        self.env_vars = {
            "MYSQL_HOST": "mysql-container",
            "MYSQL_USER": "test_user",
            "MYSQL_PASSWORD": "pw",
            "SQLSERVER_HOST": "sql-server",
            "SQLSERVER_USER_DEV": "dev_user",
            "SQLSERVER_PASSWORD_DEV": "dev_pw",
            "SQLSERVER_DEV_SCHEMA": "my_dev_schema",
            "SQLSERVER_USER_PRD": "prd_user",
            "SQLSERVER_PASSWORD_PRD": "prd_pw",
            "SQLSERVER_PROD_SCHEMA": "my_prd_schema",
        }

    def test_dev_environment_setup(self):
        """
        Tests if the manager correctly configures itself for the 'dev' environment.
        """
        with patch.dict(os.environ, self.env_vars):
            # Instancia o manager explicitamente para o ambiente 'dev'
            manager = DatabaseConnectionManager(environment="dev")

        assert manager.environment == "dev"
        assert manager.is_production is False
        assert manager.sqlserver_config.username == "dev_user"
        assert manager.sqlserver_config.schema == "my_dev_schema"

    def test_prod_environment_setup(self):
        """
        Tests if the manager correctly configures itself for the 'prod' environment.
        """
        with patch.dict(os.environ, self.env_vars):
            # Instancia o manager explicitamente para o ambiente 'prod'
            manager = DatabaseConnectionManager(environment="prod")

        assert manager.environment == "prod"
        assert manager.is_production is True
        assert manager.sqlserver_config.username == "prd_user"
        assert manager.sqlserver_config.schema == "my_prd_schema"

    def test_hotfix_mode_setup(self):
        """
        Tests if hotfix mode correctly uses production settings even in a dev environment.
        """
        with patch.dict(os.environ, self.env_vars):
            # Instancia em 'dev', mas com a flag 'hotfix' ativada
            manager = DatabaseConnectionManager(environment="dev", hotfix_mode=True)

        assert manager.hotfix_mode is True
        # Verifica se as configurações de SQL Server são as de produção
        assert manager.sqlserver_config.username == "prd_user"
        assert manager.sqlserver_config.schema == "my_prd_schema"

    def test_multiple_mysql_sources_discovery(self):
        """
        Tests the discovery of multiple MySQL sources from environment variables.
        """
        # Define um ambiente limpo com APENAS as variáveis que queremos testar
        test_env_vars = {
            "MYSQL_HOST": "mysql-container",
            "MYSQL_USER": "user",
            "MYSQL_PASSWORD": "pass",
            "MYSQL_DATABASE": "test_db",
            "MYSQL_SOURCE1_HOST": "source1-host",
            "MYSQL_SOURCE1_USER": "user1",
            "MYSQL_SOURCE1_PASSWORD": "pw1",
            "MYSQL_SOURCE2_HOST": "source2-host",
            "MYSQL_SOURCE2_USER": "user2",
            "MYSQL_SOURCE2_PASSWORD": "pw2",
            # Adiciona as variáveis do SQL Server para que o __init__ não falhe
            "SQLSERVER_HOST": "test-server",
            "SQLSERVER_USER_DEV": "sa",
            "SQLSERVER_PASSWORD_DEV": "pass",
            "SQLSERVER_DEV_SCHEMA": "dev",
        }

        # O 'patch.dict' agora usa 'clear=True' para isolar o ambiente
        with patch.dict(os.environ, test_env_vars, clear=True):
            # Desabilitamos o _load_environment para garantir que o .env real não seja lido
            with patch.object(
                DatabaseConnectionManager, "_load_environment", return_value=None
            ):
                manager = DatabaseConnectionManager(environment="dev")

        # A asserção agora deve passar, pois o manager só verá 3 fontes
        # (airflow_mysql, mysql_source_1, mysql_source_2)
        assert len(manager.mysql_configs) == 3

    def test_invalid_environment_raises_error(self):
        """
        Tests that initializing with an invalid environment string raises a ValueError.
        """
        with pytest.raises(ValueError) as excinfo:
            DatabaseConnectionManager(environment="staging")

        assert "Environment must be either 'dev' or 'prod'" in str(excinfo.value)


# --- Testes de Integração (Opcionais, para rodar contra bancos reais) ---


# Os testes de integração são muito úteis, mas dependem de um ambiente real.
# A anotação @pytest.mark.skip os desabilita por padrão.
# Para rodá-los, você pode comentar a linha @pytest.mark.skip e garantir
# que suas variáveis de ambiente (.env) estão configuradas corretamente.
@pytest.mark.skip(
    reason="Integration tests require real database connections and credentials."
)
class TestDatabaseConnectionManagerIntegration:
    """
    Integration tests - require real database connections configured via .env file.
    """

    @pytest.fixture(scope="class")
    def db_manager_dev(self):
        """Fixture for a DEV environment connection manager."""
        return DatabaseConnectionManager(environment="dev")

    def test_get_connection_info(self, db_manager_dev):
        """Tests that get_connection_info returns a correctly structured dictionary."""
        info = db_manager_dev.get_connection_info()
        assert isinstance(info, dict)
        assert info["environment"] == "dev"
        assert info["is_production"] is False
        assert "mysql_sources" in info

    def test_mysql_connection_health(self, db_manager_dev):
        """Tests the health of the 'airflow_mysql' connection."""
        if "airflow_mysql" not in db_manager_dev.mysql_configs:
            pytest.skip("Default 'airflow_mysql' source not configured in .env")

        assert db_manager_dev.test_mysql_connection("airflow_mysql") is True

    def test_sqlserver_connection_health(self, db_manager_dev):
        """Tests the health of the SQL Server connection."""
        assert db_manager_dev.test_sqlserver_connection() is True

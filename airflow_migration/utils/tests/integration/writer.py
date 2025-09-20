import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import MagicMock, patch

from utils.connections.writer import (
    CopyAndLoader,
    LoadResult,
    IncrementalConfig,
    TableMapping,
    UpsertConfig
)


@pytest.fixture
def mock_db_manager():
    """Mock do DatabaseConnectionManager para evitar conexões reais."""
    mock = MagicMock()
    mock.sqlserver_config.schema = "dbo"
    mock.get_connection_info.return_value = {"environment_type": "test"}
    return mock


@pytest.fixture
def loader(mock_db_manager):
    """Instância do CopyAndLoader com db_manager mockado."""
    return CopyAndLoader(db_manager=mock_db_manager)


def test_batch_loader_success(loader, mock_db_manager):
    # Simula fetch_data retornando dados
    mock_db_manager.fetch_data.return_value = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]

    # Mock para evitar escrita real no banco
    mock_engine = MagicMock()
    loader.db_manager.get_sqlserver_engine.return_value = mock_engine

    result = loader.batch_loader(
        source_type="mysql",
        source_schema="",
        source_table="users",
        target_schema="dbo",
        target_table="users",
        source_name="mock_mysql"
    )

    assert isinstance(result, LoadResult)
    assert result.success is True
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    assert result.error_message is None
    mock_db_manager.fetch_data.assert_called_once()


def test_batch_loader_no_data(loader, mock_db_manager):
    mock_db_manager.fetch_data.return_value = []

    result = loader.batch_loader(
        source_type="mysql",
        source_schema="",
        source_table="users",
        target_schema="dbo",
        target_table="users",
        source_name="mock_mysql"
    )

    assert result.success is True
    assert result.rows_processed == 0
    assert result.rows_inserted == 0


def test_incremental_load_full_refresh(loader, mock_db_manager):
    # Configuração de incremental full refresh
    inc_config = IncrementalConfig(
        source_timestamp_column="updated_at",
        target_timestamp_column="updated_at",
        full_refresh=True
    )

    mock_db_manager.execute_mysql_query.return_value = [
        {"id": 1, "updated_at": datetime.now()},
        {"id": 2, "updated_at": datetime.now()},
    ]
    mock_db_manager.get_sqlserver_engine.return_value = MagicMock()

    result = loader.incremental_load(
        source_name="mock_mysql",
        source_table="users",
        target_table="users",
        incremental_config=inc_config
    )

    assert result.success is True
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    assert result.error_message is None


def test_incremental_load_no_data(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_column="updated_at",
        target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.return_value = []

    result = loader.incremental_load(
        source_name="mock_mysql",
        source_table="users",
        target_table="users",
        incremental_config=inc_config
    )

    assert result.success is True
    assert result.rows_processed == 0
    assert result.rows_inserted == 0


def test_incremental_load_with_error(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_column="updated_at",
        target_timestamp_column="updated_at"
    )

    mock_db_manager.execute_mysql_query.side_effect = Exception("MySQL error")

    result = loader.incremental_load(
        source_name="mock_mysql",
        source_table="users",
        target_table="users",
        incremental_config=inc_config
    )

    assert result.success is False
    assert "MySQL error" in result.error_message

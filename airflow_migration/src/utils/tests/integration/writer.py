import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import MagicMock, patch

from airflow_migration.src.utils.connections.writer import (
    CopyAndLoader,
    LoadResult,
    IncrementalConfig,
    TableMapping,
    UpsertConfig,
)


@pytest.fixture
def mock_db_manager():
    """Mock do DatabaseConnectionManager para evitar conexões reais."""
    mock = MagicMock()
    mock.sqlserver_config.schema = "dbo"
    mock.get_connection_info.return_value = {"environment_type": "test"}
    mock.get_last_timestamp.return_value = None
    return mock


@pytest.fixture
def loader(mock_db_manager):
    """Instância do CopyAndLoader com db_manager mockado."""
    return CopyAndLoader(db_manager=mock_db_manager)


def test_batch_loader_success(loader, mock_db_manager):
    # CORREÇÃO 1: Adicione colunas esperadas (como 'updated_at') aos dados do mock,
    # mesmo que a lógica específica do batch_loader não as use diretamente.
    # Isso evita erros em funções de limpeza/parsing genéricas.
    mock_db_manager.fetch_data.return_value = [
        {"id": 1, "name": "Alice", "updated_at": datetime.now()},
        {"id": 2, "name": "Bob", "updated_at": datetime.now()},
    ]

    # CORREÇÃO 2: Crie um mock mais robusto para o engine que suporte o 'with'.
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    # Configura o mock para funcionar com 'with engine.begin() as conn:'
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    loader.db_manager.get_sqlserver_engine.return_value = mock_engine

    result = loader.batch_loader(
        source_type="mysql",
        source_schema="",
        source_table="users",
        target_schema="dbo",
        target_table="users",
        source_name="mock_mysql",
    )

    assert (
        result.success is True
    ), f"A execução falhou com o erro: {result.error_message}"
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    mock_db_manager.fetch_data.assert_called_once()


def test_batch_loader_no_data(loader, mock_db_manager):
    mock_db_manager.fetch_data.return_value = []
    result = loader.batch_loader(
        source_type="mysql",
        source_schema="",
        source_table="users",
        target_schema="dbo",
        target_table="users",
        source_name="mock_mysql",
    )
    assert result.success is True
    assert result.rows_processed == 0
    assert result.rows_inserted == 0


def test_incremental_load_full_refresh(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="updated_at",
        full_refresh=True,
    )
    mock_db_manager.execute_mysql_query.return_value = [
        {"id": 1, "updated_at": datetime.now()},
        {"id": 2, "updated_at": datetime.now()},
    ]

    # CORREÇÃO 2 (APLICADA AQUI TAMBÉM): Crie um mock mais robusto para o engine.
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    loader.db_manager.get_sqlserver_engine.return_value = mock_engine

    result = loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_table=None,
        source_query="SELECT * FROM users WHERE updated_at >= {safe_timestamp} {first_run_null_check};",
    )

    assert (
        result.success is True
    ), f"A execução falhou com o erro: {result.error_message}"
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    assert result.error_message is None


def test_incremental_load_no_data(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.return_value = []

    result = loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_table=None,
        source_query="SELECT * FROM users WHERE updated_at >= {safe_timestamp} {first_run_null_check};",
    )

    assert result.success is True
    assert result.rows_processed == 0
    assert result.rows_inserted == 0


def test_incremental_load_with_error(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.side_effect = Exception("MySQL error")

    # Adicionada source_query para usar a nova lógica
    result = loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_table=None,
        source_query="SELECT * FROM users WHERE updated_at >= {safe_timestamp} {first_run_null_check};",
    )

    assert result.success is False
    assert "MySQL error" in result.error_message


def test_incremental_load_first_run_multiple_timestamps(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_columns=["t1.updated_at", "t2.modified_at"],
        target_timestamp_column="dw_updated_at",
    )
    with patch.object(CopyAndLoader, "_get_last_timestamp", return_value=None):
        loader.incremental_load(
            source_name="mock_mysql",
            target_table="target_table",
            incremental_config=inc_config,
            source_table=None,
            source_query="SELECT * FROM t1 JOIN t2 ON t1.id = t2.id WHERE (t1.updated_at >= {safe_timestamp} OR t2.modified_at >= {safe_timestamp} {first_run_null_check});",
        )
    executed_query = mock_db_manager.execute_mysql_query.call_args[0][1]
    assert "'1900-01-01 00:00:00'" in executed_query
    assert "OR t1.updated_at IS NULL OR t2.modified_at IS NULL" in executed_query


def test_incremental_load_subsequent_run_multiple_timestamps(loader, mock_db_manager):
    inc_config = IncrementalConfig(
        source_timestamp_columns=["t1.updated_at", "t2.modified_at"],
        target_timestamp_column="dw_updated_at",
        lookback_hours=2,
    )
    last_ts = datetime(2025, 9, 23, 14, 0, 0)
    safe_ts_expected = "2025-09-23 12:00:00"
    with patch.object(CopyAndLoader, "_get_last_timestamp", return_value=last_ts):
        loader.incremental_load(
            source_name="mock_mysql",
            target_table="target_table",
            incremental_config=inc_config,
            source_table=None,
            source_query="SELECT * FROM t1 JOIN t2 ON t1.id = t2.id WHERE (t1.updated_at >= {safe_timestamp} OR t2.modified_at >= {safe_timestamp} {first_run_null_check});",
        )
    executed_query = mock_db_manager.execute_mysql_query.call_args[0][1]
    assert f"'{safe_ts_expected}'" in executed_query
    assert "{first_run_null_check}" not in executed_query
    assert "IS NULL" not in executed_query

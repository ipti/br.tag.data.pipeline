import pytest
from unittest.mock import MagicMock, patch

from utils.connections.writer import (
    CopyAndLoader,
    IncrementalConfig,
    UpsertConfig,
)
from utils.connections.connection_manager import DatabaseConnectionManager


@pytest.fixture
def mock_db_manager() -> MagicMock:
    """
    Provides a fully configured mock for the DatabaseConnectionManager.
    """
    mock = MagicMock(spec=DatabaseConnectionManager)
    mock_sql_config = MagicMock()
    mock_sql_config.schema = "dbo"
    mock.sqlserver_config = mock_sql_config
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock.get_sqlserver_engine.return_value = mock_engine
    return mock


@pytest.fixture
def loader(mock_db_manager: MagicMock) -> CopyAndLoader:
    """
    Provides a CopyAndLoader instance with a mocked db_manager.
    """
    with patch.object(CopyAndLoader, "_load_dbt_sources_config", return_value={}):
        yield CopyAndLoader(db_manager=mock_db_manager)


def test_incremental_load_success_flow(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Tests the main success path for incremental_load.
    Ensures that when data is returned from the source query, the result is successful and rows_processed is correct.

    Example:
        result.success == True
        result.rows_processed == 2
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.return_value = [
        {"id": 1, "col": "a"},
        {"id": 2, "col": "b"},
    ]
    result = loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT id, col FROM source_users",
        source_database="my_db",
    )
    assert (
        result.success is True
    ), f"Execution failed with error: {result.error_message}"
    assert result.rows_processed == 2


def test_incremental_load_handles_exception_gracefully(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Ensures that if the database query fails, the result object reflects the failure and contains the error message.

    Example:
        result.success == False
        "DB Connection Error" in result.error_message
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.side_effect = Exception("DB Connection Error")
    result = loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT 1",
    )
    assert result.success is False
    assert "DB Connection Error" in result.error_message


def test_incremental_load_with_upsert(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Tests that the upsert logic is triggered when an upsert_config is provided.
    Ensures that _perform_upsert is called and the result is successful.

    Example:
        result.success == True
        _perform_upsert is called once
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    upsert_config = UpsertConfig(source_key_columns=["id"])
    mock_db_manager.execute_mysql_query.return_value = [{"id": 1, "col": "a"}]
    with patch.object(loader, "_perform_upsert", return_value=(1, 0)) as mock_upsert:
        result = loader.incremental_load(
            source_name="mock_mysql",
            target_table="users",
            incremental_config=inc_config,
            source_query="SELECT 1",
            upsert_config=upsert_config,
        )
    assert result.success is True
    mock_upsert.assert_called_once()


def test_incremental_load_no_data_returns_success(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Tests that the load is successful when the source query returns no data.
    Ensures that result.success is True and rows_processed is zero.

    Example:
        result.success == True
        result.rows_processed == 0
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.return_value = []
    result = loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT 1",
    )
    assert result.success is True
    assert result.rows_processed == 0

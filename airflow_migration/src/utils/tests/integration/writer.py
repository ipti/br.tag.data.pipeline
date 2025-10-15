import pytest
from unittest.mock import MagicMock, patch

from utils.connections.writer import CopyAndLoader, IncrementalConfig, UpsertConfig
from utils.connections.connection_manager import DatabaseConnectionManager


@pytest.fixture
def mock_db_manager() -> MagicMock:
    """
    Provides a fully configured mock for the DatabaseConnectionManager,
    isolating the CopyAndLoader from real database connections.
    The mock includes a nested sqlserver_config and a fetch_data method returning sample data.
    """
    mock = MagicMock(spec=DatabaseConnectionManager)
    mock_sql_config = MagicMock()
    mock_sql_config.schema = "dbo"
    mock.sqlserver_config = mock_sql_config
    mock.fetch_data.return_value = [
        {"id": 1, "name": "Alice"},
        {"id": 2, "name": "Bob"},
    ]
    return mock


@pytest.fixture
def loader(mock_db_manager: MagicMock) -> CopyAndLoader:
    """
    Provides a CopyAndLoader instance with its dependencies mocked.
    The DBT sources config is patched to an empty dictionary for isolation.
    """
    with patch.object(CopyAndLoader, "_load_dbt_sources_config", return_value={}):
        yield CopyAndLoader(db_manager=mock_db_manager)


@patch("utils.connections.writer.clean_dataframe_for_sql", side_effect=lambda df: df)
@patch.object(CopyAndLoader, "_insert_dataframe_direct", return_value=2)
def test_incremental_load_calls_append_flow(
    mock_insert: MagicMock,
    mock_clean: MagicMock,
    loader: CopyAndLoader,
    mock_db_manager: MagicMock,
):
    """
    Tests the main success path for a simple INSERT (append) load.
    Verifies that the loader processes and inserts all rows, and the mocks are called as expected.

    Example:
        result.success == True
        result.rows_processed == 2
        result.rows_inserted == 2
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["ts"], target_timestamp_column="ts"
    )
    result = loader.incremental_load(
        source_type="mysql",
        source_name="mock_mysql",
        source_database="my_db",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT * FROM users",
        upsert_config=None,
    )
    assert (
        result.success is True
    ), f"Execution failed with error: {result.error_message}"
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    mock_db_manager.fetch_data.assert_called_once()
    mock_clean.assert_called_once()
    mock_insert.assert_called_once()


@patch("utils.connections.writer.clean_dataframe_for_sql", side_effect=lambda df: df)
@patch.object(CopyAndLoader, "_perform_upsert", return_value=(1, 1))
def test_incremental_load_calls_upsert_flow(
    mock_upsert: MagicMock,
    mock_clean: MagicMock,
    loader: CopyAndLoader,
    mock_db_manager: MagicMock,
):
    """
    Tests the main success path for an UPSERT load.
    Verifies that the loader processes the upsert and the mocks are called as expected.

    Example:
        result.success == True
        result.rows_inserted == 1
        result.rows_updated == 1
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["ts"], target_timestamp_column="ts"
    )
    upsert_config = UpsertConfig(source_key_columns=["id"])
    result = loader.incremental_load(
        source_type="mysql",
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT * FROM users",
        upsert_config=upsert_config,
    )
    assert result.success is True
    assert result.rows_inserted == 1
    assert result.rows_updated == 1
    mock_db_manager.fetch_data.assert_called_once()
    mock_clean.assert_called_once()
    mock_upsert.assert_called_once()


def test_incremental_load_no_data_returns_success(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Tests the behavior when the source query returns no data.
    Verifies that the loader returns a successful result with zero rows processed.

    Example:
        result.success == True
        result.rows_processed == 0
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["ts"], target_timestamp_column="ts"
    )
    mock_db_manager.fetch_data.return_value = []
    result = loader.incremental_load(
        source_type="mysql",
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT * FROM users",
    )
    assert result.success is True
    assert result.rows_processed == 0


def test_incremental_load_handles_fetch_exception(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Ensures that if the db_manager fails to fetch data, the exception is caught and the result is unsuccessful.
    Verifies that the error message contains the exception details.

    Example:
        result.success == False
        "Connection Timeout" in result.error_message
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["ts"], target_timestamp_column="ts"
    )
    mock_db_manager.fetch_data.side_effect = Exception("Connection Timeout")
    result = loader.incremental_load(
        source_type="mysql",
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_query="SELECT * FROM users",
    )
    assert result.success is False
    assert "Connection Timeout" in result.error_message

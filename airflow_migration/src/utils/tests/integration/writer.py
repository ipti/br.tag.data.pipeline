import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from utils.connections.writer import (
    CopyAndLoader,
    IncrementalConfig,
)


@pytest.fixture
def mock_db_manager():
    """
    Returns a mock DatabaseConnectionManager configured for integration tests.
    """
    mock = MagicMock()
    mock.sqlserver_config.schema = "dbo"
    mock.execute_mysql_query.return_value = [{"id": 1, "name": "Alice"}]
    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_engine.begin.return_value.__enter__.return_value = mock_conn
    mock.get_sqlserver_engine.return_value = mock_engine
    return mock


@pytest.fixture
def loader(mock_db_manager):
    """
    Returns a CopyAndLoader instance with a mocked db_manager for testing.
    """
    return CopyAndLoader(db_manager=mock_db_manager)


def test_process_query_placeholders_first_run():
    """
    Tests _process_query_placeholders for the first run scenario.
    Ensures that the default timestamp and null checks are inserted in the query.

    Example output:
        SELECT * FROM t WHERE ts >= '1900-01-01 00:00:00' OR ts IS NULL;
    """
    loader = CopyAndLoader(db_manager=MagicMock())
    query = "SELECT * FROM t WHERE ts >= {safe_timestamp} {first_run_null_check};"
    processed = loader._process_query_placeholders(
        source_query=query,
        last_timestamp=None,
        safe_timestamp=None,
        full_refresh=False,
        source_timestamp_columns=["ts"],
    )
    assert "'1900-01-01 00:00:00'" in processed
    assert "OR ts IS NULL" in processed


def test_process_query_placeholders_incremental_run():
    """
    Tests _process_query_placeholders for a normal incremental run.
    Ensures that the correct safe_timestamp is inserted and no null check is present.

    Example output:
        SELECT * FROM t WHERE ts >= '2025-09-26 10:00:00';
    """
    loader = CopyAndLoader(db_manager=MagicMock())
    query = "SELECT * FROM t WHERE ts >= {safe_timestamp} {first_run_null_check};"
    safe_ts = datetime(2025, 9, 26, 10, 0, 0)
    processed = loader._process_query_placeholders(
        source_query=query,
        last_timestamp=datetime(2025, 9, 26, 12, 0, 0),
        safe_timestamp=safe_ts,
        full_refresh=False,
        source_timestamp_columns=["ts"],
    )
    assert safe_ts.strftime("'%Y-%m-%d %H:%M:%S'") in processed
    assert "IS NULL" not in processed


def test_batch_loader_success(loader, mock_db_manager):
    """
    Tests batch_loader for successful data load.
    Ensures that rows are processed and inserted correctly.

    Example output:
        result.success == True
        result.rows_processed == 2
        result.rows_inserted == 2
    """
    mock_db_manager.fetch_data.return_value = [
        {"id": 1, "name": "Alice", "updated_at": datetime.now()},
        {"id": 2, "name": "Bob", "updated_at": datetime.now()},
    ]
    mock_engine = MagicMock()
    mock_conn = MagicMock()
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

    assert result.success is True
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    mock_db_manager.fetch_data.assert_called_once()


def test_incremental_load_no_new_data(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Tests incremental_load when the source query returns no new data.
    Ensures that the result is successful and no rows are processed.
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


def test_incremental_load_passes_source_database(
    loader: CopyAndLoader, mock_db_manager: MagicMock
):
    """
    Tests that the source_database parameter is passed to db_manager in incremental_load.
    Ensures that database_override is set correctly in the call.
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    loader.incremental_load(
        source_name="mock_mysql",
        target_table="users",
        incremental_config=inc_config,
        source_database="specific_db_name",
        source_query="SELECT 1",
    )
    call_kwargs = mock_db_manager.execute_mysql_query.call_args.kwargs
    assert call_kwargs["database_override"] == "specific_db_name"


def test_batch_loader_no_data(loader, mock_db_manager):
    """
    Tests batch_loader when no data is returned from the source.
    Ensures that the result is successful and zero rows are processed and inserted.
    """
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
    """
    Tests incremental_load with full_refresh enabled.
    Ensures that all rows are processed and inserted, and the result is successful.
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="updated_at",
        full_refresh=True,
    )
    mock_db_manager.execute_mysql_query.return_value = [
        {"id": 1, "updated_at": datetime.now()},
        {"id": 2, "updated_at": datetime.now()},
    ]
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

    assert result.success is True
    assert result.rows_processed == 2
    assert result.rows_inserted == 2
    assert result.error_message is None


def test_incremental_load_no_data(loader, mock_db_manager):
    """
    Tests incremental_load when no data is returned from the source query.
    Ensures that the result is successful and zero rows are processed and inserted.
    """
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
    """
    Tests incremental_load when an exception is raised by db_manager.
    Ensures that the result is unsuccessful and the error message is present.
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="updated_at"
    )
    mock_db_manager.execute_mysql_query.side_effect = Exception("MySQL error")

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
    """
    Tests incremental_load for the first run with multiple timestamp columns.
    Ensures that the default timestamp and null checks are present for all columns.

    Example output:
        WHERE (t1.updated_at >= '1900-01-01 00:00:00' OR t2.modified_at >= '1900-01-01 00:00:00' OR t1.updated_at IS NULL OR t2.modified_at IS NULL)
    """
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


def test_incremental_load_subsequent_run_success(loader: CopyAndLoader):
    """
    Tests a successful incremental run with a valid safe_timestamp.
    Ensures that the correct timestamp is used in the query.

    Example output:
        WHERE updated_at >= '2025-09-26 11:00:00'
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="updated_at",
        lookback_hours=1,
    )
    last_ts = datetime(2025, 9, 26, 12, 0, 0)
    with patch.object(loader, "_get_last_timestamp", return_value=last_ts):
        result = loader.incremental_load(
            source_name="mock_mysql",
            target_table="users",
            incremental_config=inc_config,
            source_query="SELECT * FROM users WHERE updated_at >= {safe_timestamp};",
        )
    assert result.success is True
    executed_query = loader.db_manager.execute_mysql_query.call_args[0][1]
    assert "'2025-09-26 11:00:00'" in executed_query


def test_incremental_load_subsequent_run_multiple_timestamps(loader, mock_db_manager):
    """
    Tests incremental_load for a subsequent run with multiple timestamp columns and lookback.
    Ensures that the correct safe_timestamp is used and no null checks are present.

    Example output:
        WHERE (t1.updated_at >= '2025-09-23 12:00:00' OR t2.modified_at >= '2025-09-23 12:00:00')
    """
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

import pytest
from unittest.mock import patch
from pathlib import Path

from airflow.exceptions import AirflowException

from plugins.operators.warehouse_etl_operator import WarehouseEtlOperator
from utils.connections.writer import LoadResult
from utils.planner.execution_planner import TableExecution
from utils.planner.warehouse_basic_config import IncrementalConfig, UpsertConfig


@pytest.fixture
def sample_table_execution_dict(tmp_path: Path) -> dict:
    """
    Creates a serialized TableExecution dictionary and a temporary SQL file for testing.
    """
    sql_file = tmp_path / "d_student.sql"
    sql_file.write_text("SELECT * FROM {{ database }}.raw_students")

    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="inserted_at"
    )
    ups_config = UpsertConfig(source_key_columns=["id"])
    db_name = "nossasenhoradagloria_db"

    exec_obj = TableExecution(
        table_name="d_student",
        stage=1,
        database=db_name,
        source_name="{SOURCE_NAME}",
        target_schema="{TARGET_SCHEMA}",
        trigger="daily",
        model="tables/d_student.yml",
        sql_path=str(sql_file),
        incremental_config=inc_config,
        upsert_config=ups_config,
        execution_context={"database": db_name},
        pool="default_pool",
        retries=2,
        retry_delay_minutes=5,
    )
    return exec_obj.to_dict()


@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
def test_operator_execute_success_flow(
    mock_copy_loader_class, mock_db_manager_class, sample_table_execution_dict
):
    """
    Tests the complete and successful execution flow of WarehouseEtlOperator.
    Ensures that the operator calls the loader and returns the expected result.

    Example output:
        {"status": "success", "rows_processed": 100}
    """
    mock_db_manager_instance = mock_db_manager_class.return_value
    mock_db_manager_instance.is_production, mock_db_manager_instance.hotfix_mode = (
        False,
        False,
    )
    mock_db_manager_instance.sqlserver_config.schema = "resolved_dev_schema"

    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=True, rows_processed=100
    )

    operator = WarehouseEtlOperator(
        task_id="test_success", table_execution_dict=sample_table_execution_dict
    )
    result = operator.execute(context={})

    mock_db_manager_class.assert_called_once_with(hotfix_mode=False)
    mock_copy_loader_class.assert_called_once_with(db_manager=mock_db_manager_instance)
    mock_loader_instance.incremental_load.assert_called_once()
    call_kwargs = mock_loader_instance.incremental_load.call_args.kwargs

    assert call_kwargs["source_database"] == "nossasenhoradagloria_db"
    assert (
        "SELECT * FROM `nossasenhoradagloria_db`.raw_students"
        in call_kwargs["source_query"]
    )
    assert result == {"status": "success", "rows_processed": 100}


@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
def test_operator_handles_load_failure(
    mock_copy_loader_class, mock_db_manager_class, sample_table_execution_dict
):
    """
    Tests that WarehouseEtlOperator raises AirflowException when CopyAndLoader fails.
    Ensures the error message contains the table name and error details.

    Example output:
        AirflowException("Load operation failed for table d_student. Error: DB timeout")
    """
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=False, error_message="DB timeout"
    )

    operator = WarehouseEtlOperator(
        task_id="test_failure", table_execution_dict=sample_table_execution_dict
    )
    with pytest.raises(AirflowException) as excinfo:
        operator.execute(context={})

    assert "Load operation failed for table d_student. Error: DB timeout" in str(
        excinfo.value
    )


@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
def test_operator_hotfix_mode_is_passed(
    mock_copy_loader_class, mock_db_manager_class, sample_table_execution_dict
):
    """
    Tests that the hotfix flag is correctly passed to DatabaseConnectionManager.
    Ensures that hotfix_mode=True is used when initializing the manager.
    """
    operator = WarehouseEtlOperator(
        task_id="test_hotfix",
        table_execution_dict=sample_table_execution_dict,
        hotfix=True,
    )
    operator.execute(context={})
    mock_db_manager_class.assert_called_once_with(hotfix_mode=True)


def test_operator_fails_on_missing_sql_file(sample_table_execution_dict):
    """
    Tests that the operator fails if the sql_path is invalid or the SQL file does not exist.
    Ensures that AirflowException is raised with the correct error message.

    Example output:
        AirflowException("Task failed unexpectedly: SQL file not found at ...")
    """
    sample_table_execution_dict["sql_path"] = "/invalid/path/to/non_existent.sql"
    operator = WarehouseEtlOperator(
        task_id="test_missing_file", table_execution_dict=sample_table_execution_dict
    )
    with pytest.raises(AirflowException) as excinfo:
        operator.execute(context={})
    assert "Task failed unexpectedly: SQL file not found at" in str(excinfo.value)

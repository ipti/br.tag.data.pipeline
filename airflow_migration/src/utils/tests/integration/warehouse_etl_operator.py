import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

from airflow.exceptions import AirflowException

from plugins.operators.warehouse_etl_operator import WarehouseEtlOperator
from utils.connections.writer import LoadResult
from utils.planner.execution_planner import TableExecution
from utils.planner.warehouse_basic_config import IncrementalConfig, UpsertConfig


@pytest.fixture
def sample_table_execution_dict(tmp_path: Path) -> dict:
    """
    Creates a serialized TableExecution dictionary and a temporary SQL file for testing.
    The sql_path is set to a relative file in the temp directory.
    """
    sql_file_name = "d_student.sql"
    sql_file = tmp_path / sql_file_name
    sql_file.write_text(
        "SELECT * FROM `{{ database }}`.raw_students WHERE updated_at >= '{{ safe_timestamp }}';"
    )

    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="inserted_at",
        lookback_hours=12,
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
        sql_path=sql_file_name,
        incremental_config=inc_config,
        upsert_config=ups_config,
        pool="default_pool",
        retries=3,
        retry_delay_minutes=5,
        execution_context={"database": db_name, "environment": "dev"},
    )
    return exec_obj.to_dict()


@pytest.fixture
def mock_airflow_context() -> dict:
    """
    Creates a mock Airflow context dictionary for operator execution.
    """
    mock_ti = MagicMock()
    mock_ti.xcom_pull.return_value = datetime(2025, 10, 1, 12, 0, 0)
    mock_dag_run = MagicMock()
    mock_dag_run.conf = {}
    return {"ti": mock_ti, "dag_run": mock_dag_run}


@patch("airflow.models.Variable.get")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_execute_success_flow(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_variable_get: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
    tmp_path: Path,
):
    """
    Tests the complete and successful execution flow of WarehouseEtlOperator.
    Ensures that the operator returns the correct result and interacts with dependencies as expected.

    Example:
        result == {"status": "success", "rows_processed": 123}
    """
    mock_variable_get.return_value = str(tmp_path)
    mock_db_manager_instance = mock_db_manager_class.return_value
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=True, rows_processed=123
    )
    operator = WarehouseEtlOperator(
        task_id="test_success_flow",
        table_execution_dict=sample_table_execution_dict,
    )
    result = operator.execute(context=mock_airflow_context)
    assert result == {"status": "success", "rows_processed": 123}
    mock_variable_get.assert_called_with("etl_config_root_path")
    mock_db_manager_class.assert_called_once_with(environment="dev", hotfix_mode=False)
    mock_copy_loader_class.assert_called_once()
    mock_loader_instance.incremental_load.assert_called_once()


@patch("airflow.models.Variable.get")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_hotfix_mode_is_passed_to_db_manager(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_variable_get: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
    tmp_path: Path,
):
    """
    Tests that the hotfix flag is correctly passed to DatabaseConnectionManager when set in the DAG run context.
    """
    mock_variable_get.return_value = str(tmp_path)
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=True, rows_processed=50
    )
    mock_airflow_context["dag_run"].conf = {"hotfix": True}
    operator = WarehouseEtlOperator(
        task_id="test_hotfix_mode", table_execution_dict=sample_table_execution_dict
    )
    operator.execute(context=mock_airflow_context)
    mock_db_manager_class.assert_called_once_with(environment="dev", hotfix_mode=True)


@patch("airflow.models.Variable.get")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_handles_load_failure(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_variable_get: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
    tmp_path: Path,
):
    """
    Tests that the operator raises AirflowException when CopyAndLoader returns a failure result.

    Example:
        AirflowException("DB timeout")
    """
    mock_variable_get.return_value = str(tmp_path)
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=False, error_message="DB timeout"
    )
    operator = WarehouseEtlOperator(
        task_id="test_load_failure", table_execution_dict=sample_table_execution_dict
    )
    with pytest.raises(AirflowException) as excinfo:
        operator.execute(context=mock_airflow_context)
    assert "DB timeout" in str(excinfo.value)


@patch("airflow.models.Variable.get")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_missing_config_variable(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_variable_get: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
):
    """
    Tests the behavior when the Airflow Variable etl_config_root_path does not exist.
    Ensures that AirflowException is raised with a message mentioning the missing variable.
    """
    mock_variable_get.side_effect = KeyError(
        "Variable etl_config_root_path does not exist"
    )
    operator = WarehouseEtlOperator(
        task_id="test_missing_var", table_execution_dict=sample_table_execution_dict
    )
    with pytest.raises(AirflowException) as excinfo:
        operator.execute(context=mock_airflow_context)
    assert "etl_config_root_path" in str(excinfo.value)


@patch("airflow.models.Variable.get")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_sql_file_not_found(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_variable_get: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
    tmp_path: Path,
):
    """
    Tests the behavior when the SQL file specified in sql_path does not exist.
    Ensures that AirflowException is raised and the error message mentions the missing file.

    Example:
        AirflowException mentioning "nonexistent_file.sql"
    """
    mock_variable_get.return_value = str(tmp_path)
    sample_table_execution_dict["sql_path"] = "nonexistent_file.sql"
    operator = WarehouseEtlOperator(
        task_id="test_file_not_found", table_execution_dict=sample_table_execution_dict
    )
    with pytest.raises(AirflowException) as excinfo:
        operator.execute(context=mock_airflow_context)
    assert (
        "nonexistent_file.sql" in str(excinfo.value)
        or "not found" in str(excinfo.value).lower()
    )


@patch("airflow.models.Variable.get")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_with_empty_execution_context(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_variable_get: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
    tmp_path: Path,
):
    """
    Tests the operator with an empty execution_context.
    Ensures that the operator still runs and returns a successful result with zero rows processed.

    Example:
        result["status"] == "success"
        result["rows_processed"] == 0
    """
    mock_variable_get.return_value = str(tmp_path)
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=True, rows_processed=0
    )
    sample_table_execution_dict["execution_context"] = {}
    operator = WarehouseEtlOperator(
        task_id="test_empty_context", table_execution_dict=sample_table_execution_dict
    )
    result = operator.execute(context=mock_airflow_context)
    assert result["status"] == "success"
    assert result["rows_processed"] == 0

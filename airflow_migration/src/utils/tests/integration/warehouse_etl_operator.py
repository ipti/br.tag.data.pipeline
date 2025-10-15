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
    Provides a realistic, serialized TableExecution dictionary and creates its
    corresponding temporary SQL file for use in tests.
    """
    sql_file = tmp_path / "d_student.sql"
    sql_file.write_text(
        "SELECT * FROM students WHERE updated_at >= '{{ safe_timestamp }}';"
    )

    exec_obj = TableExecution(
        table_name="d_student",
        stage=1,
        database="nossasenhoradagloria_db",
        source_name="{SOURCE_NAME}",
        source_type="mysql",
        target_schema="{TARGET_SCHEMA}",
        trigger="daily",
        model="tables/d_student.yml",
        sql_path=str(sql_file.name),
        incremental_config=IncrementalConfig(
            source_timestamp_columns=["updated_at"],
            target_timestamp_column="inserted_at",
            lookback_hours=12,
        ),
        upsert_config=UpsertConfig(source_key_columns=["id"]),
        pool="default_pool",
        retries=3,
        retry_delay_minutes=5,
        execution_context={"database": "nossasenhoradagloria_db", "environment": "dev"},
    )
    return exec_obj.to_dict()


@pytest.fixture
def mock_airflow_context() -> dict:
    """Provides a mock Airflow context dictionary."""
    mock_ti = MagicMock()

    mock_ti.xcom_pull.side_effect = [
        datetime(2025, 10, 1, 12, 0, 0),  # last_timestamp
        datetime(2025, 10, 1, 14, 0, 0),  # execution_timestamp
    ]
    mock_dag_run = MagicMock()
    mock_dag_run.conf = {}
    return {"ti": mock_ti, "dag_run": mock_dag_run}


# --- Test Cases ---


@patch("plugins.operators.warehouse_etl_operator.render_sql_template")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_execute_success_flow(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_render_sql: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
):
    """
    Tests the main success path, ensuring all components are instantiated and
    called correctly with the right context.
    """
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=True, rows_processed=123
    )
    mock_render_sql.return_value = (
        "SELECT * FROM students WHERE updated_at >= '2025-10-01 00:00:00';"
    )

    operator = WarehouseEtlOperator(
        task_id="test_success_flow",
        table_execution_dict=sample_table_execution_dict,
    )

    result = operator.execute(context=mock_airflow_context)

    assert result == {"status": "success", "rows_processed": 123}
    mock_db_manager_class.assert_called_once_with(environment="dev", hotfix_mode=False)
    mock_copy_loader_class.assert_called_once()
    mock_loader_instance.incremental_load.assert_called_once()

    call_kwargs = mock_loader_instance.incremental_load.call_args.kwargs
    assert call_kwargs["source_type"] == "mysql"


@patch("plugins.operators.warehouse_etl_operator.render_sql_template")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_hotfix_mode_is_passed_correctly(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_render_sql: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
):
    """
    Tests that the 'hotfix' flag from the DAG run config is correctly
    identified and passed to the DatabaseConnectionManager.
    """
    mock_airflow_context["dag_run"].conf = {"hotfix": True}

    operator = WarehouseEtlOperator(
        task_id="test_hotfix_mode", table_execution_dict=sample_table_execution_dict
    )
    operator.execute(context=mock_airflow_context)

    mock_db_manager_class.assert_called_once_with(environment="dev", hotfix_mode=True)


@patch("plugins.operators.warehouse_etl_operator.render_sql_template")
@patch("plugins.operators.warehouse_etl_operator.CopyAndLoader")
@patch("plugins.operators.warehouse_etl_operator.DatabaseConnectionManager")
def test_operator_raises_exception_on_loader_failure(
    mock_db_manager_class: MagicMock,
    mock_copy_loader_class: MagicMock,
    mock_render_sql: MagicMock,
    sample_table_execution_dict: dict,
    mock_airflow_context: dict,
):
    """
    Tests that the operator correctly raises an AirflowException if the
    CopyAndLoader returns a failed LoadResult.
    """
    mock_loader_instance = mock_copy_loader_class.return_value
    mock_loader_instance.incremental_load.return_value = LoadResult(
        success=False, error_message="DB timeout"
    )

    operator = WarehouseEtlOperator(
        task_id="test_load_failure", table_execution_dict=sample_table_execution_dict
    )

    with pytest.raises(AirflowException):
        operator.execute(context=mock_airflow_context)

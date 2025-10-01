import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from utils.runtime.runtime_engine import resolve_placeholders, render_sql_template
from utils.planner.execution_planner import TableExecution
from utils.planner.warehouse_basic_config import IncrementalConfig, UpsertConfig


@pytest.fixture
def mock_db_manager_dev() -> MagicMock:
    """
    Returns a mock DatabaseConnectionManager for DEV environment.
    """
    mock = MagicMock()
    mock.is_production = False
    mock.hotfix_mode = False
    mock.sqlserver_config.schema = "dbo_tia_dev"
    return mock


@pytest.fixture
def mock_db_manager_prod() -> MagicMock:
    """
    Returns a mock DatabaseConnectionManager for PROD environment.
    """
    mock = MagicMock()
    mock.is_production = True
    mock.hotfix_mode = False
    mock.sqlserver_config.schema = "dbo_tia"
    return mock


@pytest.fixture
def mock_db_manager_hotfix() -> MagicMock:
    """
    Returns a mock DatabaseConnectionManager for HOTFIX mode, which should behave as PROD.
    """
    mock = MagicMock()
    mock.is_production = False
    mock.hotfix_mode = True
    mock.sqlserver_config.schema = "dbo_tia"
    return mock


@pytest.fixture
def base_table_execution(tmp_path: Path) -> TableExecution:
    """
    Creates a TableExecution object with a temporary SQL file for rendering tests.
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="dw_inserted_at",
    )
    ups_config = UpsertConfig(source_key_columns=["id"])
    sql_file = tmp_path / "test_query.sql"
    sql_file.write_text(
        "SELECT * FROM {{ database }}.source_table WHERE id = {{ context_id }};"
    )
    return TableExecution(
        table_name="d_student",
        stage=1,
        database="nossasenhoradagloria.tag.ong.br",
        source_name="{SOURCE_NAME}",
        target_schema="{TARGET_SCHEMA}",
        trigger="daily",
        model="tables/d_student.yml",
        sql_path=str(sql_file),
        incremental_config=inc_config,
        upsert_config=ups_config,
        pool="default_pool",
        retries=3,
        retry_delay_minutes=5,
        execution_context={
            "database": "nossasenhoradagloria.tag.ong.br",
            "context_id": 123,
        },
    )


def test_resolve_placeholders_in_dev_env(base_table_execution, mock_db_manager_dev):
    """
    Tests that resolve_placeholders correctly resolves DEV environment values.

    Example:
        resolved_exec.source_name == "airflow_mysql"
        resolved_exec.target_schema == "dbo_tia_dev"
    """
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_dev)
    assert resolved_exec.source_name == "airflow_mysql"
    assert resolved_exec.target_schema == "dbo_tia_dev"
    assert base_table_execution.source_name == "{SOURCE_NAME}"


def test_resolve_placeholders_in_prod_env(base_table_execution, mock_db_manager_prod):
    """
    Tests that resolve_placeholders correctly resolves PROD environment values.

    Example:
        resolved_exec.source_name == "mysql_source_1"
        resolved_exec.target_schema == "dbo_tia"
    """
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_prod)
    assert resolved_exec.source_name == "mysql_source_1"
    assert resolved_exec.target_schema == "dbo_tia"


def test_resolve_placeholders_in_hotfix_mode(
    base_table_execution, mock_db_manager_hotfix
):
    """
    Tests that hotfix mode forces resolution to PROD values.

    Example:
        resolved_exec.source_name == "mysql_source_1"
        resolved_exec.target_schema == "dbo_tia"
    """
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_hotfix)
    assert resolved_exec.source_name == "mysql_source_1"
    assert resolved_exec.target_schema == "dbo_tia"


def test_resolve_placeholders_no_placeholders_present(
    base_table_execution, mock_db_manager_dev
):
    """
    Tests that resolve_placeholders does not alter values when no placeholders are present.

    Example:
        resolved_exec.source_name == "fixed_source_name"
        resolved_exec.target_schema == "fixed_target_schema"
    """
    base_table_execution.source_name = "fixed_source_name"
    base_table_execution.target_schema = "fixed_target_schema"
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_dev)
    assert resolved_exec.source_name == "fixed_source_name"
    assert resolved_exec.target_schema == "fixed_target_schema"


@patch("airflow.models.Variable.get")
def test_render_sql_template_success_and_quoting(
    mock_variable_get, base_table_execution, tmp_path
):
    """
    Tests that render_sql_template correctly renders the SQL template and quotes the database name.

    Example:
        final_sql == "SELECT * FROM `nossasenhoradagloria.tag.ong.br`.source_table WHERE id = 123;"
    """
    mock_variable_get.return_value = str(tmp_path.parent)
    final_sql = render_sql_template(base_table_execution)
    expected_sql = (
        "SELECT * FROM `nossasenhoradagloria.tag.ong.br`.source_table WHERE id = 123;"
    )
    assert final_sql == expected_sql


@patch("airflow.models.Variable.get")
def test_render_sql_template_no_database_in_context(
    mock_variable_get, base_table_execution, tmp_path
):
    """
    Tests rendering when the 'database' key is missing from the execution context.

    Example:
        final_sql == "SELECT 1;"
    """
    mock_variable_get.return_value = str(tmp_path.parent)
    del base_table_execution.execution_context["database"]
    Path(base_table_execution.sql_path).write_text("SELECT 1;")
    final_sql = render_sql_template(base_table_execution)
    assert final_sql == "SELECT 1;"


@patch("airflow.models.Variable.get")
def test_render_sql_template_file_not_found(
    mock_variable_get, base_table_execution, tmp_path
):
    """
    Tests that FileNotFoundError is raised if the SQL file does not exist.

    Example:
        FileNotFoundError is raised when sql_path is invalid.
    """
    mock_variable_get.return_value = str(tmp_path)
    base_table_execution.sql_path = "non_existent_file.sql"
    with pytest.raises(FileNotFoundError):
        render_sql_template(base_table_execution)


@patch("airflow.models.Variable.get")
def test_render_sql_template_with_special_characters_in_database(
    mock_variable_get, base_table_execution, tmp_path
):
    """
    Tests that database names with special characters are properly quoted.

    Example:
        final_sql contains "`database-with-dashes.example.com`"
    """
    mock_variable_get.return_value = str(tmp_path.parent)
    base_table_execution.execution_context["database"] = (
        "database-with-dashes.example.com"
    )
    Path(base_table_execution.sql_path).write_text(
        "SELECT * FROM {{ database }}.table;"
    )
    final_sql = render_sql_template(base_table_execution)
    assert "`database-with-dashes.example.com`" in final_sql


@patch("airflow.models.Variable.get")
def test_render_sql_template_multiple_context_variables(
    mock_variable_get, base_table_execution, tmp_path
):
    """
    Tests rendering with multiple context variables.

    Example:
        final_sql contains "students", "123", and "100"
    """
    mock_variable_get.return_value = str(tmp_path.parent)
    base_table_execution.execution_context["table_name"] = "students"
    base_table_execution.execution_context["limit"] = 100
    Path(base_table_execution.sql_path).write_text(
        "SELECT * FROM {{ database }}.{{ table_name }} WHERE id = {{ context_id }} LIMIT {{ limit }};"
    )
    final_sql = render_sql_template(base_table_execution)
    assert "students" in final_sql
    assert "123" in final_sql
    assert "100" in final_sql


def test_resolve_placeholders_preserves_other_attributes(
    base_table_execution, mock_db_manager_dev
):
    """
    Tests that resolve_placeholders preserves all other attributes of TableExecution.
    """
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_dev)
    assert resolved_exec.table_name == base_table_execution.table_name
    assert resolved_exec.stage == base_table_execution.stage
    assert resolved_exec.database == base_table_execution.database
    assert resolved_exec.trigger == base_table_execution.trigger
    assert resolved_exec.model == base_table_execution.model
    assert resolved_exec.sql_path == base_table_execution.sql_path
    assert resolved_exec.pool == base_table_execution.pool
    assert resolved_exec.retries == base_table_execution.retries
    assert resolved_exec.retry_delay_minutes == base_table_execution.retry_delay_minutes


def test_resolve_placeholders_creates_new_instance(
    base_table_execution, mock_db_manager_dev
):
    """
    Tests that resolve_placeholders returns a new instance and doesn't modify the original.

    Example:
        resolved_exec is not base_table_execution
        resolved_exec.source_name != base_table_execution.source_name
    """
    original_source = base_table_execution.source_name
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_dev)
    assert base_table_execution.source_name == original_source
    assert resolved_exec.source_name != original_source
    assert resolved_exec is not base_table_execution

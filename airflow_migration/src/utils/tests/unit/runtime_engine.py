import pytest
from pathlib import Path
from unittest.mock import MagicMock

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
    inc_config = IncrementalConfig(source_timestamp_columns=["updated_at"], target_timestamp_column="dw_inserted_at")
    ups_config = UpsertConfig(source_key_columns=["id"])
    sql_file = tmp_path / "test_query.sql"
    sql_file.write_text("SELECT * FROM {{ database }}.source_table WHERE id = {{ context_id }};")
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
        execution_context={
            "database": "nossasenhoradagloria.tag.ong.br",
            "context_id": 123
        }
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

def test_resolve_placeholders_in_hotfix_mode(base_table_execution, mock_db_manager_hotfix):
    """
    Tests that hotfix mode forces resolution to PROD values.

    Example:
        resolved_exec.source_name == "mysql_source_1"
        resolved_exec.target_schema == "dbo_tia"
    """
    resolved_exec = resolve_placeholders(base_table_execution, mock_db_manager_hotfix)
    assert resolved_exec.source_name == "mysql_source_1"
    assert resolved_exec.target_schema == "dbo_tia"

def test_resolve_placeholders_no_placeholders_present(base_table_execution, mock_db_manager_dev):
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

def test_render_sql_template_success_and_quoting(base_table_execution):
    """
    Tests that render_sql_template correctly renders the SQL template and quotes the database name.

    Example:
        final_sql == "SELECT * FROM `nossasenhoradagloria.tag.ong.br`.source_table WHERE id = 123;"
    """
    final_sql = render_sql_template(base_table_execution)
    expected_sql = "SELECT * FROM `nossasenhoradagloria.tag.ong.br`.source_table WHERE id = 123;"
    assert final_sql == expected_sql

def test_render_sql_template_no_database_in_context(base_table_execution):
    """
    Tests rendering when the 'database' key is missing from the execution context.

    Example:
        final_sql == "SELECT 1;"
    """
    del base_table_execution.execution_context['database']
    Path(base_table_execution.sql_path).write_text("SELECT 1;")
    final_sql = render_sql_template(base_table_execution)
    assert final_sql == "SELECT 1;"

def test_render_sql_template_file_not_found(base_table_execution):
    """
    Tests that FileNotFoundError is raised if the SQL file does not exist.

    Example:
        FileNotFoundError is raised when sql_path is invalid.
    """
    base_table_execution.sql_path = "/a/b/c/non_existent_file.sql"
    with pytest.raises(FileNotFoundError):
        render_sql_template(base_table_execution)
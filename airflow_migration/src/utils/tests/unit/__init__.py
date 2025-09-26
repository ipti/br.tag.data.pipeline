import pytest
from pathlib import Path
from unittest.mock import MagicMock

# Importe as classes e funções a serem testadas
from airflow_migration.src.utils.runtime.runtime_engine import (
    resolve_placeholders,
    render_sql_template,
)
from airflow_migration.src.utils.planner.execution_planner import TableExecution
from airflow_migration.src.utils.planner.warehouse_basic_config import (
    IncrementalConfig,
    UpsertConfig,
)

# --- Fixtures para dados de teste ---


@pytest.fixture
def mock_db_manager_dev():
    """Cria um mock do db_manager para um ambiente de DEV."""
    mock = MagicMock()
    mock.is_production = False
    mock.hotfix_mode = False
    mock.sqlserver_config.schema = "dbo_tia_dev"
    return mock


@pytest.fixture
def mock_db_manager_prod():
    """Cria um mock do db_manager para um ambiente de PROD."""
    mock = MagicMock()
    mock.is_production = True
    mock.hotfix_mode = False
    mock.sqlserver_config.schema = "dbo_tia"
    return mock


@pytest.fixture
def sample_table_execution() -> TableExecution:
    """Cria um objeto TableExecution de exemplo com placeholders."""
    # Simula objetos de configuração aninhados
    inc_config = IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="dw_inserted_at",
    )
    ups_config = UpsertConfig(source_key_columns=["id"])

    return TableExecution(
        table_name="d_student",
        stage=1,
        database="my_test_db",
        source_name="{SOURCE_NAME}",
        target_schema="{TARGET_SCHEMA}",
        trigger="daily",
        model="tables/d_student.yml",
        sql_path="/fake/path.sql",  # Será substituído nos testes que precisam
        incremental_config=inc_config,
        upsert_config=ups_config,
        execution_context={
            "database": "my_test_db",
            "target_schema": "{TARGET_SCHEMA}",
        },
    )


# --- Testes para resolve_placeholders ---


def test_resolve_placeholders_dev_environment(
    sample_table_execution, mock_db_manager_dev
):
    """Testa se os placeholders são resolvidos corretamente para o ambiente de DEV."""
    # Act
    resolved_exec = resolve_placeholders(sample_table_execution, mock_db_manager_dev)

    # Assert
    assert resolved_exec.source_name == "airflow_mysql"
    assert resolved_exec.target_schema == "dbo_tia_dev"
    # Garante que o objeto original não foi modificado
    assert sample_table_execution.source_name == "{SOURCE_NAME}"


def test_resolve_placeholders_prod_environment(
    sample_table_execution, mock_db_manager_prod
):
    """Testa se os placeholders são resolvidos corretamente para o ambiente de PROD."""
    # Act
    resolved_exec = resolve_placeholders(sample_table_execution, mock_db_manager_prod)

    # Assert
    assert resolved_exec.source_name == "mysql_source_1"
    assert resolved_exec.target_schema == "dbo_tia"


# --- Testes para render_sql_template ---


def test_render_sql_template_success(sample_table_execution, tmp_path: Path):
    """Testa se a renderização de um template SQL com Jinja funciona."""
    # Arrange
    sql_content = "SELECT * FROM {{ database }}.students WHERE year = 2025;"
    sql_file = tmp_path / "d_student.sql"
    sql_file.write_text(sql_content)

    # Atualiza o objeto de execução com o caminho do arquivo temporário
    sample_table_execution.sql_path = str(sql_file)

    # Act
    final_sql = render_sql_template(sample_table_execution)

    # Assert
    expected_sql = "SELECT * FROM my_test_db.students WHERE year = 2025;"
    assert final_sql == expected_sql


def test_render_sql_template_file_not_found(sample_table_execution):
    """Testa se uma exceção é levantada quando o arquivo SQL não existe."""
    # Arrange
    sample_table_execution.sql_path = "/non_existent_path/fake.sql"

    # Act & Assert
    with pytest.raises(FileNotFoundError):
        render_sql_template(sample_table_execution)

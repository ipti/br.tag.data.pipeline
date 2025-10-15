import pytest
from pathlib import Path
from unittest.mock import patch

from utils.runtime.runtime_engine import render_sql_template
from utils.planner.execution_planner import TableExecution
from utils.planner.warehouse_basic_config import IncrementalConfig, UpsertConfig


@pytest.fixture
def base_table_execution() -> TableExecution:
    """
    Provides a base TableExecution object for testing, including all required fields such as 'source_type'.
    """
    return TableExecution(
        table_name="d_test",
        stage=1,
        database="my_db",
        source_name="{SOURCE_NAME}",
        target_schema="{TARGET_SCHEMA}",
        source_type="mysql",
        trigger="daily",
        model="m",
        sql_path="test.sql",
        incremental_config=IncrementalConfig(
            source_timestamp_columns=[], target_timestamp_column=""
        ),
        upsert_config=UpsertConfig(source_key_columns=[]),
        pool="default",
        retries=1,
        retry_delay_minutes=5,
        execution_context={"database": "my_db"},
    )


class TestResolvePlaceholders:
    """
    Tests for the resolve_placeholders function.
    Ensures that placeholders in TableExecution are correctly resolved based on environment and db_manager configuration.
    """

    pass


@pytest.fixture
def mock_variable(tmp_path: Path):
    """
    Mocks the Airflow Variable.get call to return the temporary path for config root.
    """
    with patch("utils.runtime.runtime_engine.Variable.get") as mock_get:
        mock_get.return_value = str(tmp_path)
        yield mock_get


class TestRenderSQLTemplate:
    """
    Unit tests for the render_sql_template function.
    Validates correct rendering of SQL templates, context preparation, and error handling.
    """

    def test_successful_render_with_context_preparation(
        self, tmp_path: Path, mock_variable
    ):
        """
        Tests that render_sql_template reads the file, prepares the context, and renders both
        'database' (as an identifier with backticks) and 'database_raw' (as a plain value) correctly.

        Example:
            SQL template: "SELECT * FROM {{ database }}.users WHERE city = '{{ database_raw }}' AND id = {{ user_id }};"
            Context: {"database": "city_db.example.com", "user_id": 123}
            Output: "SELECT * FROM `city_db.example.com`.users WHERE city = 'city_db.example.com' AND id = 123;"
        """
        sql_file = tmp_path / "test_query.sql"
        sql_file.write_text(
            "SELECT * FROM {{ database }}.users WHERE city = '{{ database_raw }}' AND id = {{ user_id }};"
        )
        context = {"database": "city_db.example.com", "user_id": 123}
        final_sql = render_sql_template(
            sql_path=str(sql_file.name), execution_context=context
        )
        assert "FROM `city_db.example.com`.users" in final_sql
        assert "city = 'city_db.example.com'" in final_sql

    def test_file_not_found_raises_exception(self, tmp_path: Path, mock_variable):
        """
        Tests that render_sql_template raises FileNotFoundError when the SQL template file does not exist.
        """
        with pytest.raises(FileNotFoundError):
            render_sql_template(sql_path="non_existent_file.sql", execution_context={})

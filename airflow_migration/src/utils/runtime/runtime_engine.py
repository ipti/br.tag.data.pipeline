# src/utils/runtime/runtime_engine.py

from jinja2 import Template
from pathlib import Path
import copy

from src.utils.connections.connection_manager import DatabaseConnectionManager
from src.utils.planner.execution_planner import TableExecution


def resolve_placeholders(
    table_execution: TableExecution, db_manager: DatabaseConnectionManager
) -> TableExecution:
    """
    Resolves the placeholders {SOURCE_NAME} and {TARGET_SCHEMA} in a TableExecution object
    using the provided DatabaseConnectionManager configuration.

    This function creates a deep copy of the input TableExecution to avoid mutating the original object.
    The environment is determined based on db_manager's production or hotfix mode.
    The placeholders are replaced with appropriate values for source_name and target_schema.

    Args:
        table_execution (TableExecution): The TableExecution object with possible placeholders.
        db_manager (DatabaseConnectionManager): The database manager containing environment and schema info.

    Returns:
        TableExecution: A new TableExecution object with resolved placeholders.

    Example:
        >>> exec = TableExecution(source_name="{SOURCE_NAME}", target_schema="{TARGET_SCHEMA}", ...)
        >>> resolved = resolve_placeholders(exec, db_manager)
        >>> print(resolved.source_name)
        'mysql_source_1'
        >>> print(resolved.target_schema)
        'prod_schema'
    """
    resolved_execution = copy.deepcopy(table_execution)
    environment = (
        "prod" if db_manager.is_production or db_manager.hotfix_mode else "dev"
    )
    if resolved_execution.source_name == "{SOURCE_NAME}":
        resolved_execution.source_name = (
            "mysql_source_1" if environment == "prod" else "airflow_mysql"
        )
    if resolved_execution.target_schema == "{TARGET_SCHEMA}":
        resolved_execution.target_schema = db_manager.sqlserver_config.schema
    return resolved_execution


def render_sql_template(resolved_execution: TableExecution) -> str:
    """
    Renders a SQL file using Jinja2 templating, filling placeholders with the execution context.

    The SQL file path is read from resolved_execution.sql_path. The file is rendered with the
    execution_context dictionary from the TableExecution object, which should contain all variables
    required by the template.

    Args:
        resolved_execution (TableExecution): The TableExecution object with execution_context and sql_path.

    Returns:
        str: The rendered SQL string.

    Raises:
        FileNotFoundError: If the SQL file does not exist.

    Example:
        >>> resolved_execution.sql_path = "/path/to/query.sql"
        >>> resolved_execution.execution_context = {"database": "db1", "table": "users"}
        >>> sql = render_sql_template(resolved_execution)
        >>> print(sql)
        "SELECT * FROM db1.users;"
    """
    sql_path = Path(resolved_execution.sql_path)
    if not sql_path.exists():
        raise FileNotFoundError(f"SQL file not found at: {sql_path}")

    sql_template_content = sql_path.read_text()
    template = Template(sql_template_content)
    render_context = resolved_execution.execution_context.copy()

    if "database" in render_context and render_context["database"]:
        render_context["database"] = f"`{render_context['database']}`"

    final_sql = template.render(render_context)

    return final_sql

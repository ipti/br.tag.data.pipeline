# src/utils/runtime/runtime_engine.py

from jinja2 import Template
from pathlib import Path
import copy
from airflow.sdk import Variable
from typing import Dict, Any


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


def render_sql_template(sql_path: str, execution_context: Dict[str, Any]) -> str:
    """
    Renders a SQL file using Jinja2 by accepting a direct path and context.

    This utility function is responsible for all templating logic. It fetches
    the base configuration path from an Airflow Variable, constructs the full
    path to the SQL file, and reads its content. It then enriches the provided
    execution context by preparing different versions of the 'database' variable
    (raw and quoted) for flexible use within the template, before finally
    rendering and returning the final SQL string.

    Args:
        sql_path (str): The relative path to the SQL template file from the
            configuration root.
        execution_context (Dict[str, Any]): A dictionary of variables to be made
            available to the Jinja2 template.

    Returns:
        str: The rendered SQL string.

    Raises:
        FileNotFoundError: If the SQL file does not exist at the resolved path.
    """
    config_root = Variable.get("etl_config_root_path")
    full_sql_path = Path(config_root) / sql_path

    if not full_sql_path.exists():
        raise FileNotFoundError(f"SQL file not found at: {full_sql_path}")

    sql_template_content = full_sql_path.read_text()
    template = Template(sql_template_content)

    render_context = execution_context.copy()

    if "database" in render_context and render_context["database"]:
        db_name_raw = render_context["database"]
        render_context["database_raw"] = db_name_raw
        render_context["database"] = f"`{db_name_raw}`"

    final_sql = template.render(render_context)

    return final_sql

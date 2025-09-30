from typing import Any, Dict
from airflow.models import BaseOperator
from airflow.utils.context import Context
from airflow.exceptions import AirflowException

from src.utils.connections.connection_manager import DatabaseConnectionManager
from src.utils.connections.writer import CopyAndLoader
from src.utils.planner.execution_planner import TableExecution
from src.utils.runtime.runtime_engine import resolve_placeholders, render_sql_template


class WarehouseEtlOperator(BaseOperator):
    """
    Executes a single table load task based on a TableExecution object.

    This operator is the primary execution engine for the dynamic ETL framework.
    It deserializes a table execution configuration, resolves placeholders,
    renders the final SQL, and uses the CopyAndLoader to perform the

    incremental load operation against the source and target databases.
    """

    def __init__(
        self,
        table_execution_dict: Dict[str, Any],
        **kwargs,
    ):
        """
        Initializes the WarehouseEtlOperator.

        Args:
            table_execution_dict (Dict[str, Any]): A dictionary representation of a
                TableExecution object, which contains all necessary configuration
                for a single ETL task.
            **kwargs: Additional arguments inherited from BaseOperator (e.g., task_id,
                retries, pool).
        """
        super().__init__(**kwargs)
        self.table_execution_dict = table_execution_dict

    def execute(self, context: Context) -> Dict[str, Any]:
        """
        Executes the ETL task.

        This method is called by the Airflow worker at runtime. It orchestrates
        the entire process of deserialization, placeholder resolution, SQL rendering,
        and data loading.
        """
        try:
            table_execution = TableExecution.from_dict(self.table_execution_dict)
            self.log.info(
                f"Successfully deserialized execution for table: {table_execution.table_name}"
            )
        except Exception as e:
            self.log.error(f"Failed to deserialize TableExecution object: {e}")
            raise AirflowException(f"Deserialization failed: {e}")

        environment = table_execution.execution_context.get("environment", "dev")

        dag_run = context.get("dag_run")
        hotfix_mode = (
            dag_run.conf.get("hotfix", False) if dag_run and dag_run.conf else False
        )

        self.log.info(
            f"Initializing connection manager. Environment: {environment}, Hotfix mode: {hotfix_mode}"
        )

        db_manager = DatabaseConnectionManager(
            environment=environment, hotfix_mode=hotfix_mode
        )
        copy_loader = CopyAndLoader(db_manager=db_manager)

        try:
            resolved_execution = resolve_placeholders(table_execution, db_manager)
            final_sql = render_sql_template(resolved_execution)

            self.log.info(
                f"SQL template rendered for {resolved_execution.table_name} "
                f"on database {resolved_execution.database}"
            )
            self.log.debug(f"SQL Preview: {final_sql[:500]}...")

            result = copy_loader.incremental_load(
                source_name=resolved_execution.source_name,
                target_table=resolved_execution.table_name,
                source_database=resolved_execution.database,
                target_schema=resolved_execution.target_schema,
                incremental_config=resolved_execution.incremental_config,
                upsert_config=resolved_execution.upsert_config,
                source_query=final_sql,
            )

            if not result.success:
                raise AirflowException(
                    f"Load operation failed for table {resolved_execution.table_name}. "
                    f"Error: {result.error_message}"
                )

            self.log.info(
                f"Successfully loaded table {resolved_execution.table_name}. "
                f"Rows processed: {result.rows_processed}"
            )

            return {"status": "success", "rows_processed": result.rows_processed}

        except Exception as e:
            self.log.error(
                f"An unexpected error occurred during execution for table {table_execution.table_name}: {e}"
            )
            raise AirflowException(f"Task failed unexpectedly: {e}")

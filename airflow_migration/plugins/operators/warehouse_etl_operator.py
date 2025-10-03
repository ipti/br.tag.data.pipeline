from typing import Any, Dict
from airflow.models import BaseOperator
from airflow.utils.context import Context
from airflow.exceptions import AirflowException
from datetime import timedelta
from pendulum import datetime


from src.utils.connections.connection_manager import DatabaseConnectionManager
from src.utils.connections.writer import CopyAndLoader
from src.utils.planner.execution_planner import TableExecution
from src.utils.runtime.runtime_engine import resolve_placeholders, render_sql_template


class WarehouseEtlOperator(BaseOperator):
    """
    Executes a single, configured ETL task for the dynamic warehouse framework.

    This operator acts as the runtime engine for a `TableExecution` object.
    It is responsible for orchestrating the entire lifecycle of a task, including
    deserializing its configuration, determining the runtime context (like
    hotfix mode), fetching the incremental timestamp from XComs, rendering the
    final SQL query, and invoking the data loader (`CopyAndLoader`).
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
                for a single ETL task. This is passed by the DagGenerator.
            **kwargs: Additional arguments inherited from BaseOperator (e.g., task_id,
                retries, pool, retry_delay).
        """
        super().__init__(**kwargs)
        self.table_execution_dict = table_execution_dict

    def execute(self, context: Context) -> Dict[str, Any]:
        """
        Executes the ETL task by orchestrating the entire process.

        This method is called by the Airflow worker at runtime. Its main
        responsibilities are:
        1. Deserializing the task's configuration from the input dictionary.
        2. Determining the runtime environment and hotfix mode from the context.
        3. Instantiating service classes (DBManager, CopyAndLoader).
        4. Retrieving the initial `last_timestamp` and `execution_timestamp`
        from an upstream XCom push.
        5. Calculating the `safe_timestamp` for the incremental query.
        6. Enriching the Jinja2 rendering context with all dynamic timestamps.
        7. Calling the `render_sql_template` function to generate the final SQL.
        8. Invoking the `CopyAndLoader` to execute the load operation.
        9. Handling and logging the final result.

        Args:
            context (Context): The Airflow task context, which includes the
                task instance (`ti`) for XCom access and the `dag_run` object.

        Raises:
            AirflowException: If any step of the process fails.

        Returns:
            Dict[str, Any]: A dictionary containing metadata about the execution.
        """
        try:
            table_execution = TableExecution.from_dict(self.table_execution_dict)
            self.log.info(
                f"Successfully deserialized execution for table: {table_execution.table_name}"
            )
        except Exception as e:
            raise AirflowException(f"Deserialization failed: {e}")

        dag_run = context.get("dag_run")
        hotfix_mode = (
            dag_run.conf.get("hotfix", False) if dag_run and dag_run.conf else False
        )
        environment = table_execution.execution_context.get("environment", "dev")

        self.log.info(
            f"Initializing connection manager. Environment: {environment}, Hotfix mode: {hotfix_mode}"
        )
        db_manager = DatabaseConnectionManager(
            environment=environment, hotfix_mode=hotfix_mode
        )
        copy_loader = CopyAndLoader(db_manager=db_manager)

        try:
            ti = context["ti"]
            inc_config = table_execution.incremental_config

            last_timestamp = ti.xcom_pull(
                task_ids="get_initial_timestamps", key="last_timestamp"
            )
            execution_timestamp = ti.xcom_pull(
                task_ids="get_initial_timestamps", key="execution_timestamp"
            )

            if not execution_timestamp:
                self.log.warning(
                    "Could not pull execution_timestamp from XComs, using fallback."
                )

                execution_timestamp = datetime.now("UTC")

            safe_timestamp = None

            if inc_config.full_refresh or not last_timestamp:
                safe_timestamp = datetime(1900, 1, 1)
                last_timestamp = datetime(1900, 1, 1)
            else:
                safe_timestamp = last_timestamp - timedelta(
                    hours=inc_config.lookback_hours
                )

            self.log.info(
                f"Timestamps for query: "
                f"last_timestamp='{last_timestamp}', safe_timestamp='{safe_timestamp}', "
                f"execution_timestamp='{execution_timestamp}'"
            )

            resolved_execution = resolve_placeholders(table_execution, db_manager)

            render_context = resolved_execution.execution_context
            render_context["last_timestamp"] = (
                last_timestamp.strftime("%Y-%m-%d %H:%M:%S") if last_timestamp else None
            )
            render_context["safe_timestamp"] = safe_timestamp.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            render_context["execution_timestamp"] = execution_timestamp.strftime(
                "%Y-%m-%d %H:%M:%S"
            )

            final_sql = render_sql_template(resolved_execution)

            self.log.info(
                f"SQL template rendered for {resolved_execution.table_name} "
                f"on database {resolved_execution.database}"
            )
            self.log.debug(f"SQL Preview: {final_sql[:500]}...")

            result = copy_loader.incremental_load(
                source_name=resolved_execution.source_name,
                target_table=resolved_execution.table_name,
                incremental_config=resolved_execution.incremental_config,
                source_query=final_sql,
                source_database=resolved_execution.database,
                target_schema=resolved_execution.target_schema,
                upsert_config=resolved_execution.upsert_config,
                quality_check_pipeline=resolved_execution.quality_check_pipeline,
                quality_check_params=resolved_execution.quality_check_params,
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
            self.log.exception(
                f"An unexpected error occurred during execution for table {table_execution.table_name}"
            )
            raise AirflowException(f"Task failed unexpectedly: {e}")

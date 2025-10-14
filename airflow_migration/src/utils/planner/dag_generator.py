"""
Generates dynamic Airflow DAG Python files from a structured execution plan.
"""

from pathlib import Path
from typing import Any, Dict, List
from collections import defaultdict
from datetime import datetime, timedelta

from utils.logs.logging_functions import get_logger
from utils.planner.execution_planner import TableExecution
from utils.planner.warehouse_basic_config import WorkflowConfig, TriggerConfig


class DagGenerator:
    """
    Generates dynamic Airflow DAG Python files based on a validated execution plan.

    This class reads a structured execution plan and a workflow configuration
    to produce one or more DAG files. Each file corresponds to a unique trigger
    and environment. It contains the necessary Airflow code, including TaskGroups,
    a setup task for incremental loads, instances of the custom
    WarehouseEtlOperator, and an optional final task to trigger a downstream DAG.
    """

    def __init__(self, output_path: str):
        """
        Initializes the DagGenerator.

        Args:
            output_path (str): The directory path where the generated DAG files
                will be saved.
        """
        self.output_path = Path(output_path)
        self.logger = get_logger("dag_generator")
        self.output_path.mkdir(parents=True, exist_ok=True)

    def generate_dags(
        self,
        execution_plan: List[List[TableExecution]],
        workflow_config: WorkflowConfig,
        environment: str,
        is_paused: bool = False,
    ):
        """
        Main method to generate all DAG files for a specific environment.

        It groups executions by their trigger and then generates a separate,
        environment-specific DAG file for each trigger.

        Args:
            execution_plan (List[List[TableExecution]]): The structured, batched
                plan from the ExecutionPlanner.
            workflow_config (WorkflowConfig): The main workflow configuration.
            environment (str): The target environment (e.g., 'dev', 'prod').
            is_paused (bool): If True, the generated DAG will be paused upon
                creation in Airflow.
        """
        self.logger.info(
            f"Starting DAG generation for environment: {environment.upper()}"
        )
        grouped_executions = self._group_plan_by_trigger(execution_plan)

        for trigger_name, batches in grouped_executions.items():
            try:
                trigger_config = workflow_config.triggers.get(trigger_name)
                if not trigger_config:
                    self.logger.warning(
                        f"Trigger '{trigger_name}' found in plan but not in workflow "
                        f"triggers config. Skipping.",
                        {"trigger_name": trigger_name},
                    )
                    continue

                self.logger.info(
                    f"Generating DAG file for trigger: '{trigger_name}'..."
                )

                file_content = self._generate_dag_file_content(
                    trigger_name,
                    trigger_config,
                    batches,
                    workflow_config,
                    environment,
                    is_paused,
                )

                file_name = f"dag__{workflow_config.workflow_name.lower()}__{trigger_name}__{environment}.py"
                file_path = self.output_path / file_name

                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(file_content)

                self.logger.info(f"Successfully generated DAG file: {file_path}")

            except Exception as e:
                self.logger.error(
                    f"Failed to generate DAG for trigger '{trigger_name}'. Original error: {e}",
                    extra_data={"trigger_name": trigger_name},
                )
                raise

    def _group_plan_by_trigger(
        self, execution_plan: List[List[TableExecution]]
    ) -> Dict[str, List[List[TableExecution]]]:
        """Groups the execution plan's batches by their trigger."""
        grouped = defaultdict(list)
        for batch in execution_plan:
            if not batch:
                continue
            trigger = batch[0].trigger
            grouped[trigger].append(batch)
        return grouped

    def _generate_dag_file_content(
        self,
        trigger_name: str,
        trigger_config: TriggerConfig,
        batches: List[List[TableExecution]],
        workflow_config: WorkflowConfig,
        environment: str,
        is_paused: bool,
    ) -> str:
        """
        Generates the full Python source code for a single, timezone-aware DAG file.
        """
        dag_id = (
            f"{workflow_config.workflow_name.lower()}__{trigger_name}__{environment}"
        )

        reference_table_name = trigger_config.incremental_reference_table
        reference_execution = None

        if reference_table_name:
            self.logger.info(
                f"Using '{reference_table_name}' as the explicit reference for initial timestamp."
            )
            for batch in batches:
                for execution in batch:
                    if execution.table_name == reference_table_name:
                        reference_execution = execution
                        break
                if reference_execution:
                    break

        if not reference_execution and batches:
            reference_execution = batches[-1][-1]
            self.logger.info(
                f"No explicit reference table set for trigger '{trigger_name}'. "
                f"Using last table in plan as default: '{reference_execution.table_name}'"
            )

        target_table_for_ts = (
            reference_execution.table_name if reference_execution else ""
        )
        target_schema_placeholder_for_ts = (
            reference_execution.target_schema if reference_execution else ""
        )
        timestamp_column_for_ts = (
            reference_execution.incremental_config.target_timestamp_column
            if reference_execution
            else ""
        )

        header = f'''"""
# AUTOGENERATED FILE - DO NOT EDIT MANUALLY
# Generated by DagGenerator on {datetime.now().isoformat()}
# For environment: {environment.upper()}
"""
import pendulum
from datetime import timedelta
from airflow.models.dag import DAG
from airflow.models.dagrun import DagRun
from airflow.utils.task_group import TaskGroup
from airflow.operators.python import PythonOperator
from airflow.operators.trigger_dagrun import TriggerDagRunOperator

from utils.connections.connection_manager import DatabaseConnectionManager
from utils.connections.writer import CopyAndLoader
from plugins.operators.warehouse_etl_operator import WarehouseEtlOperator

'''

        python_callable_str = """
def get_and_push_timestamps(ti, dag_run, target_table, target_schema_placeholder, timestamp_column, env):
    \"\"\"
    Captures the current execution time in UTC, queries for the max
    timestamp, and pushes both to XComs for downstream tasks.
    \"\"\"
    execution_ts = pendulum.now('UTC')
    hotfix_mode = dag_run.conf.get("hotfix", False) if dag_run and dag_run.conf else False
    
    db_manager = DatabaseConnectionManager(environment=env, hotfix_mode=hotfix_mode)
    target_schema = (
        db_manager.sqlserver_config.schema
        if target_schema_placeholder == "{TARGET_SCHEMA}"
        else target_schema_placeholder
    )
    loader = CopyAndLoader(db_manager=db_manager)
    last_ts = loader._get_last_timestamp(target_table, timestamp_column, target_schema)
    
    ti.xcom_push(key='last_timestamp', value=last_ts)
    ti.xcom_push(key='execution_timestamp', value=execution_ts)
    print(f"Pushed to XComs: last_timestamp={{last_ts}}, execution_timestamp={{execution_ts}}")

"""

        dag_definition = f'''
{python_callable_str}
with DAG(
    dag_id="{dag_id}",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    schedule="{trigger_config.schedule_interval}",
    catchup=False,
    is_paused_upon_creation={is_paused},
    tags=["warehouse", "autogenerated", "{trigger_name}", "{environment}"],
    doc_md="""{trigger_config.description}"""
) as dag:
'''

        setup_task_code = (
            f"""
    get_initial_timestamps = PythonOperator(
        task_id="get_initial_timestamps",
        python_callable=get_and_push_timestamps,
        op_kwargs={{
            "target_table": "{target_table_for_ts}",
            "target_schema_placeholder": "{target_schema_placeholder_for_ts}",
            "timestamp_column": "{timestamp_column_for_ts}",
            "env": "{environment}"
        }}
    )
"""
            if batches
            else ""
        )

        task_groups_code = []
        task_group_vars = []

        for i, batch in enumerate(batches):
            stage_num = batch[0].stage
            tg_var = f"tg_{i + 1}"
            task_group_vars.append(tg_var)

            tg_header = f"""
    with TaskGroup(group_id="Batch_{i + 1}_Stage_{stage_num}") as {tg_var}:"""

            tasks_code = []
            for execution in batch:
                task_id = (
                    f"{execution.table_name}__{execution.database.replace('.', '_')}"
                )
                task_variable_name = task_id.replace("-", "_")

                task_code = f"""
        {task_variable_name} = WarehouseEtlOperator(
            task_id="{task_id}",
            table_execution_dict={repr(execution.to_dict())},
            pool="{execution.pool or 'default_pool'}",
            retries={execution.retries},
            retry_delay=timedelta(minutes={execution.retry_delay_minutes})
        )"""
                tasks_code.append(task_code)

            task_groups_code.append(tg_header + "".join(tasks_code))

        trigger_task_code = ""
        dependencies_code = ""
        last_task_in_chain = "get_initial_timestamps" if batches else ""

        if task_group_vars:
            dependencies_code = "\n    (\n        get_initial_timestamps"
            for tg_var in task_group_vars:
                dependencies_code += f"\n        >> {tg_var}"
            dependencies_code += "\n    )"
            last_task_in_chain = task_group_vars[-1]

        if trigger_config.trigger_dag_on_success:
            triggered_dag_id = trigger_config.trigger_dag_on_success
            sanitized_task_var = (
                f"trigger_{triggered_dag_id.replace('-', '_').replace('.', '_')}"
            )
            trigger_task_code = f"""
    {sanitized_task_var} = TriggerDagRunOperator(
        task_id="trigger_{triggered_dag_id}",
        trigger_dag_id="{triggered_dag_id}",
        wait_for_completion=False,
    )
"""
            if last_task_in_chain:
                dependencies_code += f"\n    (\n        {last_task_in_chain}\n        >> {sanitized_task_var}\n    )"

        return (
            header
            + dag_definition
            + setup_task_code
            + "".join(task_groups_code)
            + trigger_task_code
            + dependencies_code
        )

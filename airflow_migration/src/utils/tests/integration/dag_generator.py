import pytest
from pathlib import Path

from utils.planner.dag_generator import DagGenerator
from utils.planner.execution_planner import TableExecution
from utils.planner.warehouse_basic_config import (
    WorkflowConfig,
    Stage,
    IncrementalConfig,
    UpsertConfig,
    TriggerConfig,
)


@pytest.fixture
def sample_execution_plan() -> list:
    """
    Provides a standard, multi-stage execution plan for DAG generation tests.
    Returns a list of batches, each containing TableExecution objects for different stages and databases.
    """
    inc_config = IncrementalConfig(
        source_timestamp_columns=["ts"], target_timestamp_column="dw_ts"
    )
    ups_config = UpsertConfig(source_key_columns=["id"])
    exec_A = TableExecution(
        table_name="table_A",
        stage=1,
        database="db1",
        source_name="src",
        source_type="mysql",
        target_schema="tgt",
        trigger="daily_run",
        model="m",
        sql_path="/fake/A.sql",
        incremental_config=inc_config,
        upsert_config=ups_config,
        pool="pool_A",
        retries=3,
        retry_delay_minutes=10,
    )
    exec_B = TableExecution(
        table_name="table_B",
        stage=2,
        database="db1",
        source_name="src",
        source_type="mysql",
        target_schema="tgt",
        trigger="daily_run",
        model="m",
        sql_path="/fake/B.sql",
        incremental_config=inc_config,
        upsert_config=ups_config,
        pool="default",
        retries=1,
        retry_delay_minutes=5,
    )
    return [[exec_A], [exec_B]]


@pytest.fixture
def sample_workflow_config() -> WorkflowConfig:
    """
    Provides a standard WorkflowConfig with a daily trigger for DAG generation tests.
    """
    return WorkflowConfig(
        workflow_name="My_Test_Workflow",
        max_parallel_tasks=4,
        triggers={
            "daily_run": TriggerConfig(
                name="daily_run", schedule_interval="@daily", description="Daily run"
            )
        },
        stages=[Stage(stage=1, loads=[])],
    )


class TestDagGenerator:
    """
    Unit tests for the DagGenerator class, validating DAG file generation, structure, and content.
    """

    def test_dag_generation_structure_and_content(
        self, tmp_path: Path, sample_execution_plan, sample_workflow_config
    ):
        """
        Validates that the generated DAG file contains the correct structure, including dag_id, schedule,
        TaskGroups, and dependencies between tasks and groups.
        """
        generator = DagGenerator(output_path=str(tmp_path))
        generator.generate_dags(sample_execution_plan, sample_workflow_config, "prod")
        expected_file = tmp_path / "dag__my_test_workflow__daily_run__prod.py"
        assert expected_file.exists()
        generated_code = expected_file.read_text()
        assert 'dag_id="my_test_workflow__daily_run__prod"' in generated_code
        assert 'schedule="@daily"' in generated_code
        assert "is_paused_upon_creation=False" in generated_code
        assert "get_initial_timestamps" in generated_code
        assert 'TaskGroup(group_id="Batch_1_Stage_1")' in generated_code
        assert 'TaskGroup(group_id="Batch_2_Stage_2")' in generated_code
        code_without_whitespace = generated_code.replace("\n", "").replace(" ", "")
        assert "get_initial_timestamps>>tg_1" in code_without_whitespace
        assert "tg_1>>tg_2" in code_without_whitespace

    def test_dag_paused_for_dev_environment(
        self, tmp_path: Path, sample_execution_plan, sample_workflow_config
    ):
        """
        Ensures that the 'is_paused_upon_creation=True' flag is set in the generated DAG file for the dev environment.
        """
        generator = DagGenerator(output_path=str(tmp_path))
        generator.generate_dags(
            sample_execution_plan, sample_workflow_config, "dev", is_paused=True
        )
        expected_file = tmp_path / "dag__my_test_workflow__daily_run__dev.py"
        generated_code = expected_file.read_text()
        assert "is_paused_upon_creation=True" in generated_code

    def test_downstream_dag_trigger_generation(
        self, tmp_path: Path, sample_execution_plan, sample_workflow_config
    ):
        """
        Validates that a TriggerDagRunOperator is generated and correctly chained to downstream TaskGroups
        when trigger_dag_on_success is set in the workflow config.
        """
        sample_workflow_config.triggers["daily_run"].trigger_dag_on_success = (
            "downstream_trigger"
        )
        generator = DagGenerator(output_path=str(tmp_path))
        generator.generate_dags(sample_execution_plan, sample_workflow_config, "prod")
        expected_file = tmp_path / "dag__my_test_workflow__daily_run__prod.py"
        generated_code = expected_file.read_text()
        code_without_whitespace = generated_code.replace("\n", "").replace(" ", "")
        expected_triggered_dag_id = "my_test_workflow__downstream_trigger__prod"
        assert f'trigger_dag_id="{expected_triggered_dag_id}"' in generated_code
        trigger_task_name = f"trigger_{expected_triggered_dag_id.replace('-', '_')}"
        assert f"tg_2>>{trigger_task_name}" in code_without_whitespace

    def test_manual_schedule_generation(
        self, tmp_path: Path, sample_execution_plan, sample_workflow_config
    ):
        """
        Tests that when schedule_interval is None in the workflow config, the generated DAG file sets schedule=None.
        """
        sample_workflow_config.triggers["daily_run"].schedule_interval = None
        generator = DagGenerator(output_path=str(tmp_path))
        generator.generate_dags(sample_execution_plan, sample_workflow_config, "prod")
        expected_file = tmp_path / "dag__my_test_workflow__daily_run__prod.py"
        generated_code = expected_file.read_text()
        assert "schedule=None" in generated_code
        assert 'schedule="None"' not in generated_code

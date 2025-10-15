import pytest

from utils.planner.execution_planner import (
    ExecutionPlanner,
    InvalidWorkflowError,
)
from utils.planner.warehouse_basic_config import (
    WorkflowConfig,
    Stage,
    TableLoad,
    TableConfig,
    IncrementalConfig,
    UpsertConfig,
    TriggerConfig,
)

from pathlib import Path


@pytest.fixture
def dummy_incremental_config() -> IncrementalConfig:
    """
    Returns a default IncrementalConfig for testing.
    """
    return IncrementalConfig(
        source_timestamp_columns=["updated_at"], target_timestamp_column="dw_updated_at"
    )


@pytest.fixture
def dummy_upsert_config() -> UpsertConfig:
    """
    Returns a default UpsertConfig for testing.
    """
    return UpsertConfig(source_key_columns=["id"])


@pytest.fixture
def base_table_configs(
    tmp_path: Path,
    dummy_incremental_config: IncrementalConfig,
    dummy_upsert_config: UpsertConfig,
) -> dict[str, TableConfig]:
    """
    Creates a dictionary of TableConfig objects and temporary .sql files for testing.
    """
    (tmp_path / "A.sql").touch()
    (tmp_path / "B.sql").touch()
    (tmp_path / "C.sql").touch()

    return {
        "table_A": TableConfig(
            table_name="table_A",
            description="Table A",
            source_name="src",
            target_schema="stg",
            yml_config={},
            sql_path=str(tmp_path / "A.sql"),
            incremental_config=dummy_incremental_config,
            upsert_config=dummy_upsert_config,
            optional_filters=[],
            filter_sources={},
        ),
        "table_B": TableConfig(
            table_name="table_B",
            description="Table B",
            source_name="src",
            target_schema="stg",
            yml_config={},
            sql_path=str(tmp_path / "B.sql"),
            incremental_config=dummy_incremental_config,
            upsert_config=dummy_upsert_config,
            optional_filters=[],
            filter_sources={},
        ),
        "table_C": TableConfig(
            table_name="table_C",
            description="Table C",
            source_name="src",
            target_schema="marts",
            yml_config={},
            sql_path=str(tmp_path / "C.sql"),
            incremental_config=dummy_incremental_config,
            upsert_config=dummy_upsert_config,
            optional_filters=[],
            filter_sources={},
        ),
    }


@pytest.fixture
def databases_list() -> list[str]:
    """
    Returns a list of database names for testing.
    """
    return ["db_1", "db_2"]


def test_planner_initialization():
    """
    Tests if ExecutionPlanner is initialized correctly and the dependency validator is set.
    """
    planner = ExecutionPlanner()
    assert planner.validator is not None, "Dependency validator should be initialized."


def test_valid_plan_generation(base_table_configs, databases_list):
    """
    Tests execution plan generation for a valid workflow with no parallelism limit.
    Ensures correct batch and execution counts per stage.
    """
    workflow_config = WorkflowConfig(
        workflow_name="valid_workflow",
        max_parallel_tasks=10,
        triggers={
            "daily": TriggerConfig(
                name="daily", schedule_interval="@daily", description=""
            )
        },
        stages=[
            Stage(
                stage=1,
                loads=[
                    TableLoad(
                        table_name="table_A",
                        model="m",
                        stage=1,
                        depends_on=[],
                        trigger="daily",
                    ),
                    TableLoad(
                        table_name="table_B",
                        model="m",
                        stage=1,
                        depends_on=[],
                        trigger="daily",
                    ),
                ],
            ),
            Stage(
                stage=2,
                loads=[
                    TableLoad(
                        table_name="table_C",
                        model="m",
                        stage=2,
                        depends_on=["table_A"],
                        trigger="daily",
                    )
                ],
            ),
        ],
    )
    planner = ExecutionPlanner()
    execution_plan = planner.generate_execution_plan(
        workflow_config, base_table_configs, databases_list
    )
    assert len(execution_plan) == 2, "Should have 2 batches for 2 stages"
    batch_1 = execution_plan[0]
    assert (
        len(batch_1) == 4
    ), "Stage 1 should have 4 executions (2 tables x 2 databases)"
    assert {exec.table_name for exec in batch_1} == {"table_A", "table_B"}
    batch_2 = execution_plan[1]
    assert len(batch_2) == 2, "Stage 2 should have 2 executions (1 table x 2 databases)"
    assert {exec.table_name for exec in batch_2} == {"table_C"}


def test_plan_generation_respects_max_parallel_tasks(
    base_table_configs, databases_list
):
    """
    Tests if the planner splits batches correctly when theoretical parallelism exceeds the max_parallel_tasks limit.
    """
    workflow_config = WorkflowConfig(
        workflow_name="limited_workflow",
        max_parallel_tasks=2,
        triggers={
            "daily": TriggerConfig(
                name="daily", schedule_interval="@daily", description=""
            )
        },
        stages=[
            Stage(
                stage=1,
                loads=[
                    TableLoad(
                        table_name="table_A",
                        model="m",
                        stage=1,
                        depends_on=[],
                        trigger="daily",
                    ),
                    TableLoad(
                        table_name="table_B",
                        model="m",
                        stage=1,
                        depends_on=[],
                        trigger="daily",
                    ),
                ],
            ),
            Stage(
                stage=2,
                loads=[
                    TableLoad(
                        table_name="table_C",
                        model="m",
                        stage=2,
                        depends_on=["table_A"],
                        trigger="daily",
                    )
                ],
            ),
        ],
    )
    planner = ExecutionPlanner()
    execution_plan = planner.generate_execution_plan(
        workflow_config, base_table_configs, databases_list
    )
    assert len(execution_plan) == 3, f"Expected 3 batches, got {len(execution_plan)}"
    for batch in execution_plan:
        assert (
            len(batch) <= 2
        ), f"A batch exceeded the parallelism limit. Size: {len(batch)}"


def test_raises_error_for_circular_dependency(base_table_configs, databases_list):
    """
    Tests if the planner raises an error when a workflow contains a circular dependency.
    """
    workflow_config = WorkflowConfig(
        workflow_name="circular_workflow",
        max_parallel_tasks=10,
        triggers={
            "daily": TriggerConfig(
                name="daily", schedule_interval="@daily", description=""
            )
        },
        stages=[
            Stage(
                stage=1,
                loads=[
                    TableLoad(
                        table_name="table_A",
                        model="m",
                        stage=1,
                        depends_on=["table_C"],
                        trigger="daily",
                    )
                ],
            ),
            Stage(
                stage=2,
                loads=[
                    TableLoad(
                        table_name="table_C",
                        model="m",
                        stage=2,
                        depends_on=["table_A"],
                        trigger="daily",
                    )
                ],
            ),
        ],
    )
    planner = ExecutionPlanner()
    with pytest.raises(InvalidWorkflowError) as excinfo:
        planner.generate_execution_plan(
            workflow_config, base_table_configs, databases_list
        )
    assert "circular_dependency" in [error.error_type for error in excinfo.value.errors]


def test_raises_error_for_invalid_stage_dependency(base_table_configs, databases_list):
    """
    Tests if the planner raises an error when a dependency points to a future stage.
    """
    workflow_config = WorkflowConfig(
        workflow_name="bad_stage_workflow",
        max_parallel_tasks=10,
        triggers={
            "daily": TriggerConfig(
                name="daily", schedule_interval="@daily", description=""
            )
        },
        stages=[
            Stage(
                stage=1,
                loads=[
                    TableLoad(
                        table_name="table_A",
                        model="m",
                        stage=1,
                        depends_on=["table_C"],
                        trigger="daily",
                    )
                ],
            ),
            Stage(
                stage=2,
                loads=[
                    TableLoad(
                        table_name="table_C",
                        model="m",
                        stage=2,
                        depends_on=[],
                        trigger="daily",
                    )
                ],
            ),
        ],
    )
    planner = ExecutionPlanner()
    with pytest.raises(InvalidWorkflowError) as excinfo:
        planner.generate_execution_plan(
            workflow_config, base_table_configs, databases_list
        )
    assert "invalid_stage_dependency" in [
        error.error_type for error in excinfo.value.errors
    ]

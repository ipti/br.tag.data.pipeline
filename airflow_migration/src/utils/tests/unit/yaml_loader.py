import pytest
from pathlib import Path

from utils.planner.yaml_loader import YAMLLoader
from utils.planner.warehouse_basic_config import (
    WorkflowConfig,
    TableLoad,
    TableConfig,
)


@pytest.fixture
def mock_config_dir(tmp_path: Path) -> Path:
    """
    Creates a temporary directory structure with YAML files to simulate a real configuration environment.
    """
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()

    (tmp_path / "workflow.yml").write_text(
        """
workflow_name: "test_workflow"
max_parallel_tasks: 5
triggers:
  daily:
    schedule_interval: "@daily"
    description: "Roda diariamente"
stages:
  - stage: 1
    loads:
      - table_name: "stg_users"
        model: "tables/stg_users.yml"
        trigger: "daily"
        depends_on: []
        retries: 3
        pool: "high_cpu_pool"
  - stage: 2
    loads:
      - table_name: "fct_orders"
        model: "tables/fct_orders.yml"
        trigger: "daily"
        depends_on:
          - "stg_users"
    """
    )

    (tmp_path / "databases_mysql.yml").write_text(
        """
databases_dev:
  - "dev_db_1"
  - "dev_db_2"
databases_prod:
  - "prod_db_1"
    """
    )

    (tables_dir / "stg_users.yml").write_text(
        """
table_name: "stg_users"
description: "Staging de usuários"
sql_path: "models/staging/stg_users.sql"
source_name: "airflow_mysql"
target_schema: "stg"
    """
    )
    (tables_dir / "stg_users.sql").touch()

    (tables_dir / "fct_orders.yml").write_text(
        """
table_name: "fct_orders"
description: "Fato de pedidos"
sql_path: "models/marts/fct_orders.sql"
source_name: "{SOURCE_NAME}"
target_schema: "{TARGET_SCHEMA}"
    """
    )
    (tables_dir / "fct_orders.sql").touch()

    return tmp_path


def test_loader_initialization(mock_config_dir: Path):
    """
    Tests that YAMLLoader initializes correctly with the provided root directory.
    """
    loader = YAMLLoader(config_root=str(mock_config_dir))
    assert loader.config_root == mock_config_dir


def test_load_workflow_config_success(mock_config_dir: Path):
    """
    Tests loading and parsing of a valid workflow.yml file.
    Ensures that stages, triggers, and custom properties are correctly read.

    Example:
        workflow.workflow_name == "test_workflow"
        workflow.stages[0].loads[0].retries == 3
        workflow.stages[1].loads[0].retries == 1
    """
    loader = YAMLLoader(config_root=str(mock_config_dir))
    workflow = loader.load_workflow_config("workflow.yml")

    assert isinstance(workflow, WorkflowConfig)
    assert workflow.workflow_name == "test_workflow"
    assert len(workflow.stages) == 2
    assert len(workflow.stages[0].loads) == 1

    stg_users_load = workflow.stages[0].loads[0]
    assert isinstance(stg_users_load, TableLoad)
    assert stg_users_load.table_name == "stg_users"
    assert stg_users_load.retries == 3
    assert stg_users_load.pool == "high_cpu_pool"

    fct_orders_load = workflow.stages[1].loads[0]
    assert fct_orders_load.retries == 1
    assert fct_orders_load.pool is None


def test_load_workflow_config_file_not_found(tmp_path: Path):
    """
    Tests that FileNotFoundError is raised when workflow.yml does not exist.
    """
    loader = YAMLLoader(config_root=str(tmp_path))
    with pytest.raises(FileNotFoundError):
        loader.load_workflow_config("non_existent_workflow.yml")


def test_load_databases_list_selects_environment(mock_config_dir: Path):
    """
    Tests that the correct database list is returned for each environment.

    Example:
        dev_dbs == ["dev_db_1", "dev_db_2"]
        prod_dbs == ["prod_db_1"]
    """
    loader = YAMLLoader(config_root=str(mock_config_dir))
    dev_dbs = loader.load_databases_list("databases_mysql.yml", environment="dev")
    prod_dbs = loader.load_databases_list("databases_mysql.yml", environment="prod")

    assert dev_dbs == ["dev_db_1", "dev_db_2"]
    assert prod_dbs == ["prod_db_1"]


def test_load_table_configs_success(mock_config_dir: Path):
    """
    Tests that table configurations are loaded correctly from a workflow.
    Ensures that fixed and placeholder values are handled as expected.

    Example:
        table_configs["stg_users"].source_name == "airflow_mysql"
        table_configs["fct_orders"].source_name == "{SOURCE_NAME}"
    """
    loader = YAMLLoader(config_root=str(mock_config_dir))
    workflow = loader.load_workflow_config("workflow.yml")
    table_configs = loader.load_table_configs(workflow)

    assert isinstance(table_configs, dict)
    assert len(table_configs) == 2
    assert "stg_users" in table_configs
    assert "fct_orders" in table_configs

    stg_users_config = table_configs["stg_users"]
    assert isinstance(stg_users_config, TableConfig)
    assert stg_users_config.source_name == "airflow_mysql"
    assert stg_users_config.needs_target_schema_resolution() is False

    fct_orders_config = table_configs["fct_orders"]
    assert fct_orders_config.source_name == "{SOURCE_NAME}"
    assert fct_orders_config.needs_target_schema_resolution() is True


def test_load_table_configs_missing_sql_file_raises_error(mock_config_dir: Path):
    """
    Tests that an error is raised if the .sql file corresponding to a .yml config is missing.

    Example:
        FileNotFoundError("Missing configuration files ... fct_orders.sql")
    """
    (mock_config_dir / "tables" / "fct_orders.sql").unlink()
    loader = YAMLLoader(config_root=str(mock_config_dir))
    workflow = loader.load_workflow_config("workflow.yml")

    with pytest.raises(FileNotFoundError) as excinfo:
        loader.load_table_configs(workflow)

    assert "Missing configuration files" in str(excinfo.value)
    assert "fct_orders.sql" in str(excinfo.value)

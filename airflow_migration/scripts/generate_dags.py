"""
DAG Generation Build Script.

This script serves as the main entry point for the dynamic DAG generation framework.
It orchestrates the end-to-end process for ALL target environments (e.g., dev, prod).
For each environment, it:
1.  Loads the relevant YAML configurations.
2.  Validates dependencies and creates an optimized execution plan.
3.  Generates the final Airflow DAG .py files into the /dags directory,
    applying environment-specific rules, such as pausing DAGs for dev.

This script should be executed manually or in a CI/CD pipeline whenever there
is a change in the YAML configuration files to regenerate all DAGs.
"""

from pathlib import Path

# Assuming 'src' is installed via `pip install -e .`
from utils.logs.logging_functions import get_logger
from utils.planner.dag_generator import DagGenerator
from utils.planner.execution_planner import ExecutionPlanner, InvalidWorkflowError
from utils.planner.yaml_loader import YAMLLoader

# --- Configuration Constants ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_ROOT = PROJECT_ROOT / "config/warehouse_etl"
DAGS_OUTPUT_DIR = PROJECT_ROOT / "dags"

WORKFLOW_FILE = "workflow.yml"
DATABASES_FILE = "database_mysql.yml"

# Define all environments for which DAGs should be generated
TARGET_ENVIRONMENTS = ["dev", "prod"]

logger = get_logger("dag_build_script")


def main():
    """
    Orchestrates the DAG generation process for all defined target environments.
    """
    logger.info("--- STARTING DAG GENERATION BUILD SCRIPT FOR ALL ENVIRONMENTS ---")

    try:
        # Load non-environment-specific configurations once to be efficient
        logger.info("Loading shared configurations (workflow, tables)...")
        loader = YAMLLoader(config_root=str(CONFIG_ROOT))
        workflow_config = loader.load_workflow_config(WORKFLOW_FILE)
        table_configs = loader.load_table_configs(workflow_config)
        logger.info("Shared configurations loaded successfully.")

        # Instantiate the generator once
        generator = DagGenerator(output_path=str(DAGS_OUTPUT_DIR))

        # Loop through each target environment to generate its specific DAGs
        for environment in TARGET_ENVIRONMENTS:
            logger.info(f"--- Processing environment: {environment.upper()} ---")

            # Load environment-specific database list
            databases_list = loader.load_databases_list(
                DATABASES_FILE, environment=environment
            )

            # Generate the execution plan for this environment
            planner = ExecutionPlanner()
            execution_plan = planner.generate_execution_plan(
                workflow_config=workflow_config,
                table_configs=table_configs,
                databases_list=databases_list,
                environment=environment,
            )

            # Determine if DAGs for this environment should be paused upon creation
            is_paused = environment == "dev"
            logger.info(f"Generating DAGs with is_paused_upon_creation={is_paused}")

            # Generate the DAG files for this specific plan and environment
            generator.generate_dags(
                execution_plan, workflow_config, environment, is_paused=is_paused
            )

        print("\n--- DAG GENERATION COMPLETED SUCCESSFULLY FOR ALL ENVIRONMENTS ---")

    except InvalidWorkflowError as e:
        logger.error("--- BUILD FAILED: Workflow configuration is invalid. ---")
        for error in e.errors:
            logger.error(f" - {error.message}")
        exit(1)
    except Exception as e:
        logger.error(
            f"--- BUILD FAILED: An unexpected error occurred: {e}",
        )
        exit(1)


if __name__ == "__main__":
    main()

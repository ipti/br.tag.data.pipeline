from typing import Dict, List, Optional, Any
from pathlib import Path
import yaml

from airflow_migration.src.utils.logs.logging_functions import get_logger
from .warehouse_basic_config import (
    WorkflowConfig,
    TriggerConfig,
    Stage,
    TableLoad,
    TableConfig,
)
from airflow_migration.src.utils.connections.writer import (
    IncrementalConfig,
    UpsertConfig,
)


class YAMLLoader:
    """Handles loading and validation of YAML configuration files integrated with DatabaseConnectionManager"""

    def __init__(self, config_root: Optional[str] = None):
        """
        Initialize YAML Loader

        Args:
            config_root: Root directory for configuration files. If None, uses current directory
        """
        self.logger = get_logger("yaml_loader")
        self.config_root = Path(config_root) if config_root else Path.cwd()
        self.table_configs: Dict[str, TableConfig] = {}

        self.logger.info(
            "YAMLLoader initialized",
            {
                "config_root": str(self.config_root),
                "config_root_exists": self.config_root.exists(),
            },
        )

    def load_workflow_config(
        self, workflow_file: str = "workflow.yml"
    ) -> WorkflowConfig:
        """
        Loads the main workflow configuration from a YAML file.

        Args:
            workflow_file (str): Name of the workflow YAML file.

        Returns:
            WorkflowConfig: Validated workflow configuration.

        Raises:
            FileNotFoundError: If the workflow file is not found.
            ValueError: If the configuration is invalid.
            yaml.YAMLError: If YAML parsing fails.

        Example:
            loader = YAMLLoader("/path/to/configs")
            workflow_config = loader.load_workflow_config("workflow.yml")

        Output Example:
            WorkflowConfig(
                workflow_name='example_workflow',
                max_parallel_tasks=4,
                triggers={'daily': TriggerConfig(...), ...},
                stages=[Stage(stage=1, loads=[TableLoad(...), ...]), ...]
            )
        """
        workflow_path = self.config_root / workflow_file

        if not workflow_path.exists():
            error_msg = f"Workflow configuration file not found: {workflow_path}"
            self.logger.error(
                "Workflow file not found",
                extra_data={
                    "workflow_path": str(workflow_path),
                    "config_root": str(self.config_root),
                    "error": error_msg,
                },
            )
            raise FileNotFoundError(error_msg)

        try:
            self.logger.info(
                "Loading workflow configuration", {"workflow_file": str(workflow_path)}
            )

            with open(workflow_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f)

            if not isinstance(raw_config, dict):
                error_msg = "Workflow configuration must be a dictionary"
                self.logger.error(
                    "Invalid workflow structure",
                    extra_data={"config_type": type(raw_config), "error": error_msg},
                )
                raise ValueError(error_msg)

            # Parse triggers
            triggers = self._parse_triggers(raw_config.get("triggers", {}))

            # Parse stages
            stages = self._parse_stages(raw_config.get("stages", []), triggers)

            # Create WorkflowConfig
            workflow_config = WorkflowConfig(
                workflow_name=raw_config.get("workflow_name", ""),
                max_parallel_tasks=raw_config.get("max_parallel_tasks", 4),
                triggers=triggers,
                stages=stages,
            )

            self.logger.info(
                "Workflow configuration loaded successfully",
                {
                    "workflow_name": workflow_config.workflow_name,
                    "triggers_count": len(workflow_config.triggers),
                    "stages_count": len(workflow_config.stages),
                    "total_tables": sum(
                        len(stage.loads) for stage in workflow_config.stages
                    ),
                },
            )

            return workflow_config

        except yaml.YAMLError as e:
            error_msg = f"YAML parsing error in {workflow_file}: {str(e)}"
            self.logger.error(
                "YAML parsing failed",
                exception=e,
                extra_data={"workflow_file": str(workflow_path), "error": error_msg},
            )
            raise yaml.YAMLError(error_msg)

        except Exception as e:
            error_msg = f"Failed to load workflow configuration: {str(e)}"
            self.logger.error(
                "Workflow loading failed",
                exception=e,
                extra_data={"workflow_file": str(workflow_path), "error": error_msg},
            )
            raise ValueError(error_msg)

    def load_databases_list(
        self, databases_file: str = "databases_mysql.yml", environment: str = "dev"
    ) -> List[str]:
        """
        Load list of database names for the specified environment

        Args:
            databases_file: Name of the databases YAML file
            environment: Environment ('dev' or 'prod')

        Returns:
            List of database names for the environment

        Raises:
            FileNotFoundError: If databases file is not found
            ValueError: If configuration is invalid or environment not found
        """
        databases_path = self.config_root / databases_file

        if not databases_path.exists():
            error_msg = f"Databases configuration file not found: {databases_path}"
            self.logger.error(
                "Databases file not found",
                extra_data={
                    "databases_path": str(databases_path),
                    "config_root": str(self.config_root),
                    "error": error_msg,
                },
            )
            raise FileNotFoundError(error_msg)

        try:
            self.logger.info(
                "Loading databases list",
                {"databases_file": str(databases_path), "environment": environment},
            )

            with open(databases_path, "r", encoding="utf-8") as f:
                raw_config = yaml.safe_load(f)

            if not isinstance(raw_config, dict):
                error_msg = "Databases configuration must be a dictionary"
                self.logger.error(
                    "Invalid databases structure",
                    extra_data={"config_type": type(raw_config), "error": error_msg},
                )
                raise ValueError(error_msg)

            # Get database list for environment
            env_key = f"databases_{environment.lower()}"
            if env_key not in raw_config:
                error_msg = (
                    f"Environment '{environment}' not found in databases configuration"
                )
                self.logger.error(
                    "Environment not found",
                    extra_data={
                        "environment": environment,
                        "env_key": env_key,
                        "available_keys": list(raw_config.keys()),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

            databases_config = raw_config[env_key]
            if not isinstance(databases_config, list):
                error_msg = f"{env_key} must be a list"
                self.logger.error(
                    "Invalid environment databases format",
                    extra_data={
                        "env_key": env_key,
                        "config_type": type(databases_config),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

            # Extract database names
            database_names = []
            for db_config in databases_config:
                if isinstance(db_config, dict) and "name" in db_config:
                    database_names.append(db_config["name"])
                elif isinstance(db_config, str):
                    database_names.append(db_config)
                else:
                    self.logger.warning(
                        "Invalid database entry format",
                        extra_data={"db_config": db_config, "environment": environment},
                    )

            self.logger.info(
                "Database list loaded successfully",
                {
                    "environment": environment,
                    "databases_count": len(database_names),
                    "databases": database_names,
                },
            )

            return database_names

        except yaml.YAMLError as e:
            error_msg = f"YAML parsing error in {databases_file}: {str(e)}"
            self.logger.error(
                "Databases YAML parsing failed",
                exception=e,
                extra_data={"databases_file": str(databases_path), "error": error_msg},
            )
            raise yaml.YAMLError(error_msg)

        except Exception as e:
            error_msg = f"Failed to load databases list: {str(e)}"
            self.logger.error(
                "Databases loading failed",
                exception=e,
                extra_data={
                    "databases_file": str(databases_path),
                    "environment": environment,
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

    def _parse_triggers(
        self, triggers_config: Dict[str, Any]
    ) -> Dict[str, TriggerConfig]:
        """Parse triggers configuration from raw YAML"""
        triggers = {}

        for trigger_name, trigger_data in triggers_config.items():
            if not isinstance(trigger_data, dict):
                error_msg = (
                    f"Trigger '{trigger_name}' configuration must be a dictionary"
                )
                self.logger.error(
                    "Invalid trigger configuration",
                    extra_data={
                        "trigger_name": trigger_name,
                        "trigger_data_type": type(trigger_data),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

            triggers[trigger_name] = TriggerConfig(
                name=trigger_name,
                schedule_interval=trigger_data.get("schedule_interval", ""),
                description=trigger_data.get("description", ""),
            )

        self.logger.debug(
            "Triggers parsed successfully",
            extra_data={
                "triggers_count": len(triggers),
                "trigger_names": list(triggers.keys()),
            },
        )

        return triggers

    def _parse_stages(
        self, stages_config: List[Any], triggers: Dict[str, TriggerConfig]
    ) -> List[Stage]:
        """Parse stages configuration from raw YAML"""
        if not isinstance(stages_config, list):
            error_msg = "Stages configuration must be a list"
            self.logger.error(
                "Invalid stages configuration",
                extra_data={
                    "stages_config_type": type(stages_config),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        stages = []

        for stage_data in stages_config:
            if not isinstance(stage_data, dict):
                error_msg = "Each stage configuration must be a dictionary"
                self.logger.error(
                    "Invalid stage configuration",
                    extra_data={
                        "stage_data_type": type(stage_data),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

            stage_number = stage_data.get("stage")
            loads_config = stage_data.get("loads", [])

            # Parse table loads
            loads = self._parse_table_loads(loads_config, triggers, stage_number)

            stages.append(Stage(stage=stage_number, loads=loads))

        self.logger.debug(
            "Stages parsed successfully",
            extra_data={
                "stages_count": len(stages),
                "stage_numbers": [stage.stage for stage in stages],
            },
        )

        return stages

    def _parse_table_loads(
        self,
        loads_config: List[Any],
        triggers: Dict[str, TriggerConfig],
        stage_number: int,
    ) -> List[TableLoad]:
        """Parse table loads configuration from raw YAML"""
        if not isinstance(loads_config, list):
            error_msg = f"Loads configuration in stage {stage_number} must be a list"
            self.logger.error(
                "Invalid loads configuration",
                extra_data={
                    "stage_number": stage_number,
                    "loads_config_type": type(loads_config),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        loads = []

        for load_data in loads_config:
            if not isinstance(load_data, dict):
                error_msg = f"Each load configuration in stage {stage_number} must be a dictionary"
                self.logger.error(
                    "Invalid load configuration",
                    extra_data={
                        "stage_number": stage_number,
                        "load_data_type": type(load_data),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

            table_name = load_data.get("table_name", "")
            trigger = load_data.get("trigger", "")

            # Validate trigger exists
            if trigger not in triggers:
                error_msg = f"Unknown trigger '{trigger}' for table '{table_name}' in stage {stage_number}"
                self.logger.error(
                    "Invalid trigger reference",
                    extra_data={
                        "table_name": table_name,
                        "trigger": trigger,
                        "stage_number": stage_number,
                        "available_triggers": list(triggers.keys()),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

            loads.append(
                TableLoad(
                    table_name=table_name,
                    model=load_data.get("model", ""),
                    stage=stage_number,
                    depends_on=load_data.get("depends_on", []),
                    trigger=trigger,
                    max_parallel_override=load_data.get("max_parallel_override"),
                    pool=load_data.get("pool"),
 
                )
            )

        self.logger.debug(
            "Table loads parsed successfully",
            extra_data={
                "stage_number": stage_number,
                "loads_count": len(loads),
                "table_names": [load.table_name for load in loads],
            },
        )

        return loads

    def load_table_configs(
        self, workflow_config: WorkflowConfig
    ) -> Dict[str, TableConfig]:
        """
        Load configuration files for all tables referenced in the workflow

        Args:
            workflow_config: Workflow configuration containing table references

        Returns:
            Dictionary mapping table names to their TableConfig objects

        Raises:
            FileNotFoundError: If required YML or SQL files are missing
            ValueError: If table configurations are invalid
        """
        self.logger.info(
            "Loading table configurations",
            {"total_tables": sum(len(stage.loads) for stage in workflow_config.stages)},
        )

        table_configs = {}
        missing_files = []

        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name
                model_path = table_load.model

                try:
                    table_config = self._load_single_table_config(
                        table_name, model_path
                    )
                    table_configs[table_name] = table_config

                except FileNotFoundError as e:
                    missing_files.append(str(e))
                    self.logger.error(
                        "Table configuration file not found",
                        extra_data={
                            "table_name": table_name,
                            "model_path": model_path,
                            "error": str(e),
                        },
                    )

        if missing_files:
            error_msg = "Missing configuration files:\n" + "\n".join(missing_files)
            self.logger.error(
                "Multiple configuration files missing",
                extra_data={
                    "missing_files_count": len(missing_files),
                    "missing_files": missing_files,
                },
            )
            raise FileNotFoundError(error_msg)

        self.table_configs = table_configs

        self.logger.info(
            "Table configurations loaded successfully",
            {
                "loaded_tables_count": len(table_configs),
                "table_names": list(table_configs.keys()),
                "fixed_schemas": [
                    name
                    for name, config in table_configs.items()
                    if config.is_fixed_schema()
                ],
                "placeholder_schemas": [
                    name
                    for name, config in table_configs.items()
                    if config.needs_target_schema_resolution()
                ],
            },
        )

        return table_configs

    def _load_single_table_config(
        self, table_name: str, model_path: str
    ) -> TableConfig:
        """
        Load configuration for a single table with support for both placeholders and fixed values

        Args:
            table_name: Name of the table
            model_path: Path to the table's YML configuration file

        Returns:
            TableConfig object with loaded configuration

        Raises:
            FileNotFoundError: If YML or SQL files are missing
            ValueError: If configuration is invalid
        """
        # Resolve YML file path
        yml_path = self.config_root / model_path
        if not yml_path.exists():
            error_msg = (
                f"YML configuration file not found for table '{table_name}': {yml_path}"
            )
            raise FileNotFoundError(error_msg)

        # Check for corresponding SQL file
        sql_path = yml_path.with_suffix(".sql")
        if not sql_path.exists():
            error_msg = f"SQL file not found for table '{table_name}': {sql_path}"
            raise FileNotFoundError(error_msg)

        try:
            with open(yml_path, "r", encoding="utf-8") as f:
                yml_config = yaml.safe_load(f)

            if not isinstance(yml_config, dict):
                error_msg = (
                    f"YML configuration for table '{table_name}' must be a dictionary"
                )
                raise ValueError(error_msg)

            # Parse incremental config
            incremental_raw = yml_config.get("incremental_config", {})
            incremental_config = IncrementalConfig(
                source_timestamp_columns=incremental_raw.get(
                    "source_timestamp_columns", []
                ),
                target_timestamp_column=incremental_raw.get(
                    "target_timestamp_column", "inserted_at"
                ),
                lookback_hours=incremental_raw.get("lookback_hours", 24),
                batch_size=incremental_raw.get("batch_size", 5000),
                full_refresh=incremental_raw.get("full_refresh", False),
            )

            # Parse upsert config
            upsert_raw = yml_config.get("upsert_config", {})
            upsert_config = UpsertConfig(
                source_key_columns=upsert_raw.get("source_key_columns", []),
                target_key_columns=upsert_raw.get("target_key_columns", []),
            )

            # Parse optional filters and filter sources
            optional_filters = yml_config.get("optional_filters", [])
            if isinstance(optional_filters, dict):
                # Handle legacy format - convert to list
                optional_filters = (
                    list(optional_filters.keys()) if optional_filters else []
                )

            filter_sources = yml_config.get("filter_sources", {})

            # Get source_name and target_schema - can be placeholders or fixed values
            source_name = yml_config.get("source_name", "{SOURCE_NAME}")
            target_schema = yml_config.get("target_schema", "{TARGET_SCHEMA}")

            table_config = TableConfig(
                table_name=table_name,
                description=yml_config.get("description", ""),
                source_name=source_name,
                target_schema=target_schema,
                yml_config=yml_config,
                sql_path=str(sql_path),
                incremental_config=incremental_config,
                upsert_config=upsert_config,
                optional_filters=optional_filters,
                filter_sources=filter_sources,
            )

            self.logger.debug(
                "Table configuration loaded",
                extra_data={
                    "table_name": table_name,
                    "yml_path": str(yml_path),
                    "sql_path": str(sql_path),
                    "source_name": source_name,
                    "target_schema": target_schema,
                    "is_fixed_schema": table_config.is_fixed_schema(),
                    "needs_source_resolution": table_config.needs_source_name_resolution(),
                    "optional_filters": optional_filters,
                    "filter_sources": list(filter_sources.keys()),
                    "timestamp_columns": incremental_config.source_timestamp_columns,
                },
            )

            return table_config

        except yaml.YAMLError as e:
            error_msg = f"YAML parsing error in {yml_path}: {str(e)}"
            raise yaml.YAMLError(error_msg)

        except Exception as e:
            error_msg = (
                f"Failed to load configuration for table '{table_name}': {str(e)}"
            )
            raise ValueError(error_msg)

    def get_table_config(self, table_name: str) -> Optional[TableConfig]:
        """Get configuration for a specific table"""
        return self.table_configs.get(table_name)

    def validate_file_structure(self, workflow_config: WorkflowConfig) -> List[str]:
        """Validate that all required files exist for the workflow"""
        self.logger.info("Validating file structure for workflow")

        errors = []

        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name
                model_path = table_load.model

                # Check YML file
                yml_path = self.config_root / model_path
                if not yml_path.exists():
                    errors.append(
                        f"Missing YML file for table '{table_name}': {yml_path}"
                    )

                # Check SQL file
                sql_path = (
                    yml_path.with_suffix(".sql")
                    if yml_path.exists()
                    else self.config_root / f"{model_path.replace('.yml', '.sql')}"
                )
                if not sql_path.exists():
                    errors.append(
                        f"Missing SQL file for table '{table_name}': {sql_path}"
                    )

        if errors:
            self.logger.error(
                "File structure validation failed",
                extra_data={"errors_count": len(errors), "errors": errors},
            )
        else:
            self.logger.info("File structure validation passed")

        return errors

    def resolve_placeholders_with_db_manager(
        self, db_manager, environment: str = None
    ) -> Dict[str, Dict[str, str]]:
        """
        Resolve placeholders using DatabaseConnectionManager configuration

        Args:
            db_manager: DatabaseConnectionManager instance
            environment: Optional environment override ('dev' or 'prod')

        Returns:
            Dictionary mapping table names to resolved placeholder values
        """
        resolved_configs = {}

        # Get environment from db_manager if not specified
        if environment is None:
            environment = (
                "prod"
                if (db_manager.is_production or db_manager.hotfix_mode)
                else "dev"
            )

        # Resolve SOURCE_NAME based on environment
        if environment == "dev":
            resolved_source_name = "airflow_mysql"
        else:
            # For prod, use mysql_source_1 (or could be configurable)
            resolved_source_name = "mysql_source_1"

        # Resolve TARGET_SCHEMA based on DatabaseConnectionManager schema
        resolved_target_schema = db_manager.sqlserver_config.schema

        self.logger.info(
            "Resolving placeholders",
            {
                "environment": environment,
                "resolved_source_name": resolved_source_name,
                "resolved_target_schema": resolved_target_schema,
                "is_production": db_manager.is_production,
                "hotfix_mode": db_manager.hotfix_mode,
            },
        )

        # Apply resolutions to each table config
        for table_name, table_config in self.table_configs.items():
            resolved = {}

            # Resolve source_name if needed
            if table_config.needs_source_name_resolution():
                resolved["source_name"] = resolved_source_name
            else:
                resolved["source_name"] = table_config.source_name

            # Resolve target_schema if needed
            if table_config.needs_target_schema_resolution():
                resolved["target_schema"] = resolved_target_schema
            else:
                resolved["target_schema"] = (
                    table_config.target_schema
                )  # Keep fixed value like 'raw'

            resolved_configs[table_name] = resolved

        self.logger.debug(
            "Placeholders resolved for all tables",
            {
                "tables_count": len(resolved_configs),
                "fixed_schemas": [
                    name
                    for name, config in self.table_configs.items()
                    if config.is_fixed_schema()
                ],
                "resolved_schemas": [
                    name
                    for name, config in self.table_configs.items()
                    if config.needs_target_schema_resolution()
                ],
            },
        )

        return resolved_configs

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


from utils.logs.logging_functions import get_logger
from utils.connections.writer import (
    UpsertConfig,
    IncrementalConfig,
)


@dataclass
class TriggerConfig:
    """Configuration for DAG scheduling triggers"""

    name: str
    schedule_interval: str
    description: str
    incremental_reference_table: Optional[str] = None

    def __post_init__(self):
        """Validates if the schedule_interval is valid"""
        logger = get_logger("warehouse_basic_config")

        if (
            not isinstance(self.schedule_interval, str)
            or not self.schedule_interval.strip()
        ):
            error_msg = (
                f"schedule_interval must be a valid string for trigger '{self.name}'"
            )
            logger.error(
                "Invalid trigger configuration",
                extra_data={
                    "trigger_name": self.name,
                    "schedule_interval": self.schedule_interval,
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        logger.debug(
            "TriggerConfig validated successfully",
            extra_data={
                "trigger_name": self.name,
                "schedule_interval": self.schedule_interval,
            },
        )


@dataclass
class TableLoad:
    """Configuration for loading a specific table"""

    table_name: str
    model: str  # path to the yml file
    depends_on: List[str]
    stage: int
    trigger: str
    max_parallel_override: Optional[int] = None
    pool: Optional[str] = None
    retries: int = 1
    retry_delay_minutes: int = 5
    env_skip: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Basic validations for required fields"""
        logger = get_logger("warehouse_basic_config")

        if not self.table_name or not isinstance(self.table_name, str):
            error_msg = "table_name must be a non-empty string"
            logger.error(
                "Invalid TableLoad configuration",
                extra_data={"table_name": self.table_name, "error": error_msg},
            )
            raise ValueError(error_msg)

        if not self.model or not isinstance(self.model, str):
            error_msg = "model must be a non-empty string"
            logger.error(
                "Invalid TableLoad configuration",
                extra_data={
                    "table_name": self.table_name,
                    "model": self.model,
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        if not self.trigger or not isinstance(self.trigger, str):
            error_msg = "trigger must be a non-empty string"
            logger.error(
                "Invalid TableLoad configuration",
                extra_data={
                    "table_name": self.table_name,
                    "trigger": self.trigger,
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        if not isinstance(self.depends_on, list):
            error_msg = "depends_on must be a list"
            logger.error(
                "Invalid TableLoad configuration",
                extra_data={
                    "table_name": self.table_name,
                    "depends_on": self.depends_on,
                    "depends_on_type": type(self.depends_on),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        logger.debug(
            "TableLoad validated successfully",
            extra_data={
                "table_name": self.table_name,
                "model": self.model,
                "trigger": self.trigger,
                "dependencies_count": len(self.depends_on),
            },
        )


@dataclass
class Stage:
    """Represents a pipeline stage with its tables"""

    stage: int
    loads: List[TableLoad]

    def __post_init__(self):
        """Stage validations"""
        logger = get_logger("warehouse_basic_config")

        if not isinstance(self.stage, int) or self.stage < 1:
            error_msg = "stage must be a positive integer"
            logger.error(
                "Invalid Stage configuration",
                extra_data={
                    "stage": self.stage,
                    "stage_type": type(self.stage),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        if not isinstance(self.loads, list):
            error_msg = "loads must be a list of TableLoad"
            logger.error(
                "Invalid Stage configuration",
                extra_data={
                    "stage": self.stage,
                    "loads_type": type(self.loads),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        # Validates if all items are TableLoad
        for i, load in enumerate(self.loads):
            if not isinstance(load, TableLoad):
                error_msg = f"All items in loads must be TableLoad, found: {type(load)}"
                logger.error(
                    "Invalid Stage configuration",
                    extra_data={
                        "stage": self.stage,
                        "load_index": i,
                        "load_type": type(load),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

        logger.debug(
            "Stage validated successfully",
            extra_data={
                "stage": self.stage,
                "tables_count": len(self.loads),
                "table_names": [load.table_name for load in self.loads],
            },
        )


@dataclass
class WorkflowConfig:
    """Main workflow configuration with all stages and triggers"""

    workflow_name: str
    max_parallel_tasks: int
    triggers: Dict[str, TriggerConfig]
    stages: List[Stage]

    def __post_init__(self):
        """Workflow configuration validations"""
        logger = get_logger("warehouse_basic_config")

        if not self.workflow_name or not isinstance(self.workflow_name, str):
            error_msg = "workflow_name must be a non-empty string"
            logger.error(
                "Invalid WorkflowConfig",
                extra_data={"workflow_name": self.workflow_name, "error": error_msg},
            )
            raise ValueError(error_msg)

        if not isinstance(self.max_parallel_tasks, int) or self.max_parallel_tasks < 1:
            error_msg = "max_parallel_tasks must be a positive integer"
            logger.error(
                "Invalid WorkflowConfig",
                extra_data={
                    "workflow_name": self.workflow_name,
                    "max_parallel_tasks": self.max_parallel_tasks,
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        if not isinstance(self.triggers, dict):
            error_msg = "triggers must be a dictionary"
            logger.error(
                "Invalid WorkflowConfig",
                extra_data={
                    "workflow_name": self.workflow_name,
                    "triggers_type": type(self.triggers),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        if not isinstance(self.stages, list) or not self.stages:
            error_msg = "stages must be a non-empty list"
            logger.error(
                "Invalid WorkflowConfig",
                extra_data={
                    "workflow_name": self.workflow_name,
                    "stages_type": type(self.stages),
                    "stages_length": (
                        len(self.stages) if isinstance(self.stages, list) else 0
                    ),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        for trigger_name, trigger_config in self.triggers.items():
            if not isinstance(trigger_config, TriggerConfig):
                error_msg = (
                    f"Trigger '{trigger_name}' must be an instance of TriggerConfig"
                )
                logger.error(
                    "Invalid WorkflowConfig",
                    extra_data={
                        "workflow_name": self.workflow_name,
                        "trigger_name": trigger_name,
                        "trigger_type": type(trigger_config),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

        for i, stage in enumerate(self.stages):
            if not isinstance(stage, Stage):
                error_msg = f"All items in stages must be Stage, found: {type(stage)}"
                logger.error(
                    "Invalid WorkflowConfig",
                    extra_data={
                        "workflow_name": self.workflow_name,
                        "stage_index": i,
                        "stage_type": type(stage),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

        # Validates if stage numbers are sequential
        stage_numbers = [stage.stage for stage in self.stages]
        stage_numbers.sort()
        expected_stages = list(range(1, len(stage_numbers) + 1))

        if stage_numbers != expected_stages:
            error_msg = f"Stage numbers must be sequential starting at 1. Found: {stage_numbers}, Expected: {expected_stages}"
            logger.error(
                "Invalid WorkflowConfig",
                extra_data={
                    "workflow_name": self.workflow_name,
                    "found_stages": stage_numbers,
                    "expected_stages": expected_stages,
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        logger.info(
            "WorkflowConfig validated successfully",
            {
                "workflow_name": self.workflow_name,
                "max_parallel_tasks": self.max_parallel_tasks,
                "triggers_count": len(self.triggers),
                "stages_count": len(self.stages),
                "total_tables": sum(len(stage.loads) for stage in self.stages),
            },
        )


@dataclass
class TableConfig:
    """Updated table configuration integrated with existing architecture"""

    table_name: str
    description: str
    source_name: str  # Can be placeholder {SOURCE_NAME} or fixed value
    target_schema: str  # Can be placeholder {TARGET_SCHEMA} or fixed value like 'raw'
    yml_config: Dict[str, Any]
    sql_path: str
    incremental_config: IncrementalConfig
    upsert_config: UpsertConfig
    optional_filters: List[str]
    filter_sources: Dict[str, str]
    quality_check_pipeline: List[str] = field(default_factory=list)
    quality_check_params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Table configuration validations"""
        logger = get_logger("config_manager")

        if not self.table_name:
            error_msg = "table_name cannot be empty"
            logger.error(
                "Invalid TableConfig",
                extra_data={"table_name": self.table_name, "error": error_msg},
            )
            raise ValueError(error_msg)

        if not isinstance(self.yml_config, dict):
            error_msg = "yml_config must be a dictionary"
            logger.error(
                "Invalid TableConfig",
                extra_data={
                    "table_name": self.table_name,
                    "yml_config_type": type(self.yml_config),
                    "error": error_msg,
                },
            )
            raise ValueError(error_msg)

        logger.debug(
            "TableConfig validated successfully",
            extra_data={
                "table_name": self.table_name,
                "sql_path": self.sql_path,
                "yml_keys": list(self.yml_config.keys()),
            },
        )

    def needs_source_name_resolution(self) -> bool:
        """Check if source_name needs to be resolved from placeholder"""
        return self.source_name == "{SOURCE_NAME}"

    def needs_target_schema_resolution(self) -> bool:
        """Check if target_schema needs to be resolved from placeholder"""
        return self.target_schema == "{TARGET_SCHEMA}"

    def is_fixed_schema(self) -> bool:
        """Check if target_schema is a fixed value (like 'raw')"""
        return not self.needs_target_schema_resolution()


@dataclass
class FilterCombination:
    """Represents a unique combination of filters for dynamic table execution"""

    database_name: str
    school_inep_fk: str
    classroom_id: int
    additional_filters: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Filter combination validations"""
        logger = get_logger("filter_resolver")

        required_fields = {
            "database_name": self.database_name,
            "school_inep_fk": self.school_inep_fk,
            "classroom_id": self.classroom_id,
        }

        for field_name, field_value in required_fields.items():
            if not field_value or not isinstance(field_value, str):
                error_msg = f"{field_name} must be a non-empty string"
                logger.error(
                    "Invalid FilterCombination",
                    extra_data={
                        "field_name": field_name,
                        "field_value": field_value,
                        "field_type": type(field_value),
                        "error": error_msg,
                    },
                )
                raise ValueError(error_msg)

        logger.debug(
            "FilterCombination validated successfully",
            extra_data={
                "database_name": self.database_name,
                "school_inep_fk": self.school_inep_fk,
                "classroom_id": self.classroom_id,
                "additional_filters_count": len(self.additional_filters),
            },
        )

    def to_context(self) -> Dict[str, str]:
        """Converts filter combination to template context dictionary"""
        context = {
            "database_name": self.database_name,
            "school_inep_fk": self.school_inep_fk,
            "classroom_id": self.classroom_id,
        }
        context.update(self.additional_filters)
        return context

    def get_unique_identifier(self) -> str:
        """Returns a unique identifier for this filter combination"""
        import hashlib

        context = self.to_context()
        context_str = "_".join(f"{k}_{v}" for k, v in sorted(context.items()))
        return hashlib.md5(context_str.encode()).hexdigest()[:8]

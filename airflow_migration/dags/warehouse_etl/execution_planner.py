from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

from airflow_migration.utils.logs.logging_functions import get_logger
from .warehouse_basic_config import WorkflowConfig, Stage, TableLoad
from .yaml_loader import TableConfig, IncrementalConfig, UpsertConfig
from .dependecy_validator import DependencyValidator, DependencyError


class InvalidWorkflowError(Exception):
    """Raised when the workflow configuration has dependency errors."""

    def __init__(self, message: str, errors: List[DependencyError]):
        super().__init__(message)
        self.errors = errors


@dataclass
class TableExecution:
    """Represents a single table execution with all necessary context"""

    table_name: str
    stage: int
    database: str
    source_name: str  # Can be placeholder {SOURCE_NAME} or resolved value
    target_schema: str  # Can be placeholder {TARGET_SCHEMA} or fixed value like 'raw'
    trigger: str
    model: str
    sql_path: str
    incremental_config: IncrementalConfig
    upsert_config: UpsertConfig
    execution_context: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Add metadata to execution context"""
        self.execution_context.update(
            {
                "created_at": datetime.now().isoformat(),
                "needs_source_resolution": self.source_name == "{SOURCE_NAME}",
                "needs_schema_resolution": self.target_schema == "{TARGET_SCHEMA}",
                "is_fixed_schema": self.target_schema not in ["{TARGET_SCHEMA}"],
                "has_optional_filters": False,  # Will be updated later
            }
        )

    def get_unique_key(self) -> str:
        """Generate unique identifier for this execution"""
        return f"{self.table_name}_{self.database}_{self.stage}"


class ExecutionPlanner:
    """Generates execution plan respecting stages, dependencies, and databases"""

    def __init__(self, db_manager=None):
        """
        Initialize ExecutionPlanner

        Args:
            db_manager: Optional DatabaseConnectionManager for environment detection
        """
        self.logger = get_logger("execution_planner")
        self.db_manager = db_manager
        # Instancia o validador para uso interno
        self.validator = DependencyValidator()

    def generate_execution_plan(
            self,
            workflow_config: WorkflowConfig,
            table_configs: Dict[str, TableConfig],
            databases_list: List[str],
            environment: str = None,
        ) -> List[List[TableExecution]]:
            """
            Gera um plano de execução completo, fatiando os lotes para respeitar
            o limite de paralelismo definido em max_parallel_tasks.
            """
            # --- Bloco de Validação (continua o mesmo) ---
            is_valid, errors = self.validator.validate_dependencies(workflow_config)
            if not is_valid:
                # ... (código de erro continua o mesmo)
                raise InvalidWorkflowError(
                    f"Workflow configuration is invalid with {len(errors)} errors.",
                    errors=errors,
                )
            self.logger.info(
                "Workflow dependency validation passed. Proceeding with plan generation."
            )
            
            # --- Bloco de setup do ambiente (continua o mesmo) ---
            if environment is None and self.db_manager:
                environment = (
                    "prod"
                    if (self.db_manager.is_production or self.db_manager.hotfix_mode)
                    else "dev"
                )
            elif environment is None:
                environment = "dev"

            self.logger.info(
                "Generating execution plan",
                {
                    "workflow_name": workflow_config.workflow_name,
                    "environment": environment,
                    # A linha abaixo agora é usada como um limite
                    "max_parallel_tasks_limit": workflow_config.max_parallel_tasks,
                },
            )
            
            # =================================================================
            # LÓGICA DE GERAÇÃO DE LOTES ATUALIZADA
            # =================================================================
            execution_batches = []
            limit = workflow_config.max_parallel_tasks # Pega o limite do YAML

            for stage in sorted(workflow_config.stages, key=lambda s: s.stage):
                # 1. Gera o lote completo para o stage, como antes
                full_stage_batch = self._generate_stage_batch(
                    stage, table_configs, databases_list, environment
                )

                if full_stage_batch:
                    # 2. Se o lote gerado for maior que o limite, fatia ele
                    if len(full_stage_batch) > limit:
                        self.logger.info(f"Stage {stage.stage} batch exceeds limit ({len(full_stage_batch)} > {limit}). Chunking batch...")
                        # Usa uma técnica de fatiamento para criar sub-lotes
                        chunked_batches = [
                            full_stage_batch[i:i + limit] 
                            for i in range(0, len(full_stage_batch), limit)
                        ]
                        # Adiciona todos os sub-lotes ao plano de execução
                        execution_batches.extend(chunked_batches)
                    else:
                        # Se for menor ou igual ao limite, adiciona o lote inteiro
                        execution_batches.append(full_stage_batch)
            # =================================================================

            total_executions = sum(len(batch) for batch in execution_batches)
            self.logger.info(
                "Execution plan generated successfully",
                {
                    "workflow_name": workflow_config.workflow_name,
                    "batches_count": len(execution_batches), # Será maior agora
                    "total_executions": total_executions,
                    "environment": environment,
                    "max_parallel_per_batch": ( # Agora refletirá o limite
                        max(len(batch) for batch in execution_batches)
                        if execution_batches
                        else 0
                    ),
                },
            )

            return execution_batches

    def _generate_stage_batch(
        self,
        stage: Stage,
        table_configs: Dict[str, TableConfig],
        databases_list: List[str],
        environment: str,
    ) -> List[TableExecution]:
        """
        Generate execution batch for a single stage
        All executions in this batch can run in parallel
        """
        stage_executions = []

        for table_load in stage.loads:
            table_name = table_load.table_name

            if table_name not in table_configs:
                self.logger.error(
                    "Table configuration not found",
                    extra_data={
                        "table_name": table_name,
                        "stage": stage.stage,
                        "available_tables": list(table_configs.keys()),
                    },
                )
                continue

            table_config = table_configs[table_name]

            for database in databases_list:
                table_execution = self._create_table_execution(
                    table_load, table_config, database, environment
                )
                stage_executions.append(table_execution)

        self.logger.debug(
            "Stage batch generated",
            extra_data={
                "stage": stage.stage,
                "tables_count": len(stage.loads),
                "databases_count": len(databases_list),
                "executions_generated": len(stage_executions),
            },
        )

        return stage_executions

    def _create_table_execution(
        self,
        table_load: TableLoad,
        table_config: TableConfig,
        database: str,
        environment: str,
    ) -> TableExecution:
        """
        Create a single TableExecution object
        """
        source_name = table_config.source_name
        target_schema = table_config.target_schema

        execution_context = {
            "environment": environment,
            "database": database,
            "original_source_name": table_config.source_name,
            "original_target_schema": table_config.target_schema,
            "optional_filters": table_config.optional_filters.copy(),
            "filter_sources": table_config.filter_sources.copy(),
            "description": table_config.description,
        }

        table_execution = TableExecution(
            table_name=table_load.table_name,
            stage=table_load.stage,
            database=database,
            source_name=source_name,
            target_schema=target_schema,
            trigger=table_load.trigger,
            model=table_load.model,
            sql_path=table_config.sql_path,
            incremental_config=table_config.incremental_config,
            upsert_config=table_config.upsert_config,
            execution_context=execution_context,
        )

        has_filters = bool(table_config.optional_filters)
        table_execution.execution_context["has_optional_filters"] = has_filters

        self.logger.debug(
            "TableExecution created",
            extra_data={
                "table_name": table_load.table_name,
                "database": database,
                "stage": table_load.stage,
                "source_name": source_name,
                "target_schema": target_schema,
                "has_filters": has_filters,
                "unique_key": table_execution.get_unique_key(),
            },
        )

        return table_execution

    def get_execution_summary(
        self, execution_plan: List[List[TableExecution]]
    ) -> Dict[str, Any]:
        """
        Generate summary statistics for an execution plan
        """
        if not execution_plan:
            return {
                "total_batches": 0,
                "total_executions": 0,
                "tables": [],
                "databases": [],
                "stages": [],
                "max_parallel": 0,
            }

        all_executions = [exec for batch in execution_plan for exec in batch]
        tables = sorted(list(set(exec.table_name for exec in all_executions)))
        databases = sorted(list(set(exec.database for exec in all_executions)))
        stages = sorted(list(set(exec.stage for exec in all_executions)))

        stage_stats = {
            f"stage_{s}": {
                "executions_count": len([e for e in all_executions if e.stage == s])
            }
            for s in stages
        }

        summary = {
            "total_batches": len(execution_plan),
            "total_executions": len(all_executions),
            "tables": tables,
            "databases": databases,
            "stages": stages,
            "max_parallel": max(len(batch) for batch in execution_plan),
            "stage_statistics": stage_stats,
        }

        self.logger.info("Execution plan summary generated", summary)

        return summary

    def validate_execution_plan(
        self, execution_plan: List[List[TableExecution]]
    ) -> List[str]:
        """
        Validate the generated execution plan for potential issues
        """
        errors = []

        if not execution_plan:
            errors.append("Execution plan is empty")
            return errors

        all_executions = [exec for batch in execution_plan for exec in batch]

        unique_keys = set()
        for execution in all_executions:
            key = execution.get_unique_key()
            if key in unique_keys:
                errors.append(f"Duplicate execution found: {key}")
            unique_keys.add(key)

        stages_in_order = [exec.stage for batch in execution_plan for exec in batch]
        if stages_in_order != sorted(stages_in_order):
            errors.append(
                "Stages are not processed in ascending order within the plan."
            )

        for i, batch in enumerate(execution_plan):
            if not batch:
                continue
            batch_stage = batch[0].stage
            if not all(exec.stage == batch_stage for exec in batch):
                errors.append(f"Mixed stages found within batch {i}.")

        if errors:
            self.logger.error(
                "Execution plan validation failed", extra_data={"errors": errors}
            )
        else:
            self.logger.info("Execution plan validation passed")

        return errors

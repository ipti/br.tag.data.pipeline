from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict, deque
from dataclasses import dataclass

from airflow_migration.utils.logs.logging_functions import get_logger
from .warehouse_basic_config import WorkflowConfig, Stage, TableLoad


@dataclass
class DependencyError:
    """Represents a dependency validation error"""

    error_type: str
    table_name: str
    stage: int
    dependency: Optional[str] = None
    cycle_path: Optional[List[str]] = None
    message: str = ""

    def __post_init__(self):
        """Generate error message if not provided"""
        if not self.message:
            if self.error_type == "missing_table":
                self.message = f"Table '{self.table_name}' in stage {self.stage} depends on '{self.dependency}' which does not exist"
            elif self.error_type == "circular_dependency":
                cycle_str = (
                    " -> ".join(self.cycle_path) if self.cycle_path else "unknown"
                )
                self.message = f"Circular dependency detected involving table '{self.table_name}': {cycle_str}"
            elif self.error_type == "invalid_stage_dependency":
                self.message = f"Table '{self.table_name}' in stage {self.stage} depends on '{self.dependency}' which is in the same or later stage"
            elif self.error_type == "self_dependency":
                self.message = f"Table '{self.table_name}' in stage {self.stage} cannot depend on itself"


class DependencyValidator:
    """Validates dependency relationships in workflow configuration"""

    def __init__(self):
        """Initialize dependency validator"""
        self.logger = get_logger("dependency_validator")

    def validate_dependencies(
        self, workflow_config: WorkflowConfig
    ) -> Tuple[bool, List[DependencyError]]:
        """
        Validate all dependency relationships in the workflow

        Args:
            workflow_config: Workflow configuration to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        self.logger.info(
            "Starting dependency validation",
            {
                "workflow_name": workflow_config.workflow_name,
                "stages_count": len(workflow_config.stages),
                "total_tables": sum(
                    len(stage.loads) for stage in workflow_config.stages
                ),
            },
        )

        errors = []

        # Build table mappings
        table_to_stage, all_tables = self._build_table_mappings(workflow_config)

        # Validate stage order and dependencies
        errors.extend(
            self._validate_stage_dependencies(
                workflow_config, table_to_stage, all_tables
            )
        )

        # Detect circular dependencies
        errors.extend(self._detect_circular_dependencies(workflow_config, all_tables))

        is_valid = len(errors) == 0

        if is_valid:
            self.logger.info(
                "Dependency validation passed",
                {
                    "workflow_name": workflow_config.workflow_name,
                    "total_tables": len(all_tables),
                    "total_dependencies": self._count_total_dependencies(
                        workflow_config
                    ),
                },
            )
        else:
            self.logger.error(
                "Dependency validation failed",
                extra_data={
                    "workflow_name": workflow_config.workflow_name,
                    "errors_count": len(errors),
                    "error_types": [error.error_type for error in errors],
                },
            )

        return is_valid, errors

    def _build_table_mappings(
        self, workflow_config: WorkflowConfig
    ) -> Tuple[Dict[str, int], Set[str]]:
        """
        Build mappings of table names to their stages and set of all tables

        Args:
            workflow_config: Workflow configuration

        Returns:
            Tuple of (table_to_stage_mapping, all_tables_set)
        """
        table_to_stage = {}
        all_tables = set()

        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name

                if table_name in table_to_stage:
                    self.logger.warning(
                        "Duplicate table name found",
                        extra_data={
                            "table_name": table_name,
                            "existing_stage": table_to_stage[table_name],
                            "new_stage": stage.stage,
                        },
                    )

                table_to_stage[table_name] = stage.stage
                all_tables.add(table_name)

        self.logger.debug(
            "Table mappings built",
            extra_data={
                "total_tables": len(all_tables),
                "stages_with_tables": len(set(table_to_stage.values())),
            },
        )

        return table_to_stage, all_tables

    def _validate_stage_dependencies(
        self,
        workflow_config: WorkflowConfig,
        table_to_stage: Dict[str, int],
        all_tables: Set[str],
    ) -> List[DependencyError]:
        """
        Validate that dependencies respect stage ordering and exist

        Args:
            workflow_config: Workflow configuration
            table_to_stage: Mapping of table names to stage numbers
            all_tables: Set of all table names

        Returns:
            List of dependency errors found
        """
        errors = []

        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name
                current_stage = stage.stage

                for dependency in table_load.depends_on:
                    if dependency == table_name:
                        errors.append(
                            DependencyError(
                                error_type="self_dependency",
                                table_name=table_name,
                                stage=current_stage,
                                dependency=dependency,
                            )
                        )
                        continue

                    if dependency not in all_tables:
                        errors.append(
                            DependencyError(
                                error_type="missing_table",
                                table_name=table_name,
                                stage=current_stage,
                                dependency=dependency,
                            )
                        )
                        continue

                    dependency_stage = table_to_stage[dependency]
                    if dependency_stage >= current_stage:
                        errors.append(
                            DependencyError(
                                error_type="invalid_stage_dependency",
                                table_name=table_name,
                                stage=current_stage,
                                dependency=dependency,
                            )
                        )

        self.logger.debug(
            "Stage dependency validation completed",
            extra_data={
                "errors_found": len(errors),
                "error_types": [error.error_type for error in errors],
            },
        )

        return errors

    def _detect_circular_dependencies(
        self, workflow_config: WorkflowConfig, all_tables: Set[str]
    ) -> List[DependencyError]:
        """
        Detect circular dependencies using Depth-First Search (DFS)

        Args:
            workflow_config: Workflow configuration
            all_tables: Set of all table names

        Returns:
            List of circular dependency errors
        """
        # Build dependency graph
        dependency_graph = self._build_dependency_graph(workflow_config)

        errors = []
        visited = set()
        rec_stack = set()  # Recursion stack for DFS

        def dfs_detect_cycle(node: str, path: List[str]) -> Optional[List[str]]:
            """
            DFS to detect cycles in dependency graph

            Args:
                node: Current node being visited
                path: Current path from root

            Returns:
                List representing the cycle if found, None otherwise
            """
            if node in rec_stack:
                cycle_start_idx = path.index(node)
                cycle = path[cycle_start_idx:] + [node]
                return cycle

            if node in visited:
                return None

            visited.add(node)
            rec_stack.add(node)

            for neighbor in dependency_graph.get(node, []):
                if neighbor in all_tables:
                    cycle = dfs_detect_cycle(neighbor, path + [node])
                    if cycle:
                        return cycle

            rec_stack.remove(node)
            return None

        for table in all_tables:
            if table not in visited:
                cycle = dfs_detect_cycle(table, [])
                if cycle:
                    errors.append(
                        DependencyError(
                            error_type="circular_dependency",
                            table_name=cycle[0],
                            stage=self._get_table_stage(workflow_config, cycle[0]),
                            cycle_path=cycle,
                        )
                    )

        self.logger.debug(
            "Circular dependency detection completed",
            extra_data={
                "cycles_found": len(errors),
                "total_tables_checked": len(all_tables),
            },
        )

        return errors

    def _build_dependency_graph(
        self, workflow_config: WorkflowConfig
    ) -> Dict[str, List[str]]:
        """
        Build a directed graph of table dependencies

        Args:
            workflow_config: Workflow configuration

        Returns:
            Dictionary mapping table names to their dependencies
        """
        graph = defaultdict(list)

        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name
                for dependency in table_load.depends_on:
                    graph[table_name].append(dependency)

        self.logger.debug(
            "Dependency graph built",
            extra_data={
                "nodes_count": len(graph),
                "total_edges": sum(len(deps) for deps in graph.values()),
            },
        )

        return dict(graph)

    def _get_table_stage(self, workflow_config: WorkflowConfig, table_name: str) -> int:
        """
        Get the stage number for a given table

        Args:
            workflow_config: Workflow configuration
            table_name: Name of the table

        Returns:
            Stage number where the table is defined
        """
        for stage in workflow_config.stages:
            for table_load in stage.loads:
                if table_load.table_name == table_name:
                    return stage.stage
        return 0

    def _count_total_dependencies(self, workflow_config: WorkflowConfig) -> int:
        """
        Count total number of dependencies across all tables

        Args:
            workflow_config: Workflow configuration

        Returns:
            Total number of dependencies
        """
        total = 0
        for stage in workflow_config.stages:
            for table_load in stage.loads:
                total += len(table_load.depends_on)
        return total

    def get_dependency_summary(self, workflow_config: WorkflowConfig) -> Dict[str, any]:
        """
        Generate a summary of the dependency structure

        Args:
            workflow_config: Workflow configuration

        Returns:
            Dictionary with dependency statistics and information
        """
        table_to_stage, all_tables = self._build_table_mappings(workflow_config)
        dependency_graph = self._build_dependency_graph(workflow_config)

        tables_with_dependencies = sum(1 for deps in dependency_graph.values() if deps)
        tables_without_dependencies = len(all_tables) - tables_with_dependencies
        max_dependencies = max(
            (len(deps) for deps in dependency_graph.values()), default=0
        )

        root_tables = [
            table for table in all_tables if not dependency_graph.get(table, [])
        ]

        all_dependencies = set()
        for deps in dependency_graph.values():
            all_dependencies.update(deps)
        leaf_tables = [table for table in all_tables if table not in all_dependencies]

        summary = {
            "total_tables": len(all_tables),
            "total_dependencies": self._count_total_dependencies(workflow_config),
            "tables_with_dependencies": tables_with_dependencies,
            "tables_without_dependencies": tables_without_dependencies,
            "max_dependencies_per_table": max_dependencies,
            "root_tables": root_tables,
            "leaf_tables": leaf_tables,
            "stages_count": len(workflow_config.stages),
            "dependency_graph": dict(dependency_graph),
        }

        self.logger.info("Dependency summary generated", summary)

        return summary

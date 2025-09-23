from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
import yaml
import os
import sys

from airflow_migration.utils.logs.logging_functions import get_logger
from airflow_migration.dags.warehouse_etl.warehouse_basic_config import WorkflowConfig, TriggerConfig, Stage, TableLoad, TableConfig


class YAMLLoader:
    """Handles loading and validation of YAML configuration files"""
    
    def __init__(self, config_root: Optional[str] = None):
        """
        Initialize YAML Loader
        
        Args:
            config_root: Root directory for configuration files. If None, uses current directory
        """
        self.logger = get_logger("yaml_loader")
        self.config_root = Path(config_root) if config_root else Path.cwd()
        self.table_configs: Dict[str, TableConfig] = {}
        
        self.logger.info("YAMLLoader initialized", {
            "config_root": str(self.config_root),
            "config_root_exists": self.config_root.exists()
        })
        
    def load_workflow_config(self, workflow_file: str = "workflow.yml") -> WorkflowConfig:
        """
        Load main workflow configuration from YAML file
        
        Args:
            workflow_file: Name of the workflow YAML file
            
        Returns:
            WorkflowConfig object with validated configuration
            
        Raises:
            FileNotFoundError: If workflow file is not found
            ValueError: If configuration is invalid
            yaml.YAMLError: If YAML parsing fails
        """
        workflow_path = self.config_root / workflow_file
        
        if not workflow_path.exists():
            error_msg = f"Workflow configuration file not found: {workflow_path}"
            self.logger.error("Workflow file not found", extra_data={
                "workflow_path": str(workflow_path),
                "config_root": str(self.config_root),
                "error": error_msg
            })
            raise FileNotFoundError(error_msg)
            
        try:
            self.logger.info("Loading workflow configuration", {
                "workflow_file": str(workflow_path)
            })
            
            with open(workflow_path, 'r', encoding='utf-8') as f:
                raw_config = yaml.safe_load(f)
                
            if not isinstance(raw_config, dict):
                error_msg = "Workflow configuration must be a dictionary"
                self.logger.error("Invalid workflow structure", extra_data={
                    "config_type": type(raw_config),
                    "error": error_msg
                })
                raise ValueError(error_msg)
                
            triggers = self._parse_triggers(raw_config.get("triggers", {}))
            
            stages = self._parse_stages(raw_config.get("stages", []), triggers)
            
            workflow_config = WorkflowConfig(
                workflow_name=raw_config.get("workflow_name", ""),
                max_parallel_tasks=raw_config.get("max_parallel_tasks", 4),
                triggers=triggers,
                stages=stages
            )
            
            self.logger.info("Workflow configuration loaded successfully", {
                "workflow_name": workflow_config.workflow_name,
                "triggers_count": len(workflow_config.triggers),
                "stages_count": len(workflow_config.stages),
                "total_tables": sum(len(stage.loads) for stage in workflow_config.stages)
            })
            
            return workflow_config
            
        except yaml.YAMLError as e:
            error_msg = f"YAML parsing error in {workflow_file}: {str(e)}"
            self.logger.error("YAML parsing failed", exception=e, extra_data={
                "workflow_file": str(workflow_path),
                "error": error_msg
            })
            raise yaml.YAMLError(error_msg)
            
        except Exception as e:
            error_msg = f"Failed to load workflow configuration: {str(e)}"
            self.logger.error("Workflow loading failed", exception=e, extra_data={
                "workflow_file": str(workflow_path),
                "error": error_msg
            })
            raise ValueError(error_msg)
    
    def _parse_triggers(self, triggers_config: Dict[str, Any]) -> Dict[str, TriggerConfig]:
        """
        Parse triggers configuration from raw YAML
        
        Args:
            triggers_config: Raw triggers configuration dictionary
            
        Returns:
            Dictionary mapping trigger names to TriggerConfig objects
        """
        triggers = {}
        
        for trigger_name, trigger_data in triggers_config.items():
            if not isinstance(trigger_data, dict):
                error_msg = f"Trigger '{trigger_name}' configuration must be a dictionary"
                self.logger.error("Invalid trigger configuration", extra_data={
                    "trigger_name": trigger_name,
                    "trigger_data_type": type(trigger_data),
                    "error": error_msg
                })
                raise ValueError(error_msg)
                
            triggers[trigger_name] = TriggerConfig(
                name=trigger_name,
                schedule_interval=trigger_data.get("schedule_interval", ""),
                description=trigger_data.get("description", "")
            )
            
        self.logger.debug("Triggers parsed successfully", extra_data={
            "triggers_count": len(triggers),
            "trigger_names": list(triggers.keys())
        })
        
        return triggers
    
    def _parse_stages(self, stages_config: List[Any], triggers: Dict[str, TriggerConfig]) -> List[Stage]:
        """
        Parse stages configuration from raw YAML
        
        Args:
            stages_config: Raw stages configuration list
            triggers: Available triggers for validation
            
        Returns:
            List of Stage objects
        """
        if not isinstance(stages_config, list):
            error_msg = "Stages configuration must be a list"
            self.logger.error("Invalid stages configuration", extra_data={
                "stages_config_type": type(stages_config),
                "error": error_msg
            })
            raise ValueError(error_msg)
            
        stages = []
        
        for stage_data in stages_config:
            if not isinstance(stage_data, dict):
                error_msg = "Each stage configuration must be a dictionary"
                self.logger.error("Invalid stage configuration", extra_data={
                    "stage_data_type": type(stage_data),
                    "error": error_msg
                })
                raise ValueError(error_msg)
                
            stage_number = stage_data.get("stage")
            loads_config = stage_data.get("loads", [])
            
            loads = self._parse_table_loads(loads_config, triggers, stage_number)
            
            stages.append(Stage(
                stage=stage_number,
                loads=loads
            ))
            
        self.logger.debug("Stages parsed successfully", extra_data={
            "stages_count": len(stages),
            "stage_numbers": [stage.stage for stage in stages]
        })
        
        return stages
    
    def _parse_table_loads(self, loads_config: List[Any], triggers: Dict[str, TriggerConfig], stage_number: int) -> List[TableLoad]:
        """
        Parse table loads configuration from raw YAML
        
        Args:
            loads_config: Raw table loads configuration list
            triggers: Available triggers for validation
            stage_number: Current stage number for logging
            
        Returns:
            List of TableLoad objects
        """
        if not isinstance(loads_config, list):
            error_msg = f"Loads configuration in stage {stage_number} must be a list"
            self.logger.error("Invalid loads configuration", extra_data={
                "stage_number": stage_number,
                "loads_config_type": type(loads_config),
                "error": error_msg
            })
            raise ValueError(error_msg)
            
        loads = []
        
        for load_data in loads_config:
            if not isinstance(load_data, dict):
                error_msg = f"Each load configuration in stage {stage_number} must be a dictionary"
                self.logger.error("Invalid load configuration", extra_data={
                    "stage_number": stage_number,
                    "load_data_type": type(load_data),
                    "error": error_msg
                })
                raise ValueError(error_msg)
                
            table_name = load_data.get("table_name", "")
            trigger = load_data.get("trigger", "")
            
            if trigger not in triggers:
                error_msg = f"Unknown trigger '{trigger}' for table '{table_name}' in stage {stage_number}"
                self.logger.error("Invalid trigger reference", extra_data={
                    "table_name": table_name,
                    "trigger": trigger,
                    "stage_number": stage_number,
                    "available_triggers": list(triggers.keys()),
                    "error": error_msg
                })
                raise ValueError(error_msg)
            
            loads.append(TableLoad(
                table_name=table_name,
                model=load_data.get("model", ""),
                depends_on=load_data.get("depends_on", []),
                trigger=trigger,
                max_parallel_override=load_data.get("max_parallel_override")
            ))
            
        self.logger.debug("Table loads parsed successfully", extra_data={
            "stage_number": stage_number,
            "loads_count": len(loads),
            "table_names": [load.table_name for load in loads]
        })
        
        return loads
    
    def load_table_configs(self, workflow_config: WorkflowConfig) -> Dict[str, TableConfig]:
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
        self.logger.info("Loading table configurations", {
            "total_tables": sum(len(stage.loads) for stage in workflow_config.stages)
        })
        
        table_configs = {}
        missing_files = []
        
        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name
                model_path = table_load.model
                
                try:
                    table_config = self._load_single_table_config(table_name, model_path)
                    table_configs[table_name] = table_config
                    
                except FileNotFoundError as e:
                    missing_files.append(str(e))
                    self.logger.error("Table configuration file not found", extra_data={
                        "table_name": table_name,
                        "model_path": model_path,
                        "error": str(e)
                    })
                    
        if missing_files:
            error_msg = f"Missing configuration files:\n" + "\n".join(missing_files)
            self.logger.error("Multiple configuration files missing", extra_data={
                "missing_files_count": len(missing_files),
                "missing_files": missing_files
            })
            raise FileNotFoundError(error_msg)
            
        self.table_configs = table_configs
        
        self.logger.info("Table configurations loaded successfully", {
            "loaded_tables_count": len(table_configs),
            "table_names": list(table_configs.keys())
        })
        
        return table_configs
    
    def _load_single_table_config(self, table_name: str, model_path: str) -> TableConfig:
        """
        Load configuration for a single table
        
        Args:
            table_name: Name of the table
            model_path: Path to the table's YML configuration file
            
        Returns:
            TableConfig object with loaded configuration
            
        Raises:
            FileNotFoundError: If YML or SQL files are missing
            ValueError: If configuration is invalid
        """
        yml_path = self.config_root / model_path
        if not yml_path.exists():
            error_msg = f"YML configuration file not found for table '{table_name}': {yml_path}"
            raise FileNotFoundError(error_msg)
            
        sql_path = yml_path.with_suffix('.sql')
        if not sql_path.exists():
            error_msg = f"SQL file not found for table '{table_name}': {sql_path}"
            raise FileNotFoundError(error_msg)
            
        try:
            with open(yml_path, 'r', encoding='utf-8') as f:
                yml_config = yaml.safe_load(f)
                
            if not isinstance(yml_config, dict):
                error_msg = f"YML configuration for table '{table_name}' must be a dictionary"
                raise ValueError(error_msg)
                
            table_config = TableConfig(
                table_name=table_name,
                yml_config=yml_config,
                sql_path=str(sql_path)
            )
            
            self.logger.debug("Table configuration loaded", extra_data={
                "table_name": table_name,
                "yml_path": str(yml_path),
                "sql_path": str(sql_path),
                "yml_keys": list(yml_config.keys())
            })
            
            return table_config
            
        except yaml.YAMLError as e:
            error_msg = f"YAML parsing error in {yml_path}: {str(e)}"
            raise yaml.YAMLError(error_msg)
            
        except Exception as e:
            error_msg = f"Failed to load configuration for table '{table_name}': {str(e)}"
            raise ValueError(error_msg)
    
    def get_table_config(self, table_name: str) -> Optional[TableConfig]:
        """
        Get configuration for a specific table
        
        Args:
            table_name: Name of the table
            
        Returns:
            TableConfig object if found, None otherwise
        """
        return self.table_configs.get(table_name)
    
    def validate_file_structure(self, workflow_config: WorkflowConfig) -> List[str]:
        """
        Validate that all required files exist for the workflow
        
        Args:
            workflow_config: Workflow configuration to validate
            
        Returns:
            List of error messages (empty list if all files exist)
        """
        self.logger.info("Validating file structure for workflow")
        
        errors = []
        
        for stage in workflow_config.stages:
            for table_load in stage.loads:
                table_name = table_load.table_name
                model_path = table_load.model
                
                yml_path = self.config_root / model_path
                if not yml_path.exists():
                    errors.append(f"Missing YML file for table '{table_name}': {yml_path}")
                    
                sql_path = yml_path.with_suffix('.sql') if yml_path.exists() else self.config_root / f"{model_path.replace('.yml', '.sql')}"
                if not sql_path.exists():
                    errors.append(f"Missing SQL file for table '{table_name}': {sql_path}")
                    
        if errors:
            self.logger.error("File structure validation failed", extra_data={
                "errors_count": len(errors),
                "errors": errors
            })
        else:
            self.logger.info("File structure validation passed")
            
        return errors
import pytest

# Importe as classes do seu projeto. Ajuste os paths se necessário.
from airflow_migration.dags.warehouse_etl.execution_planner import ExecutionPlanner, TableExecution, InvalidWorkflowError
from airflow_migration.dags.warehouse_etl.warehouse_basic_config import (
    WorkflowConfig,
    Stage,
    TableLoad,
    TableConfig, 
    IncrementalConfig,
    UpsertConfig,
    TriggerConfig
)

from pathlib import Path


# --- Fixtures: Dados de teste reutilizáveis ---

@pytest.fixture
def dummy_incremental_config() -> IncrementalConfig:
    """Cria uma configuração incremental padrão para os testes."""
    return IncrementalConfig(
        source_timestamp_columns=["updated_at"],
        target_timestamp_column="dw_updated_at"
    )

@pytest.fixture
def dummy_upsert_config() -> UpsertConfig:
    """Cria uma configuração de upsert padrão para os testes."""
    return UpsertConfig(source_key_columns=["id"])

# ===================================================================================
# ALTERAÇÃO PRINCIPAL AQUI
# ===================================================================================
@pytest.fixture
def base_table_configs(
    tmp_path: Path, dummy_incremental_config: IncrementalConfig, dummy_upsert_config: UpsertConfig
) -> dict[str, TableConfig]:
    """
    Cria um dicionário de configs de tabela e os arquivos .sql temporários necessários.
    """
    # Passo 1: Crie arquivos .sql falsos (mas reais) no diretório temporário
    (tmp_path / "A.sql").touch()
    (tmp_path / "B.sql").touch()
    (tmp_path / "C.sql").touch()

    # Passo 2: Use os caminhos para esses arquivos temporários ao criar os TableConfig
    return {
        "table_A": TableConfig(table_name="table_A", description="Table A", source_name="src", target_schema="stg", yml_config={}, sql_path=str(tmp_path / "A.sql"), incremental_config=dummy_incremental_config, upsert_config=dummy_upsert_config, optional_filters=[], filter_sources={}),
        "table_B": TableConfig(table_name="table_B", description="Table B", source_name="src", target_schema="stg", yml_config={}, sql_path=str(tmp_path / "B.sql"), incremental_config=dummy_incremental_config, upsert_config=dummy_upsert_config, optional_filters=[], filter_sources={}),
        "table_C": TableConfig(table_name="table_C", description="Table C", source_name="src", target_schema="marts", yml_config={}, sql_path=str(tmp_path / "C.sql"), incremental_config=dummy_incremental_config, upsert_config=dummy_upsert_config, optional_filters=[], filter_sources={}),
    }
# ===================================================================================

@pytest.fixture
def databases_list() -> list[str]:
    """Retorna uma lista de databases para os testes."""
    return ["db_1", "db_2"]

# --- Testes (permanecem os mesmos) ---

def test_planner_initialization():
    """Testa se o ExecutionPlanner é inicializado corretamente."""
    planner = ExecutionPlanner()
    assert planner.validator is not None, "O validador de dependências deve ser inicializado."

def test_valid_plan_generation(base_table_configs, databases_list):
    """
    Testa a geração de um plano de execução para um workflow válido, sem limites de paralelismo apertados.
    """
    # Arrange
    workflow_config = WorkflowConfig(
        workflow_name="valid_workflow",
        max_parallel_tasks=10,
        triggers={"daily": TriggerConfig(name="daily", schedule_interval="@daily", description="")},
        stages=[
            Stage(stage=1, loads=[
                TableLoad(table_name="table_A", model="m", stage=1, depends_on=[], trigger="daily"),
                TableLoad(table_name="table_B", model="m", stage=1, depends_on=[], trigger="daily")
            ]),
            Stage(stage=2, loads=[
                TableLoad(table_name="table_C", model="m", stage=2, depends_on=["table_A"], trigger="daily")
            ]),
        ]
    )
    planner = ExecutionPlanner()
    
    # Act
    execution_plan = planner.generate_execution_plan(workflow_config, base_table_configs, databases_list)

    # Assert
    assert len(execution_plan) == 2, "Deve haver 2 lotes para os 2 stages"
    
    batch_1 = execution_plan[0]
    assert len(batch_1) == 4, "Stage 1 deve ter 4 execuções (2 tabelas x 2 databases)"
    assert {exec.table_name for exec in batch_1} == {"table_A", "table_B"}

    batch_2 = execution_plan[1]
    assert len(batch_2) == 2, "Stage 2 deve ter 2 execuções (1 tabela x 2 databases)"
    assert {exec.table_name for exec in batch_2} == {"table_C"}

def test_plan_generation_respects_max_parallel_tasks(base_table_configs, databases_list):
    """
    Testa se o planner fatia os lotes corretamente quando o paralelismo teórico excede o limite.
    """
    # Arrange
    workflow_config = WorkflowConfig(
        workflow_name="limited_workflow",
        max_parallel_tasks=2,
        triggers={"daily": TriggerConfig(name="daily", schedule_interval="@daily", description="")},
        stages=[
            Stage(stage=1, loads=[
                TableLoad(table_name="table_A", model="m", stage=1, depends_on=[], trigger="daily"),
                TableLoad(table_name="table_B", model="m", stage=1, depends_on=[], trigger="daily")
            ]),
            Stage(stage=2, loads=[
                TableLoad(table_name="table_C", model="m", stage=2, depends_on=["table_A"], trigger="daily")
            ]),
        ]
    )
    planner = ExecutionPlanner()

    # Act
    execution_plan = planner.generate_execution_plan(workflow_config, base_table_configs, databases_list)

    # Assert
    assert len(execution_plan) == 3, f"Esperado 3 lotes, mas foram gerados {len(execution_plan)}"
    
    for batch in execution_plan:
        assert len(batch) <= 2, f"Um lote excedeu o limite de paralelismo. Tamanho: {len(batch)}"

def test_raises_error_for_circular_dependency(base_table_configs, databases_list):
    """Testa se o planner falha ao receber um workflow com dependência circular."""
    # Arrange
    workflow_config = WorkflowConfig(
        workflow_name="circular_workflow",
        max_parallel_tasks=10,
        triggers={"daily": TriggerConfig(name="daily", schedule_interval="@daily", description="")},
        stages=[
            Stage(stage=1, loads=[
                TableLoad(table_name="table_A", model="m", stage=1, depends_on=["table_C"], trigger="daily")
            ]),
            Stage(stage=2, loads=[
                TableLoad(table_name="table_C", model="m", stage=2, depends_on=["table_A"], trigger="daily")
            ]),
        ]
    )
    planner = ExecutionPlanner()
    
    # Act & Assert
    with pytest.raises(InvalidWorkflowError) as excinfo:
        planner.generate_execution_plan(workflow_config, base_table_configs, databases_list)
    
    assert "circular_dependency" in [error.error_type for error in excinfo.value.errors]

def test_raises_error_for_invalid_stage_dependency(base_table_configs, databases_list):
    """Testa se o planner falha quando uma dependência aponta para um stage futuro."""
    # Arrange
    workflow_config = WorkflowConfig(
        workflow_name="bad_stage_workflow",
        max_parallel_tasks=10,
        triggers={"daily": TriggerConfig(name="daily", schedule_interval="@daily", description="")},
        stages=[
            Stage(stage=1, loads=[
                TableLoad(table_name="table_A", model="m", stage=1, depends_on=["table_C"], trigger="daily")
            ]),
            Stage(stage=2, loads=[
                TableLoad(table_name="table_C", model="m", stage=2, depends_on=[], trigger="daily")
            ]),
        ]
    )
    planner = ExecutionPlanner()

    # Act & Assert
    with pytest.raises(InvalidWorkflowError) as excinfo:
        planner.generate_execution_plan(workflow_config, base_table_configs, databases_list)
        
    assert "invalid_stage_dependency" in [error.error_type for error in excinfo.value.errors]
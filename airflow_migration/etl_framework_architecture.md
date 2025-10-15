# Framework de ETL Dinâmico - Guia de Manutenção

## 1. Visão Geral

Este framework automatiza a criação de DAGs do Airflow através de arquivos YAML declarativos, seguindo o princípio de **Configuration as Code**. Em vez de escrever código Python repetitivo para cada tabela, você define **o quê** fazer em YAML e o framework cuida do **como**.

### Fluxo de Trabalho

```
┌─────────────────────────────────────────────────────────┐
│                     BUILD TIME                          │
│  YAML Configs → Parsing → Planejamento → Geração DAGs  │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                      RUNTIME                            │
│  Airflow Trigger → Operator → SQL Render → ETL Load    │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Componentes Principais

### Build Time (Geração de DAGs)

| Componente | Responsabilidade |
|------------|------------------|
| **YAMLLoader** | Faz parsing e validação dos arquivos YAML, transformando-os em objetos Python tipados (dataclasses) |
| **ExecutionPlanner** | Constrói o grafo de dependências e organiza as tarefas em stages (sequenciais) e batches (paralelos) |
| **DagGenerator** | Gera os arquivos `.py` das DAGs na pasta `dags/` a partir do plano de execução |

### Runtime (Execução)

| Componente | Responsabilidade |
|------------|------------------|
| **WarehouseEtlOperator** | Operador Airflow que orquestra cada tarefa de ETL |
| **RuntimeEngine** | Renderiza queries SQL com templates Jinja2, preenchendo variáveis de contexto |
| **DatabaseConnectionManager** | Gerencia conexões com os bancos de dados (MySQL, SQL Server) |
| **CopyAndLoader** | Executa a extração, validação (quality checks) e carga dos dados |

---

## 3. Como Adicionar Nova Tabela ao ETL

### Passo 1: Criar Query SQL

Crie o arquivo em `config/warehouse_etl/tables/dim_customers.sql`:

```sql
SELECT 
    customer_id,
    customer_name,
    customer_email,
    registration_date,
    updated_at
FROM {{ database }}.customers
WHERE updated_at >= '{{ safe_timestamp }}'
  AND updated_at < '{{ execution_date }}'
```

### Passo 2: Criar Configuração YAML

Crie `config/warehouse_etl/tables/dim_customers.yml`:

```yaml
table_name: "dim_customers"
source_type: "mysql_crm"
source_database: "crm_production"

incremental_config:
  source_timestamp_columns: ["updated_at"]
  target_timestamp_column: "etl_loaded_at"

upsert_config:
  source_key_columns: ["customer_id"]

quality_checks:
  not_null: ["customer_id", "customer_email"]
  unique: ["customer_id"]
```

### Passo 3: Adicionar ao Workflow

Edite `config/warehouse_etl/workflow.yml`:

```yaml
stages:
  - stage: 1
    loads:
      - table_name: "dim_customers"
        model: "tables/dim_customers.yml"
        trigger: "incremental_hourly"
        depends_on: []
```

### Passo 4: Gerar DAG

```bash
python scripts/generate_dags.py
```

---

## 4. Como Adicionar Nova Característica a uma Tabela

Exemplo: adicionar um campo `delete_condition` para deletar registros antes do UPSERT.

### Passo 1: O "Contrato" (warehouse_basic_config.py)

Adicione o campo à dataclass `TableConfig`:

```python
@dataclass
class TableConfig:
    table_name: str
    source_type: str
    # ... outros campos existentes
    delete_condition: Optional[str] = None  # NOVO CAMPO
```

### Passo 2: O "Leitor" (yaml_loader.py)

Ensine o YAMLLoader a ler a nova chave:

```python
def _load_single_table_config(self, yml_path: str) -> TableConfig:
    with open(yml_path) as f:
        yml_config = yaml.safe_load(f)
    
    return TableConfig(
        table_name=yml_config["table_name"],
        source_type=yml_config["source_type"],
        # ... outros campos
        delete_condition=yml_config.get("delete_condition")  # LÊ A NOVA CHAVE
    )
```

### Passo 3: O "Planejador" (execution_planner.py)

Passe o valor para o objeto de execução:

**Adicione à dataclass:**
```python
@dataclass
class TableExecution:
    table_name: str
    # ... outros campos
    delete_condition: Optional[str] = None  # NOVO CAMPO
```

**Copie o valor no método de criação:**
```python
def _create_table_execution(self, table_config: TableConfig) -> TableExecution:
    return TableExecution(
        table_name=table_config.table_name,
        # ... outros campos
        delete_condition=table_config.delete_condition  # COPIA O VALOR
    )
```

### Passo 4: O "Consumidor" (writer.py)

Use a nova informação onde necessário:

```python
class CopyAndLoader:
    def incremental_load(
        self, 
        target_table: str,
        delete_condition: Optional[str] = None,  # NOVO PARÂMETRO
        **kwargs
    ):
        # Executa DELETE condicional antes da carga
        if delete_condition:
            delete_sql = f"DELETE FROM {target_table} WHERE {delete_condition}"
            self.db_manager.execute_query(delete_sql)
        
        # ... restante da lógica de carga
```

**Não esqueça de passar o parâmetro do Operator:**
```python
# Em warehouse_etl_operator.py
result = loader.incremental_load(
    target_table=self.table_config.table_name,
    delete_condition=self.table_config.delete_condition,  # PASSA O VALOR
    # ... outros parâmetros
)
```

### Uso no YAML

Agora você pode usar a nova característica:

```yaml
table_name: "dim_customers"
source_type: "mysql_crm"

delete_condition: "is_active = 0 AND DATEDIFF(day, updated_at, GETDATE()) > 365"

incremental_config:
  source_timestamp_columns: ["updated_at"]
  target_timestamp_column: "etl_loaded_at"

upsert_config:
  source_key_columns: ["customer_id"]
```

---

## 5. Como Adicionar Nova Característica a um Trigger

Exemplo: adicionar flag `run_as_high_priority` para controlar a prioridade da DAG.

### Passo 1: O "Contrato" (warehouse_basic_config.py)

```python
@dataclass
class TriggerConfig:
    schedule_interval: str
    catchup: bool
    # ... outros campos
    run_as_high_priority: bool = False  # NOVO CAMPO
```

### Passo 2: O "Leitor" (yaml_loader.py)

```python
def _parse_triggers(self, workflow_config: Dict) -> Dict[str, TriggerConfig]:
    triggers = {}
    
    for trigger_name, trigger_data in workflow_config["triggers"].items():
        triggers[trigger_name] = TriggerConfig(
            schedule_interval=trigger_data["schedule_interval"],
            catchup=trigger_data.get("catchup", False),
            # ... outros campos
            run_as_high_priority=trigger_data.get("run_as_high_priority", False)  # LÊ
        )
    
    return triggers
```

### Passo 3: O "Consumidor" (dag_generator.py)

Use a informação para configurar a DAG:

```python
def _generate_dag_file_content(self, trigger_config: TriggerConfig) -> str:
    # Define pool baseado na prioridade
    dag_pool = "high_priority_pool" if trigger_config.run_as_high_priority else "default_pool"
    
    dag_code = f'''
with DAG(
    dag_id="{self.dag_id}",
    schedule_interval="{trigger_config.schedule_interval}",
    catchup={trigger_config.catchup},
    pool="{dag_pool}",  # USA A NOVA CONFIGURAÇÃO
    max_active_runs=1,
    default_args={{...}}
) as dag:
    # ... definição das tasks
'''
    return dag_code
```

### Uso no YAML

Configure no `workflow.yml`:

```yaml
triggers:
  incremental_hourly:
    schedule_interval: "0 * * * *"
    catchup: false
    run_as_high_priority: true  # NOVA CONFIGURAÇÃO
    
  full_reload_daily:
    schedule_interval: "0 3 * * *"
    catchup: false
    run_as_high_priority: false

stages:
  - stage: 1
    loads:
      - table_name: "fact_sales"
        model: "tables/fact_sales.yml"
        trigger: "incremental_hourly"  # Usa a config de alta prioridade
        depends_on: []
```

---

## 6. Fluxo de Dados para Novas Features

### Para Features de Tabela:

```
TableConfig → YAMLLoader → ExecutionPlanner → TableExecution → Operator → CopyAndLoader
(Contrato)    (Leitura)    (Planejamento)     (Runtime)       (Uso)
```

### Para Features de Trigger:

```
TriggerConfig → YAMLLoader → DagGenerator → Código Python da DAG
(Contrato)      (Leitura)    (Geração)
```

---

## 7. Testes

### Testes Unitários

Sempre adicione testes ao criar novas features:

```python
# src/utils/tests/test_yaml_loader.py
def test_load_table_with_delete_condition():
    loader = YAMLLoader(config_root="tests/fixtures")
    table_config = loader.load_table("tables/test_table.yml")
    
    assert table_config.delete_condition == "status = 'inactive'"

# src/utils/tests/test_dag_generator.py
def test_generate_dag_with_high_priority():
    trigger_config = TriggerConfig(
        schedule_interval="0 * * * *",
        run_as_high_priority=True
    )
    
    dag_code = generator.generate_dag(trigger_config)
    
    assert 'pool="high_priority_pool"' in dag_code
```

Execute com:
```bash
pytest src/utils/tests/
```

### Testes Funcionais

```bash
# 1. Gerar DAGs
python scripts/generate_dags.py

# 2. Reiniciar Airflow
docker-compose down && docker-compose up -d

# 3. Testar DAG manualmente
airflow dags test warehouse_etl_incremental_hourly 2024-01-01

# 4. Trigger via UI ou CLI
airflow dags trigger warehouse_etl_incremental_hourly --conf '{"environment": "dev"}'
```

---

## 8. Troubleshooting

| Erro | Causa | Solução |
|------|-------|---------|
| **DAG not found / Failed to import** | Erro de sintaxe na DAG gerada ou inconsistência no metastore | `python scripts/generate_dags.py` e reiniciar. Se persistir: `docker-compose down --volumes` |
| **FileNotFoundError** | Caminho incorreto para arquivo `.sql` | Verificar variável `etl_config_root_path` no Airflow (`/opt/airflow/config/warehouse_etl`) e nome do arquivo no YAML |
| **Invalid column name** | Colunas do SELECT não correspondem ao schema da tabela destino | Ajustar aliases (`AS`) e casts (`CAST`) na query SQL para corresponder ao `CREATE TABLE` |
| **AttributeError: 'TableConfig' object has no attribute 'X'** | Campo novo não foi adicionado em todos os passos | Revisar os 4 passos: Contrato → Leitor → Planejador → Consumidor |

---

## 9. Checklist para Nova Feature

- [ ] **Passo 1**: Adicionar campo à dataclass em `warehouse_basic_config.py`
- [ ] **Passo 2**: Implementar leitura em `yaml_loader.py`
- [ ] **Passo 3**: Propagar valor em `execution_planner.py` (se feature de tabela)
- [ ] **Passo 4**: Implementar lógica de uso no componente consumidor
- [ ] **Testes**: Adicionar testes unitários em `src/utils/tests/`
- [ ] **Documentação**: Atualizar este documento com exemplo de uso
- [ ] **Validação**: Testar em ambiente dev antes de prod
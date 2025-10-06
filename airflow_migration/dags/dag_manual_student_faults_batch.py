from __future__ import annotations

import pendulum
from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from airflow.utils.task_group import TaskGroup
from airflow.models.baseoperator import chain

# Importe os componentes do seu framework
from utils.connections.connection_manager import DatabaseConnectionManager
from utils.connections.writer import CopyAndLoader
from utils.runtime.runtime_engine import render_sql_template
from utils.planner.execution_planner import TableExecution

# --- Constantes de Configuração ---
MONTH_GROUPS = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]
# Caminho para o arquivo SQL que busca a lista de trabalho
GET_WORK_LIST_SQL_PATH = "student_faults/get_classrooms.sql"

# --- Funções Python que serão as Tarefas ---

def get_work_list_func(ti, sql_path: str) -> None:
    """Busca a lista de (classroom_id, school_inep_fk) do DWH para o loop."""
    print(f"Buscando lista de trabalho da query em: {sql_path}")
    db_manager = DatabaseConnectionManager(environment="prod")
    mock_execution = TableExecution(sql_path=sql_path, execution_context={})
    query = render_sql_template(mock_execution)
    
    work_list = db_manager.execute_sqlserver_query(query)

    if not work_list:
        raise ValueError("Nenhuma sala de aula encontrada na query de busca.")
    
    print(f"Encontrados {len(work_list)} itens para processar.")
    ti.xcom_push(key="work_list", value=work_list)

def process_items_func(ti, upstream_task_id: str, sql_template_path: str, target_table: str, months: tuple) -> None:
    """Itera sobre a lista de itens (salas de aula) e processa cada um."""
    work_list = ti.xcom_pull(task_ids=upstream_task_id, key="work_list")
    if not work_list:
        print("Nenhuma lista de trabalho para processar. Finalizando.")
        return

    db_manager = DatabaseConnectionManager(environment="prod")
    copy_loader = CopyAndLoader(db_manager=db_manager)

    for item in work_list:
        item_dict = dict(item)
        print(f"Processando item: {item_dict}, meses: {months}")

        # O contexto agora é mais simples, sem 'database_name'
        mock_execution = TableExecution(
            sql_path=sql_template_path,
            execution_context={
                "id": item_dict['id'],
                "school_inep_fk": item_dict['school_inep_fk'],
                "months": months
            }
        )
        final_sql = render_sql_template(mock_execution)
        
        # A carga agora é de SQL Server para SQL Server
        result = copy_loader.batch_loader(
            source_type="sqlserver",
            source_query=final_sql,
            target_schema="raw",
            target_table=target_table,
        )
        
        if not result.success:
            raise AirflowException(f"Falha ao carregar dados para o item {item_dict}. Erro: {result.error_message}")
        
        print(f"Carga para o item {item_dict} concluída. Linhas processadas: {result.rows_processed}")

# --- Função Fábrica para criar os TaskGroups ---

def create_processing_group(group_id: str, months: tuple) -> TaskGroup:
    """Cria um TaskGroup completo para um bloco de meses."""
    with TaskGroup(group_id=group_id) as tg:
        
        get_work_list = PythonOperator(
            task_id="get_work_list",
            python_callable=get_work_list_func,
            op_kwargs={"sql_path": GET_WORK_LIST_SQL_PATH},
        )

        process_elementary = PythonOperator(
            task_id="process_elementary_faults",
            python_callable=process_items_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.get_work_list",
                "sql_template_path": "student_faults/student_faults_elementary.sql",
                "target_table": "student_faults_elementary_target",
                "months": months,
            },
        )
        
        process_fundamental = PythonOperator(
            task_id="process_fundamental_faults",
            python_callable=process_items_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.get_work_list",
                "sql_template_path": "student_faults/student_faults_fundamental.sql",
                "target_table": "student_faults_fundamental_target",
                "months": months,
            },
        )

        process_f_class = PythonOperator(
            task_id="process_f_class",
            python_callable=process_items_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.get_work_list",
                "sql_template_path": "student_faults/f_class.sql",
                "target_table": "f_class_target",
                "months": months,
            },
        )

        get_work_list >> [process_elementary, process_fundamental] >> process_f_class

    return tg


with DAG(
    dag_id="manual_batch_student_faults_v3",
    start_date=pendulum.datetime(2025, 10, 6, tz="UTC"),
    schedule=None,
    catchup=False,
    tags=['manual', 'batch', 'student_faults'],
    doc_md="DAG manual para processar faltas de estudantes em blocos de meses sequenciais.",
) as dag:
    
    processing_groups = []
    
    for months in MONTH_GROUPS:
        group_id = f"process_months_{'_'.join(map(str, months))}"
        group = create_processing_group(group_id=group_id, months=months)
        processing_groups.append(group)
        
    chain(*processing_groups)
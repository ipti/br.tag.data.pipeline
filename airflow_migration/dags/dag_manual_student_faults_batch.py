from __future__ import annotations
from typing import Dict, Any
import pandas as pd
from pathlib import Path

import pendulum
from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from airflow.utils.task_group import TaskGroup
from airflow.models.baseoperator import chain
from airflow.models import Variable

# Importa os componentes do seu framework
from utils.connections.connection_manager import DatabaseConnectionManager
from utils.connections.writer import CopyAndLoader
from utils.runtime.runtime_engine import render_sql_template

# --- Constantes de Configuração da DAG ---
TIMEZONE = "America/Sao_Paulo"
SQL_SUBDIRECTORY = "student_faults"
WORK_LIST_CSV_NAME = "classroom_ids_and_schools.csv"
MONTH_GROUPS = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]

# --- Funções Python que serão as Tarefas ---

def export_work_list_to_csv(ti, sql_path: str) -> None:
    """
    Fetches the work list from the DWH and saves it as a CSV file in a
    shared location, pushing the file path to XComs.
    """
    print(f"Fetching work list from query at: {sql_path}")
    db_manager = DatabaseConnectionManager(environment="prod")
    
    query = render_sql_template(sql_path=sql_path, execution_context={})
    
    sqlalchemy_results = db_manager.execute_sqlserver_query(query)
    if not sqlalchemy_results:
        raise ValueError("No items found from the controller query.")

    work_list = [dict(row._mapping) for row in sqlalchemy_results]
    df = pd.DataFrame(work_list)

    config_root = Variable.get("etl_config_root_path")
    output_dir = Path(config_root) / SQL_SUBDIRECTORY
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_file_path = output_dir / WORK_LIST_CSV_NAME
    
    print(f"Found {len(df)} items to process. Saving to: {csv_file_path}")
    df.to_csv(csv_file_path, index=False)
    
    ti.xcom_push(key="work_list_path", value=str(csv_file_path))


def process_items_from_csv_func(ti, upstream_task_id: str, sql_template_path: str, target_table: str, months: tuple) -> None:
    """
    Reads the work list from an intermediate CSV file, iterates through each
    item, and processes it.
    """
    csv_file_path = ti.xcom_pull(task_ids=upstream_task_id, key="work_list_path")
    if not csv_file_path:
        print("No work list path found in XComs. Finishing.")
        return

    print(f"Reading work list from CSV file: {csv_file_path}")
    work_df = pd.read_csv(csv_file_path)
    work_list = work_df.to_dict('records')

    db_manager = DatabaseConnectionManager(environment="prod")
    copy_loader = CopyAndLoader(db_manager=db_manager)

    for item in work_list:
        print(f"Processing item: {item}, for months: {months}")

        context = {
            "id": item.get('id'),
            "school_inep_fk": item.get('school_inep_fk'),
            "months": months
        }
        
        final_sql = render_sql_template(sql_path=sql_template_path, execution_context=context)
        
        result = copy_loader.batch_loader(
            source_type="sqlserver",
            source_query=final_sql,
            target_schema="raw",
            target_table=target_table,
        )
        
        if not result.success:
            raise AirflowException(f"Failed to load data for item {item}. Error: {result.error_message}")
        
        print(f"Load for item {item} complete. Rows processed: {result.rows_processed}")

# --- Função "Fábrica" para criar os TaskGroups ---

def create_processing_group(group_id: str, months: tuple) -> TaskGroup:
    """Cria um TaskGroup completo para um bloco de meses."""
    with TaskGroup(group_id=group_id) as tg:
        
        export_work_list = PythonOperator(
            task_id="export_work_list_to_csv",
            python_callable=export_work_list_to_csv,
            op_kwargs={"sql_path": f"{SQL_SUBDIRECTORY}/get_classrooms.sql"},
        )

        process_elementary_faults = PythonOperator(
            task_id="process_elementary_faults",
            python_callable=process_items_from_csv_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.export_work_list_to_csv",
                "sql_template_path": f"{SQL_SUBDIRECTORY}/student_faults_elementary.sql",
                "target_table": "student_faults_elementary_target",
                "months": months,
            },
        )
        
        process_fundamental_faults = PythonOperator(
            task_id="process_fundamental_faults",
            python_callable=process_items_from_csv_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.export_work_list_to_csv",
                "sql_template_path": f"{SQL_SUBDIRECTORY}/student_faults_fundamental.sql",
                "target_table": "student_faults_fundamental_target",
                "months": months,
            },
        )

        process_f_class = PythonOperator(
            task_id="process_f_class",
            python_callable=process_items_from_csv_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.export_work_list_to_csv",
                "sql_template_path": f"{SQL_SUBDIRECTORY}/f_class.sql",
                "target_table": "f_class_target",
                "months": months,
            },
        )

        # Ordem de execução DENTRO do grupo
        export_work_list >> [process_elementary_faults, process_fundamental_faults] >> process_f_class

    return tg

# --- Definição da DAG Principal ---
with DAG(
    dag_id="manual_student_faults_batch",
    start_date=pendulum.datetime(2025, 10, 6, tz=TIMEZONE),
    schedule=None,
    catchup=False,
    tags=['manual', 'batch', 'student_faults'],
    doc_md="DAG manual para processar faltas de estudantes em blocos de meses sequenciais."
) as dag:
    
    processing_groups = []
    
    for months in MONTH_GROUPS:
        group_id = f"process_months_{'_'.join(map(str, months))}"
        group = create_processing_group(group_id=group_id, months=months)
        processing_groups.append(group)
        
    # Define a ordem de execução sequencial ENTRE os TaskGroups
    chain(*processing_groups)
from __future__ import annotations
from typing import Dict, Any, List

import pendulum
from datetime import timedelta
import pandas as pd
from pathlib import Path
from airflow.models.dag import DAG
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowException
from airflow.utils.task_group import TaskGroup
from airflow.models.baseoperator import chain
from airflow.models import Variable

from utils.connections.connection_manager import DatabaseConnectionManager
from utils.connections.writer import CopyAndLoader, IncrementalConfig, UpsertConfig
from utils.runtime.runtime_engine import render_sql_template

TIMEZONE = "America/Sao_Paulo"
SQL_SUBDIRECTORY = "student_faults"
WORK_LIST_CSV_NAME = "classroom_ids_and_schools.csv"
MONTH_GROUPS = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]

default_args = {
    "owner": "airflow",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


def export_work_list_to_csv(ti, sql_path: str) -> None:
    """
    Fetches the work list from the DWH and saves it as a CSV file in a shared location.
    The file path is pushed to XComs for downstream tasks.

    This function:
        - Renders the SQL query using the provided template path.
        - Executes the query against SQL Server.
        - Converts the result to a DataFrame and saves it as CSV.
        - Pushes the CSV file path to XComs for use by other tasks.
    """
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
    df.to_csv(csv_file_path, index=False)
    ti.xcom_push(key="work_list_path", value=str(csv_file_path))


def process_items_upsert_func(
    ti,
    upstream_task_id: str,
    sql_template_path: str,
    target_table: str,
    months: tuple,
    upsert_keys: List[str],
) -> None:
    """
    Reads the work list from CSV, iterates through each item, and performs an UPSERT for each.

    This function:
        - Pulls the CSV file path from XComs.
        - Reads the CSV into a DataFrame and iterates over each row.
        - For each item, renders the SQL template with context and performs an incremental UPSERT.
        - Raises AirflowException if any load fails.
    """
    csv_file_path = ti.xcom_pull(task_ids=upstream_task_id, key="work_list_path")
    if not csv_file_path:
        return
    work_df = pd.read_csv(csv_file_path)
    work_list = work_df.to_dict("records")
    db_manager = DatabaseConnectionManager(environment="prod")
    copy_loader = CopyAndLoader(db_manager=db_manager)
    inc_config = IncrementalConfig(
        full_refresh=True, source_timestamp_columns=[], target_timestamp_column=""
    )
    ups_config = UpsertConfig(
        source_key_columns=upsert_keys, target_key_columns=upsert_keys
    )
    for item in work_list:
        context = {
            "id": item.get("id"),
            "school_inep_fk": item.get("school_inep_fk"),
            "months": months,
        }
        final_sql = render_sql_template(
            sql_path=sql_template_path, execution_context=context
        )
        result = copy_loader.incremental_load(
            source_type="sqlserver",
            source_query=final_sql,
            target_schema="dbo_tia",
            target_table=target_table,
            incremental_config=inc_config,
            upsert_config=ups_config,
        )
        if not result.success:
            raise AirflowException(
                f"Failed to load data for item {item}. Error: {result.error_message}"
            )


def create_processing_group(group_id: str, months: tuple) -> TaskGroup:
    """
    Creates a TaskGroup for a block of months, containing three PythonOperator tasks:
        - export_work_list_to_csv: Exports the work list to CSV.
        - process_elementary_faults: Processes elementary faults with UPSERT.
        - process_fundamental_faults: Processes fundamental faults with UPSERT.
        - process_f_class: Processes class faults with UPSERT.

    The dependencies are:
        export_work_list_to_csv >> [process_elementary_faults, process_fundamental_faults] >> process_f_class
    """
    with TaskGroup(group_id=group_id) as tg:
        export_work_list = PythonOperator(
            task_id="export_work_list_to_csv",
            python_callable=export_work_list_to_csv,
            op_kwargs={"sql_path": f"{SQL_SUBDIRECTORY}/get_classrooms.sql"},
        )
        process_elementary_faults = PythonOperator(
            task_id="process_elementary_faults",
            python_callable=process_items_upsert_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.export_work_list_to_csv",
                "sql_template_path": f"{SQL_SUBDIRECTORY}/student_faults_elementary.sql",
                "target_table": "F_STUDENT_CLASS",
                "months": months,
                "upsert_keys": ["HASH_ID"],
            },
        )
        process_fundamental_faults = PythonOperator(
            task_id="process_fundamental_faults",
            python_callable=process_items_upsert_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.export_work_list_to_csv",
                "sql_template_path": f"{SQL_SUBDIRECTORY}/student_faults_fundamental.sql",
                "target_table": "F_STUDENT_CLASS",
                "months": months,
                "upsert_keys": ["HASH_ID"],
            },
        )
        process_f_class = PythonOperator(
            task_id="process_f_class",
            python_callable=process_items_upsert_func,
            op_kwargs={
                "upstream_task_id": f"{group_id}.export_work_list_to_csv",
                "sql_template_path": f"{SQL_SUBDIRECTORY}/f_class.sql",
                "target_table": "F_CLASS",
                "months": months,
                "upsert_keys": ["HASH_ID"],
            },
        )
        (
            export_work_list
            >> [process_elementary_faults, process_fundamental_faults]
            >> process_f_class
        )
    return tg


with DAG(
    dag_id="manual_student_faults_batch",
    start_date=pendulum.datetime(2025, 10, 6, tz=TIMEZONE),
    schedule=None,
    catchup=False,
    tags=["manual", "batch", "student_faults"],
    doc_md="Manual DAG for processing student faults in sequential month blocks. Each TaskGroup processes a block of months and loads data into the warehouse using UPSERT logic.",
    default_args=default_args,
) as dag:
    """
    Defines the main DAG for manual batch processing of student faults.
    For each block of months, a TaskGroup is created to process the data.
    All TaskGroups are chained sequentially.
    """
    processing_groups = []
    for months in MONTH_GROUPS:
        group_id = f"process_months_{'_'.join(map(str, months))}"
        group = create_processing_group(group_id=group_id, months=months)
        processing_groups.append(group)

    chain(*processing_groups)

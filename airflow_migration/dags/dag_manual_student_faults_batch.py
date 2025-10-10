from __future__ import annotations
from typing import Dict, Any, List
import numpy as np

import pendulum
import pandas as pd
from pathlib import Path
from datetime import timedelta
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
MONTH_GROUPS = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (10, 11, 12)]

NUM_CHUNKS_ELEMENTARY = 3
NUM_CHUNKS_FUNDAMENTAL = 3
NUM_CHUNKS_FCLASS = 5

DEFAULT_ARGS = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def export_work_list_to_csv(ti, controller_sql_path: str, output_csv_name: str) -> None:
    """
    Executes a SQL query to fetch a work list from the data warehouse and saves it as a CSV file.
    The CSV file path is pushed to XCom for downstream tasks.

    Args:
        ti: Airflow TaskInstance for XCom communication.
        controller_sql_path (str): Path to the SQL template for fetching the work list.
        output_csv_name (str): Name of the output CSV file.

    Raises:
        ValueError: If no results are returned from the query.

    Example:
        export_work_list_to_csv(ti, "student_faults/get_classrooms_elementary.sql", "work_list_elementary_process_months_1_2_3.csv")
    """
    db_manager = DatabaseConnectionManager(environment="prod")
    query = render_sql_template(sql_path=controller_sql_path, execution_context={})
    sqlalchemy_results = db_manager.execute_sqlserver_query(query)
    if not sqlalchemy_results:
        ti.xcom_push(key="work_list_path", value=None)
        return

    work_list = [dict(row._mapping) for row in sqlalchemy_results]
    df = pd.DataFrame(work_list)
    config_root = Variable.get("etl_config_root_path")
    output_dir = Path(config_root) / SQL_SUBDIRECTORY
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_file_path = output_dir / output_csv_name
    df.to_csv(csv_file_path, index=False)
    ti.xcom_push(key="work_list_path", value=str(csv_file_path))


def process_csv_with_chunks(
    ti,
    upstream_task_id: str,
    sql_template_path: str,
    target_table: str,
    months: tuple,
    upsert_keys: List[str],
    num_chunks: int,
    chunk_index: int,
) -> None:
    """
    Processes a chunk of items from a work list CSV file, performing UPSERT operations for each item.

    This function:
        - Reads the CSV file path from XCom.
        - Loads the CSV and splits the work list into chunks for parallel processing.
        - For each item in the assigned chunk, renders the SQL template and performs an incremental UPSERT.
        - Raises AirflowException if any load fails.

    Args:
        ti: Airflow TaskInstance for XCom communication.
        upstream_task_id (str): Task ID that produced the CSV file.
        sql_template_path (str): Path to the SQL template for data extraction.
        target_table (str): Target table for UPSERT.
        months (tuple): Tuple of months to process.
        upsert_keys (List[str]): Keys for UPSERT operation.
        num_chunks (int): Total number of chunks for parallelism.
        chunk_index (int): Index of the chunk to process.

    Example:
        process_csv_with_chunks(ti, "group.elementary_stream.export_elementary_list", "student_faults_elementary.sql", "F_STUDENT_CLASS", (1,2,3), ["HASH_ID"], 3, 0)
    """
    csv_file_path = ti.xcom_pull(task_ids=upstream_task_id, key="work_list_path")
    if not csv_file_path or not Path(csv_file_path).exists():
        return

    work_df = pd.read_csv(csv_file_path)
    work_list = work_df.to_dict("records")
    chunked_list = np.array_split(work_list, num_chunks)
    if chunk_index >= len(chunked_list):
        return
    my_chunk = (
        chunked_list[chunk_index].tolist() if chunked_list[chunk_index].size > 0 else []
    )
    if not my_chunk:
        return

    db_manager = DatabaseConnectionManager(environment="prod")
    copy_loader = CopyAndLoader(db_manager=db_manager)
    inc_config = IncrementalConfig(
        full_refresh=True, source_timestamp_columns=[], target_timestamp_column=""
    )
    ups_config = UpsertConfig(
        source_key_columns=upsert_keys, target_key_columns=upsert_keys
    )

    for item in my_chunk:
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


with DAG(
    dag_id="manual_student_faults_batch",
    start_date=pendulum.datetime(2025, 10, 8, tz=TIMEZONE),
    schedule=None,
    catchup=False,
    tags=["manual", "batch", "student_faults"],
    default_args=DEFAULT_ARGS,
) as dag:
    """
    Defines the main DAG for manual batch processing of student faults.
    For each block of months, a TaskGroup is created for each stream (elementary, fundamental, f_class).
    Each stream exports a work list and processes it in parallel chunks.
    After elementary and fundamental streams finish, the f_class stream is triggered.
    All TaskGroups are chained sequentially for each block of months.
    """
    processing_groups = []

    for months in MONTH_GROUPS:
        group_id = f"process_months_{'_'.join(map(str, months))}"

        with TaskGroup(group_id=group_id) as tg:

            with TaskGroup(group_id="elementary_stream") as elementary_stream:
                export_list = PythonOperator(
                    task_id="export_elementary_list",
                    python_callable=export_work_list_to_csv,
                    op_kwargs={
                        "controller_sql_path": f"{SQL_SUBDIRECTORY}/get_classrooms_elementary.sql",
                        "output_csv_name": f"work_list_elementary_{group_id}.csv",
                    },
                )
                chunk_tasks = []
                for chunk_idx in range(NUM_CHUNKS_ELEMENTARY):
                    chunk_task = PythonOperator(
                        task_id=f"process_elementary_chunk_{chunk_idx}",
                        python_callable=process_csv_with_chunks,
                        op_kwargs={
                            "upstream_task_id": f"{group_id}.elementary_stream.export_elementary_list",
                            "sql_template_path": f"{SQL_SUBDIRECTORY}/student_faults_elementary.sql",
                            "target_table": "F_STUDENT_CLASS",
                            "months": months,
                            "upsert_keys": ["HASH_ID"],
                            "num_chunks": NUM_CHUNKS_ELEMENTARY,
                            "chunk_index": chunk_idx,
                        },
                    )
                    chunk_tasks.append(chunk_task)
                export_list >> chunk_tasks

            with TaskGroup(group_id="fundamental_stream") as fundamental_stream:
                export_list = PythonOperator(
                    task_id="export_fundamental_list",
                    python_callable=export_work_list_to_csv,
                    op_kwargs={
                        "controller_sql_path": f"{SQL_SUBDIRECTORY}/get_classrooms_fundamental.sql",
                        "output_csv_name": f"work_list_fundamental_{group_id}.csv",
                    },
                )
                chunk_tasks = []
                for chunk_idx in range(NUM_CHUNKS_FUNDAMENTAL):
                    chunk_task = PythonOperator(
                        task_id=f"process_fundamental_chunk_{chunk_idx}",
                        python_callable=process_csv_with_chunks,
                        op_kwargs={
                            "upstream_task_id": f"{group_id}.fundamental_stream.export_fundamental_list",
                            "sql_template_path": f"{SQL_SUBDIRECTORY}/student_faults_fundamental.sql",
                            "target_table": "F_STUDENT_CLASS",
                            "months": months,
                            "upsert_keys": ["HASH_ID"],
                            "num_chunks": NUM_CHUNKS_FUNDAMENTAL,
                            "chunk_index": chunk_idx,
                        },
                    )
                    chunk_tasks.append(chunk_task)
                export_list >> chunk_tasks

            with TaskGroup(group_id="f_class_stream") as f_class_stream:
                export_list = PythonOperator(
                    task_id="export_fclass_list",
                    python_callable=export_work_list_to_csv,
                    op_kwargs={
                        "controller_sql_path": f"{SQL_SUBDIRECTORY}/get_classrooms_general.sql",
                        "output_csv_name": f"work_list_fclass_{group_id}.csv",
                    },
                )
                chunk_tasks = []
                for chunk_idx in range(NUM_CHUNKS_FCLASS):
                    chunk_task = PythonOperator(
                        task_id=f"process_fclass_chunk_{chunk_idx}",
                        python_callable=process_csv_with_chunks,
                        op_kwargs={
                            "upstream_task_id": f"{group_id}.f_class_stream.export_fclass_list",
                            "sql_template_path": f"{SQL_SUBDIRECTORY}/f_class.sql",
                            "target_table": "F_CLASS",
                            "months": months,
                            "upsert_keys": ["HASH_ID"],
                            "num_chunks": NUM_CHUNKS_FCLASS,
                            "chunk_index": chunk_idx,
                        },
                    )
                    chunk_tasks.append(chunk_task)
                export_list >> chunk_tasks

            [elementary_stream, fundamental_stream] >> f_class_stream

        processing_groups.append(tg)

    if processing_groups:
        chain(*processing_groups)

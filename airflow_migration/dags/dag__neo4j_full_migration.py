"""
DAG: Neo4j Full Migration.

Orchestrates the migration of data from the SQL Warehouse to Neo4j.
Strategy:
1. Extract nodes (Student, School, Classroom) via streaming.
2. Load nodes into Neo4j using UNWIND batches.
3. Extract relationships (Enrollment, Class-School) via streaming.
4. Link nodes in Neo4j using MATCH/MERGE.
"""
from datetime import datetime, timedelta
import logging

from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.mysql.hooks.mysql import MySqlHook

from src.utils.neo4j.ingestor import Neo4jIngestor
import src.utils.neo4j.queries as q

# Default arguments for the DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def stream_to_neo4j(sql_query: str, cypher_query: str, batch_size: int = 2000, transformer: callable = None, **kwargs):
    """
    Generic function to stream from SQL and load to Neo4j.
    
    Args:
        sql_query (str): SQL query to execute on the source database.
        cypher_query (str): Cypher query for ingestion into Neo4j.
        batch_size (int): Number of records per batch.
        transformer (callable): Optional function to transform each row (dict) before ingestion.
    """
    logger = logging.getLogger(__name__)
    
    # Initialize implementation-specific hook
    # Note: Replace 'warehouse_staging' with the actual connection ID
    try:
        mysql_hook = MySqlHook(mysql_conn_id='warehouse_staging') 
        conn = mysql_hook.get_conn()
        cursor = conn.cursor()
    except Exception as e:
        logger.error(f"Failed to connect to MySQL: {e}")
        raise e

    ingestor = Neo4jIngestor(batch_size=batch_size)
    
    logger.info(f"Executing SQL: {sql_query}")
    try:
        cursor.execute(sql_query)
        
        # Fetch column names to map rows to dictionaries
        if cursor.description:
            columns = [col[0] for col in cursor.description]
        else:
            logger.warning("No columns returned from query.")
            return

        while True:
            rows = cursor.fetchmany(batch_size)
            if not rows:
                break
            
            # Convert tuple rows to list of dicts key-value pairs
            data = [dict(zip(columns, row)) for row in rows]
            
            # Apply transformation if provided
            if transformer:
                data = [transformer(row) for row in data]
            
            # Ingest batch
            ingestor.ingest_data(cypher_query, data)
            
    except Exception as e:
        logger.error(f"Error during streaming: {e}")
        raise e
    finally:
        ingestor.close()
        cursor.close()
        conn.close()

with DAG(
    'neo4j_full_migration',
    default_args=default_args,
    description='Migrates dbo_tia to Neo4j',
    schedule_interval=None, # Manual trigger for now
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['neo4j', 'migration'],
) as dag:

    # 1. Load Nodes (Parallel Extraction)
    
    # d_student has F_HASH_ID which is the student ID (si.id)
    load_students = PythonOperator(
        task_id='load_students',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': 'SELECT F_HASH_ID as id, name, birth_city, gender, ethnicity, deficiency, inserted_at as updated_at FROM d_student',
            'cypher_query': q.MERGE_STUDENT
        }
    )

    load_schools = PythonOperator(
        task_id='load_schools',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': 'SELECT HASH_ID, name, latitude, longitude, address, situation, inserted_at as updated_at FROM d_school',
            'cypher_query': q.MERGE_SCHOOL,
            'transformer': lambda row: {
                **row, 
                'inep_id': row['HASH_ID'].split('-')[0] if row['HASH_ID'] else None
            }
        }
    )

    # d_classroom has F_HASH_ID = "c.id".
    load_classrooms = PythonOperator(
        task_id='load_classrooms',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': 'SELECT F_HASH_ID as id, class_year as year, serie as grade_level, stage, inserted_at as updated_at FROM d_classroom',
            'cypher_query': q.MERGE_CLASSROOM
        }
    )

    # 2. Link Nodes (Relationships)
    
    # f_enrollment output: 
    # student_id = "si.id-school-classroom" (HASH_ID in d_student) -> we extract si.id (Part 0)
    # classroom_id = "class_fk-school_inep" (HASH_ID in d_classroom) -> we extract class_fk (Part 0)
    # But wait, d_classroom F_HASH_ID is `c.id`. f_enrollment `classroom_id` (HASH) likely starts with `c.id`.
    # Let's verify: f_enrollment line 12: `concat (se.classroom_fk, '-', se.school_inep_id_fk)`
    # So taking the first part of classroom_id gives us `se.classroom_fk` which matches `d_classroom.F_HASH_ID` (c.id).
    
    link_enrollments = PythonOperator(
        task_id='link_enrollments',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': 'SELECT student_id, classroom_id, enrollment_status as status, inserted_at as updated_at FROM f_enrollment', 
            'cypher_query': q.LINK_ENROLLMENT,
            'transformer': lambda row: {
                **row,
                'student_id': row['student_id'].split('-')[0] if row['student_id'] else None,
                'classroom_id': row['classroom_id'].split('-')[0] if row['classroom_id'] else None
            }
        }
    )

    # d_classroom has HASH_ID = "classroom_fk-school_inep_fk"
    # We can extract school_inep_fk from the second part of HASH_ID.
    # classroom_id (Node ID) is F_HASH_ID (c.id).
    link_class_school = PythonOperator(
        task_id='link_class_school',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': 'SELECT F_HASH_ID as classroom_id, HASH_ID, inserted_at as updated_at FROM d_classroom', 
            'cypher_query': q.LINK_CLASS_SCHOOL,
            'transformer': lambda row: {
                **row,
                'school_id': row['HASH_ID'].split('-')[1] if row['HASH_ID'] and '-' in row['HASH_ID'] else None
            }
        }
    )

    # Dependency Graph
    [load_students, load_schools, load_classrooms] >> link_enrollments
    [load_schools, load_classrooms] >> link_class_school

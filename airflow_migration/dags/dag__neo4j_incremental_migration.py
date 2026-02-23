"""
DAG: Neo4j Incremental Migration.

Orchestrates the incremental migration of ALL 10 tables from dbo_tia (SQL Server Warehouse) to Neo4j.
It uses Airflow's Jinja templating to fetch only the rows that were inserted or updated since the 
last successful DAG execution.

Strategy:
  Stage 1 – Dimension Nodes
  Stage 2 – Fact Nodes
  Stage 3 – Relationships
All stages use the `stream_to_neo4j` shared function and the Neo4j `MERGE` clause for Upserting seamlessly.
"""
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

# Shared configurations & operations
import src.utils.neo4j.queries as q
import src.utils.neo4j.transformers as t
from src.utils.neo4j.airflow_tasks import create_indexes, stream_to_neo4j

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# ----------------------------------------------------
# Incremental SQL Filter string piece using Jinja
# Jinja evaluates to: last successful run date, or current execution date if first run.
# ----------------------------------------------------
JINJA_INCREMENTAL_WHERE_INSERTED = "WHERE inserted_at >= '{{ (prev_data_interval_end_success or data_interval_start).strftime(\"%Y-%m-%d %H:%M:%S\") }}'"
JINJA_INCREMENTAL_WHERE_UPDATED = "WHERE updated_at >= '{{ (prev_data_interval_end_success or data_interval_start).strftime(\"%Y-%m-%d %H:%M:%S\") }}'"

# ================================================================
# INCREMENTAL SQL QUERIES 
# ================================================================

# Dimension tables
INC_SQL_STUDENT = f"""
SELECT F_HASH_ID as id, name, birth_city, gender, ethnicity, deficiency, birthday,
       bolsa_familia_participator, mother_name, father_name, student_cpf,
       residence_zone, city_address, uf, inserted_at
FROM dbo_tia.d_student
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_SCHOOL = f"""
SELECT HASH_ID as id, name, latitude, longitude, address, number_address,
       address_complement, address_neighborhood, situation, inserted_at
FROM dbo_tia.d_school
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_CLASSROOM = f"""
SELECT HASH_ID as id, F_HASH_ID, name, class_year, serie, stage, status, inserted_at
FROM dbo_tia.d_classroom
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_HEALTH = f"""
SELECT F_HASH_ID as id, celiac_desase, diabetes_desease, hypertension_desease,
       iron_deficiency_anemia_desease, lactose_intolerance_desease,
       malnutrition_desease, obesity_desease, sickle_cell_anemia,
       other_health_problems, updated_at
FROM dbo_tia.d_health
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

INC_SQL_SCHOOL_GEOGRAPH = f"""
SELECT HASH_ID as id, F_HASH_ID as school_hash, cep, city, uf, inserted_at
FROM dbo_tia.d_school_geograph
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_STUDENT_DISCIPLINE = f"""
SELECT HASH_ID as id, F_HASH_ID as student_id, discipline_name,
       grade_1, grade_2, grade_3, grade_4,
       rec_bim_1, rec_bim_2, rec_sem_1, rec_sem_2, rec_sem_3, rec_sem_4,
       rec_final, final_mean, updated_at
FROM dbo_tia.d_student_discipline
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

# Fact tables
INC_SQL_AVALIATION = f"""
SELECT HASH_ID as id, student_id, discipline_id, situation, updated_at
FROM dbo_tia.f_avaliation
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

INC_SQL_CLASS = f"""
SELECT HASH_ID as id, teacher_id, classroom_id, school_id, discipline_id,
       scheduled_day, scheduled_class_days, scheduled_month,
       scheduled_lessons_per_day, scheduled_year, discipline_name, updated_at
FROM dbo_tia.f_class
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

INC_SQL_STUDENT_CLASS = f"""
SELECT HASH_ID as id, student_id, class_id, discipline_id,
       total_faults_per_day, total_faults_per_discipline,
       scheduled_student_class_days, updated_at
FROM dbo_tia.f_student_class
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

# Relationship source queries
INC_SQL_ENROLLMENT = f"""
SELECT student_id, classroom_id, school_id, health_id,
       enrollment_status, inserted_at
FROM dbo_tia.f_enrollment
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_CLASSROOM_SCHOOL = f"""
SELECT HASH_ID, F_HASH_ID as classroom_fk, inserted_at
FROM dbo_tia.d_classroom
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_SCHOOL_GEO_REL = f"""
SELECT HASH_ID as geograph_id, F_HASH_ID as school_hash, inserted_at
FROM dbo_tia.d_school_geograph
{JINJA_INCREMENTAL_WHERE_INSERTED}
"""

INC_SQL_DISCIPLINE_REL = f"""
SELECT HASH_ID as discipline_id, F_HASH_ID as student_id, updated_at
FROM dbo_tia.d_student_discipline
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

INC_SQL_AVALIATION_REL = f"""
SELECT HASH_ID as avaliation_id, student_id, discipline_id, updated_at
FROM dbo_tia.f_avaliation
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

INC_SQL_CLASS_REL = f"""
SELECT HASH_ID as class_id, classroom_id, school_id, updated_at
FROM dbo_tia.f_class
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""

INC_SQL_STUDENT_CLASS_REL = f"""
SELECT HASH_ID as student_class_id, student_id, class_id, updated_at
FROM dbo_tia.f_student_class
{JINJA_INCREMENTAL_WHERE_UPDATED}
"""


# ================================================================
# DAG Definition
# ================================================================

with DAG(
    'neo4j_incremental_migration',
    default_args=default_args,
    description='Incremental Migration of dbo_tia to Neo4j',
    schedule=None,  # Adjust to '@daily' or let it be triggered by Data Warehouse DAG
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=['neo4j', 'incremental'],
) as incremental_dag:

    # ----------------------------------------------------------
    # Stage 0: Create Indexes (Ensures structure exists and fast upserts)
    # ----------------------------------------------------------
    task_create_indexes = PythonOperator(
        task_id='create_indexes',
        python_callable=create_indexes,
    )

    # ----------------------------------------------------------
    # Stage 1: Dimension Nodes
    # ----------------------------------------------------------
    load_students = PythonOperator(
        task_id='load_students',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_STUDENT, 'cypher_query': q.MERGE_STUDENT},
    )

    load_schools = PythonOperator(
        task_id='load_schools',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_SCHOOL, 
            'cypher_query': q.MERGE_SCHOOL,
            'transformer': t.transform_school_node
        },
    )

    load_classrooms = PythonOperator(
        task_id='load_classrooms',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_CLASSROOM, 
            'cypher_query': q.MERGE_CLASSROOM,
            'transformer': t.transform_classroom_node
        },
    )

    load_health = PythonOperator(
        task_id='load_health',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_HEALTH, 'cypher_query': q.MERGE_HEALTH},
    )

    load_school_geograph = PythonOperator(
        task_id='load_school_geograph',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_SCHOOL_GEOGRAPH, 'cypher_query': q.MERGE_SCHOOL_GEOGRAPH},
    )

    load_student_discipline = PythonOperator(
        task_id='load_student_discipline',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_STUDENT_DISCIPLINE, 'cypher_query': q.MERGE_STUDENT_DISCIPLINE},
    )

    # ----------------------------------------------------------
    # Stage 2: Fact Nodes
    # ----------------------------------------------------------
    load_avaliation = PythonOperator(
        task_id='load_avaliation',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_AVALIATION, 'cypher_query': q.MERGE_AVALIATION},
    )

    load_class = PythonOperator(
        task_id='load_class',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_CLASS, 'cypher_query': q.MERGE_CLASS},
    )

    load_student_class = PythonOperator(
        task_id='load_student_class',
        python_callable=stream_to_neo4j,
        op_kwargs={'sql_query': INC_SQL_STUDENT_CLASS, 'cypher_query': q.MERGE_STUDENT_CLASS},
    )

    # ----------------------------------------------------------
    # Stage 3: Relationships
    # ----------------------------------------------------------
    link_enrollment = PythonOperator(
        task_id='link_enrollment',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_ENROLLMENT,
            'cypher_query': q.LINK_ENROLLMENT,
            'transformer': t.transform_enrollment_student,
        },
    )

    link_enrollment_school = PythonOperator(
        task_id='link_enrollment_school',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_ENROLLMENT,
            'cypher_query': q.LINK_ENROLLMENT_SCHOOL,
            'transformer': t.transform_enrollment_school,
        },
    )

    link_enrollment_health = PythonOperator(
        task_id='link_enrollment_health',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_ENROLLMENT,
            'cypher_query': q.LINK_ENROLLMENT_HEALTH,
            'transformer': t.transform_enrollment_health,
        },
    )

    link_class_school = PythonOperator(
        task_id='link_class_school',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_CLASSROOM_SCHOOL,
            'cypher_query': q.LINK_CLASS_SCHOOL,
            'transformer': t.transform_classroom_school,
        },
    )

    link_school_geograph = PythonOperator(
        task_id='link_school_geograph',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_SCHOOL_GEO_REL,
            'cypher_query': q.LINK_SCHOOL_GEOGRAPH,
            'transformer': t.transform_school_geograph_rel,
        },
    )

    link_student_discipline = PythonOperator(
        task_id='link_student_discipline',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_DISCIPLINE_REL,
            'cypher_query': q.LINK_STUDENT_DISCIPLINE,
        },
    )

    link_avaliation_student = PythonOperator(
        task_id='link_avaliation_student',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_AVALIATION_REL,
            'cypher_query': q.LINK_AVALIATION_STUDENT,
            'transformer': t.transform_avaliation_student,
        },
    )

    link_avaliation_discipline = PythonOperator(
        task_id='link_avaliation_discipline',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_AVALIATION_REL,
            'cypher_query': q.LINK_AVALIATION_DISCIPLINE,
        },
    )

    link_class_classroom = PythonOperator(
        task_id='link_class_classroom',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_CLASS_REL,
            'cypher_query': q.LINK_CLASS_CLASSROOM,
            'transformer': t.transform_class_classroom,
        },
    )

    link_class_at_school = PythonOperator(
        task_id='link_class_at_school',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_CLASS_REL,
            'cypher_query': q.LINK_CLASS_AT_SCHOOL,
            'transformer': t.transform_class_school,
        },
    )

    link_student_class_student = PythonOperator(
        task_id='link_student_class_student',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_STUDENT_CLASS_REL,
            'cypher_query': q.LINK_STUDENT_CLASS_STUDENT,
            'transformer': t.transform_student_class_student,
        },
    )

    link_student_class_class = PythonOperator(
        task_id='link_student_class_class',
        python_callable=stream_to_neo4j,
        op_kwargs={
            'sql_query': INC_SQL_STUDENT_CLASS_REL,
            'cypher_query': q.LINK_STUDENT_CLASS_CLASS,
        },
    )

    # ================================================================
    # Dependency Graph (3 Stages)
    # ================================================================

    dimension_nodes = [load_students, load_schools, load_classrooms,
                       load_health, load_school_geograph, load_student_discipline]

    task_create_indexes >> dimension_nodes

    fact_nodes = [load_avaliation, load_class, load_student_class]

    for dim_node in dimension_nodes:
        dim_node >> fact_nodes

    all_relationships = [
        link_enrollment, link_enrollment_school, link_enrollment_health,
        link_class_school, link_school_geograph, link_student_discipline,
        link_avaliation_student, link_avaliation_discipline,
        link_class_classroom, link_class_at_school,
        link_student_class_student, link_student_class_class
    ]

    for fact_node in fact_nodes:
        fact_node >> all_relationships

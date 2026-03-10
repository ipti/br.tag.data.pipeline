"""
DAG: Neo4j Full Migration.

Orchestrates the migration of ALL 10 tables from dbo_tia (SQL Server Warehouse) to Neo4j.

Strategy (3 Stages):
  Stage 1 – Dimension Nodes: Student, School, Classroom, Health, SchoolGeograph, StudentDiscipline
  Stage 2 – Fact Nodes:      Avaliation, Class, StudentClass
  Stage 3 – Relationships:   12 relationship types linking all nodes

All SQL queries read from the dbo_tia schema on SQL Server.
"""

from datetime import datetime, timedelta
import logging

from airflow import DAG
from airflow.operators.python import PythonOperator
from src.utils.connections.connection_manager import DatabaseConnectionManager
from sqlalchemy import text

from src.utils.neo4j.ingestor import Neo4jIngestor
import src.utils.neo4j.queries as q

# Default arguments for the DAG
default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


from src.utils.neo4j.airflow_tasks import create_indexes, stream_to_neo4j

# ================================================================
# SQL QUERIES – Reading from dbo_tia schema on SQL Server
# ================================================================

# Dimension tables
SQL_STUDENT = """
SELECT F_HASH_ID as id, name, birth_city, gender, ethnicity, deficiency, birthday,
       bolsa_familia_participator, mother_name, father_name, student_cpf,
       residence_zone, city_address, uf, inserted_at
FROM dbo_tia.d_student
"""

SQL_SCHOOL = """
SELECT HASH_ID as id, name, latitude, longitude, address, number_address,
       address_complement, address_neighborhood, situation, inserted_at
FROM dbo_tia.d_school
"""

SQL_CLASSROOM = """
SELECT HASH_ID as id, F_HASH_ID, name, class_year, serie, stage, status, inserted_at
FROM dbo_tia.d_classroom
"""

SQL_HEALTH = """
SELECT F_HASH_ID as id, celiac_desase, diabetes_desease, hypertension_desease,
       iron_deficiency_anemia_desease, lactose_intolerance_desease,
       malnutrition_desease, obesity_desease, sickle_cell_anemia,
       other_health_problems, updated_at
FROM dbo_tia.d_health
"""

SQL_SCHOOL_GEOGRAPH = """
SELECT HASH_ID as id, F_HASH_ID as school_hash, cep, city, uf, inserted_at
FROM dbo_tia.d_school_geograph
"""

SQL_STUDENT_DISCIPLINE = """
SELECT HASH_ID as id, F_HASH_ID as student_id, discipline_name,
       grade_1, grade_2, grade_3, grade_4,
       rec_bim_1, rec_bim_2, rec_sem_1, rec_sem_2, rec_sem_3, rec_sem_4,
       rec_final, final_mean, updated_at
FROM dbo_tia.d_student_discipline
"""

# Fact tables
SQL_AVALIATION = """
SELECT HASH_ID as id, student_id, discipline_id, situation, updated_at
FROM dbo_tia.f_avaliation
"""

SQL_CLASS = """
SELECT HASH_ID as id, teacher_id, classroom_id, school_id, discipline_id,
       scheduled_day, scheduled_class_days, scheduled_month,
       scheduled_lessons_per_day, scheduled_year, discipline_name, updated_at
FROM dbo_tia.f_class
"""

SQL_STUDENT_CLASS = """
SELECT HASH_ID as id, student_id, class_id, discipline_id,
       total_faults_per_day, total_faults_per_discipline,
       scheduled_student_class_days, updated_at
FROM dbo_tia.f_student_class
"""

# Relationship source queries
SQL_ENROLLMENT = """
SELECT student_id, classroom_id, school_id, health_id,
       enrollment_status, inserted_at
FROM dbo_tia.f_enrollment
"""

SQL_CLASSROOM_SCHOOL = """
SELECT HASH_ID, F_HASH_ID as classroom_fk, inserted_at
FROM dbo_tia.d_classroom
"""

SQL_SCHOOL_GEO_REL = """
SELECT HASH_ID as geograph_id, F_HASH_ID as school_hash, inserted_at
FROM dbo_tia.d_school_geograph
"""

SQL_DISCIPLINE_REL = """
SELECT HASH_ID as discipline_id, F_HASH_ID as student_id, updated_at
FROM dbo_tia.d_student_discipline
"""

SQL_AVALIATION_REL = """
SELECT HASH_ID as avaliation_id, student_id, discipline_id, updated_at
FROM dbo_tia.f_avaliation
"""

SQL_CLASS_REL = """
SELECT HASH_ID as class_id, classroom_id, school_id, updated_at
FROM dbo_tia.f_class
"""

SQL_STUDENT_CLASS_REL = """
SELECT HASH_ID as student_class_id, student_id, class_id, updated_at
FROM dbo_tia.f_student_class
"""


import src.utils.neo4j.transformers as t

# ================================================================
# DAG Definition
# ================================================================

with DAG(
    "neo4j_full_migration",
    default_args=default_args,
    description="Migrates ALL 10 dbo_tia tables to Neo4j (nodes + relationships)",
    schedule=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=["neo4j", "migration"],
) as dag:

    # ----------------------------------------------------------
    # Stage 0: Create Indexes
    # ----------------------------------------------------------
    task_create_indexes = PythonOperator(
        task_id="create_indexes",
        python_callable=create_indexes,
    )

    # ----------------------------------------------------------
    # Stage 1: Dimension Nodes
    # ----------------------------------------------------------
    load_students = PythonOperator(
        task_id="load_students",
        python_callable=stream_to_neo4j,
        op_kwargs={"sql_query": SQL_STUDENT, "cypher_query": q.MERGE_STUDENT},
    )

    load_schools = PythonOperator(
        task_id="load_schools",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_SCHOOL,
            "cypher_query": q.MERGE_SCHOOL,
            "transformer": t.transform_school_node,
        },
    )

    load_classrooms = PythonOperator(
        task_id="load_classrooms",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_CLASSROOM,
            "cypher_query": q.MERGE_CLASSROOM,
            "transformer": t.transform_classroom_node,
        },
    )

    load_health = PythonOperator(
        task_id="load_health",
        python_callable=stream_to_neo4j,
        op_kwargs={"sql_query": SQL_HEALTH, "cypher_query": q.MERGE_HEALTH},
    )

    load_school_geograph = PythonOperator(
        task_id="load_school_geograph",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_SCHOOL_GEOGRAPH,
            "cypher_query": q.MERGE_SCHOOL_GEOGRAPH,
        },
    )

    load_student_discipline = PythonOperator(
        task_id="load_student_discipline",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_STUDENT_DISCIPLINE,
            "cypher_query": q.MERGE_STUDENT_DISCIPLINE,
        },
    )

    # ----------------------------------------------------------
    # Stage 2: Fact Nodes
    # ----------------------------------------------------------
    load_avaliation = PythonOperator(
        task_id="load_avaliation",
        python_callable=stream_to_neo4j,
        op_kwargs={"sql_query": SQL_AVALIATION, "cypher_query": q.MERGE_AVALIATION},
    )

    load_class = PythonOperator(
        task_id="load_class",
        python_callable=stream_to_neo4j,
        op_kwargs={"sql_query": SQL_CLASS, "cypher_query": q.MERGE_CLASS},
    )

    load_student_class = PythonOperator(
        task_id="load_student_class",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_STUDENT_CLASS,
            "cypher_query": q.MERGE_STUDENT_CLASS,
        },
    )

    # ----------------------------------------------------------
    # Stage 3: Relationships
    # ----------------------------------------------------------

    # F_ENROLLMENT relationships (Student->Classroom, Student->School, Student->Health)
    link_enrollment = PythonOperator(
        task_id="link_enrollment",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_ENROLLMENT,
            "cypher_query": q.LINK_ENROLLMENT,
            "transformer": t.transform_enrollment_student,
        },
    )

    link_enrollment_school = PythonOperator(
        task_id="link_enrollment_school",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_ENROLLMENT,
            "cypher_query": q.LINK_ENROLLMENT_SCHOOL,
            "transformer": t.transform_enrollment_school,
        },
    )

    link_enrollment_health = PythonOperator(
        task_id="link_enrollment_health",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_ENROLLMENT,
            "cypher_query": q.LINK_ENROLLMENT_HEALTH,
            "transformer": t.transform_enrollment_health,
        },
    )

    # D_CLASSROOM -> D_SCHOOL
    link_class_school = PythonOperator(
        task_id="link_class_school",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_CLASSROOM_SCHOOL,
            "cypher_query": q.LINK_CLASS_SCHOOL,
            "transformer": t.transform_classroom_school,
        },
    )

    # D_SCHOOL -> D_SCHOOL_GEOGRAPH
    link_school_geograph = PythonOperator(
        task_id="link_school_geograph",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_SCHOOL_GEO_REL,
            "cypher_query": q.LINK_SCHOOL_GEOGRAPH,
            "transformer": t.transform_school_geograph_rel,
        },
    )

    # D_STUDENT -> D_STUDENT_DISCIPLINE
    link_student_discipline = PythonOperator(
        task_id="link_student_discipline",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_DISCIPLINE_REL,
            "cypher_query": q.LINK_STUDENT_DISCIPLINE,
        },
    )

    # F_AVALIATION -> Student + StudentDiscipline
    link_avaliation_student = PythonOperator(
        task_id="link_avaliation_student",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_AVALIATION_REL,
            "cypher_query": q.LINK_AVALIATION_STUDENT,
            "transformer": t.transform_avaliation_student,
        },
    )

    link_avaliation_discipline = PythonOperator(
        task_id="link_avaliation_discipline",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_AVALIATION_REL,
            "cypher_query": q.LINK_AVALIATION_DISCIPLINE,
        },
    )

    # F_CLASS -> Classroom + School
    link_class_classroom = PythonOperator(
        task_id="link_class_classroom",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_CLASS_REL,
            "cypher_query": q.LINK_CLASS_CLASSROOM,
            "transformer": t.transform_class_classroom,
        },
    )

    link_class_at_school = PythonOperator(
        task_id="link_class_at_school",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_CLASS_REL,
            "cypher_query": q.LINK_CLASS_AT_SCHOOL,
            "transformer": t.transform_class_school,
        },
    )

    # F_STUDENT_CLASS -> Student + Class
    link_student_class_student = PythonOperator(
        task_id="link_student_class_student",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_STUDENT_CLASS_REL,
            "cypher_query": q.LINK_STUDENT_CLASS_STUDENT,
            "transformer": t.transform_student_class_student,
        },
    )

    link_student_class_class = PythonOperator(
        task_id="link_student_class_class",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": SQL_STUDENT_CLASS_REL,
            "cypher_query": q.LINK_STUDENT_CLASS_CLASS,
        },
    )

    # ================================================================
    # Dependency Graph (3 Stages)
    # ================================================================

    # Stage 0 -> Stage 1: Indexes first, then all dimension nodes in parallel
    dimension_nodes = [
        load_students,
        load_schools,
        load_classrooms,
        load_health,
        load_school_geograph,
        load_student_discipline,
    ]

    task_create_indexes >> dimension_nodes

    # Stage 1 -> Stage 2: Fact nodes depend on ALL dimension nodes
    fact_nodes = [load_avaliation, load_class, load_student_class]

    for dim_node in dimension_nodes:
        dim_node >> fact_nodes

    # Stage 2 -> Stage 3: All relationships depend on all nodes being loaded
    all_relationships = [
        link_enrollment,
        link_enrollment_school,
        link_enrollment_health,
        link_class_school,
        link_school_geograph,
        link_student_discipline,
        link_avaliation_student,
        link_avaliation_discipline,
        link_class_classroom,
        link_class_at_school,
        link_student_class_student,
        link_student_class_class,
    ]

    for fact_node in fact_nodes:
        fact_node >> all_relationships

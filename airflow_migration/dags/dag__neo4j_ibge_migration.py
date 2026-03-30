"""
DAG: Neo4j IBGE Migration.

Enriches Neo4j with external socioeconomic and educational data
from SQL Server BUF and raw schemas.

Strategy (3 Stages):
  Stage 0 – Indexes:       State, Municipality
  Stage 1 – Base Nodes:    State (PNAD), Municipality (Atlas)  — parallel
  Stage 2 – Enrichments:   State (Cor, Sexo) + Municipality (IDEB, Aprendizado,
                            Distorcao, Rendimento, Permanencia)  — all parallel
  Stage 3 – Relationships: Municipality->State, SchoolGeograph->Municipality
"""

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.utils.neo4j.airflow_tasks import stream_to_neo4j
import src.utils.neo4j.ibge_queries as q
import src.utils.neo4j.ibge_cypher as c
import src.utils.neo4j.ibge_transformers as t

default_args = {
    "owner": "airflow",
    "depends_on_past": False,
    "email_on_failure": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def create_ibge_indexes():
    from src.utils.neo4j.ingestor import Neo4jIngestor

    ingestor = Neo4jIngestor()
    try:
        for cypher in [
            "CREATE INDEX state_id IF NOT EXISTS FOR (s:State) ON (s.id)",
            "CREATE INDEX state_sigla IF NOT EXISTS FOR (s:State) ON (s.sigla)",
            "CREATE INDEX municipality_id IF NOT EXISTS FOR (m:Municipality) ON (m.id)",
            "CREATE INDEX municipality_name IF NOT EXISTS FOR (m:Municipality) ON (m.name)",
        ]:
            ingestor.run_query(cypher)
    finally:
        ingestor.close()


with DAG(
    "neo4j_ibge_migration",
    default_args=default_args,
    description="Enriches Neo4j with IBGE/QEdu data (State + Municipality nodes)",
    schedule=None,
    start_date=datetime(2023, 1, 1),
    catchup=False,
    tags=["neo4j", "ibge", "migration"],
) as dag:

    # ----------------------------------------------------------
    # Stage 0: Indexes
    # ----------------------------------------------------------
    task_create_ibge_indexes = PythonOperator(
        task_id="create_ibge_indexes",
        python_callable=create_ibge_indexes,
    )

    # ----------------------------------------------------------
    # Stage 1: Nós base (paralelo)
    # ----------------------------------------------------------
    load_states = PythonOperator(
        task_id="load_states",
        python_callable=stream_to_neo4j,
        op_kwargs={"sql_query": q.SQL_STATE, "cypher_query": c.MERGE_STATE},
    )

    load_municipalities = PythonOperator(
        task_id="load_municipalities",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY,
            "cypher_query": c.MERGE_MUNICIPALITY,
        },
    )

    # ----------------------------------------------------------
    # Stage 2: Enriquecimentos (paralelo dentro de cada grupo)
    # ----------------------------------------------------------
    enrich_state_cor = PythonOperator(
        task_id="enrich_state_cor",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_STATE_COR,
            "cypher_query": c.ENRICH_STATE_COR,
            "transformer": t.transform_state_cor,
        },
    )

    enrich_state_sexo = PythonOperator(
        task_id="enrich_state_sexo",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_STATE_SEXO,
            "cypher_query": c.ENRICH_STATE_SEXO,
            "transformer": t.transform_state_sexo,
        },
    )

    enrich_state_ideb = PythonOperator(
        task_id="enrich_state_ideb",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY_IDEB,
            "cypher_query": c.ENRICH_MUNICIPALITY_IDEB,
            "transformer": t.transform_ideb_by_ciclo,
        },
    )

    enrich_state_aprendizado = PythonOperator(
        task_id="enrich_state_aprendizado",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY_APRENDIZADO,
            "cypher_query": c.ENRICH_MUNICIPALITY_APRENDIZADO,
            "transformer": t.transform_ideb_by_ciclo,
        },
    )

    enrich_state_distorcao = PythonOperator(
        task_id="enrich_state_distorcao",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY_DISTORCAO,
            "cypher_query": c.ENRICH_MUNICIPALITY_DISTORCAO,
        },
    )

    enrich_state_rendimento = PythonOperator(
        task_id="enrich_state_rendimento",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY_RENDIMENTO,
            "cypher_query": c.ENRICH_MUNICIPALITY_RENDIMENTO,
        },
    )

    enrich_state_permanencia = PythonOperator(
        task_id="enrich_state_permanencia",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY_PERMANENCIA,
            "cypher_query": c.ENRICH_MUNICIPALITY_PERMANENCIA,
        },
    )

    # ----------------------------------------------------------
    # Stage 3: Relacionamentos
    # ----------------------------------------------------------
    link_municipality_state = PythonOperator(
        task_id="link_municipality_state",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_MUNICIPALITY_STATE_REL,
            "cypher_query": c.LINK_MUNICIPALITY_STATE,
        },
    )

    link_school_geograph_municipality = PythonOperator(
        task_id="link_school_geograph_municipality",
        python_callable=stream_to_neo4j,
        op_kwargs={
            "sql_query": q.SQL_SCHOOL_GEOGRAPH_IBGE_JOIN,
            "cypher_query": c.LINK_SCHOOL_GEOGRAPH_MUNICIPALITY,
        },
    )

    # ================================================================
    # Dependency Graph
    # ================================================================

    task_create_ibge_indexes >> [load_states, load_municipalities]

    load_states >> [
        enrich_state_cor,
        enrich_state_sexo,
        enrich_state_ideb,
        enrich_state_aprendizado,
        enrich_state_distorcao,
        enrich_state_rendimento,
        enrich_state_permanencia,
    ]

    # No QEdu enrichments for load_municipalities anymore
    # The Atlas base load automatically captures municipality indicators.

    all_enrichments = [
        enrich_state_cor,
        enrich_state_sexo,
        enrich_state_ideb,
        enrich_state_aprendizado,
        enrich_state_distorcao,
        enrich_state_rendimento,
        enrich_state_permanencia,
    ]

    # Explicit list needed here to fan out to multiple downstreams
    for enrichment in all_enrichments:
        enrichment >> link_municipality_state
        enrichment >> link_school_geograph_municipality

import os
from pathlib import Path
from datetime import datetime, timedelta
import logging
import pandas as pd
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

from src.ml.features.neo4j_extractor import Neo4jExtractor
from src.ml.features.school_aggregator import compute_school_metrics
from src.embeddings.student_embedder import embed_students
from src.embeddings.school_embedder import embed_schools
from src.embeddings.neo4j_vector_writer import write_embeddings

logger = logging.getLogger(__name__)

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

def _refresh_all_embeddings():
    logger.info("Iniciando refresh semanal dos embeddings RAG...")
    
    neo = Neo4jExtractor.from_env()
    driver = neo._driver
    
    # 1. Alunos
    logger.info("Buscando dados de alunos para embedding do Parquet local...")
    
    raw_dir = Path("/opt/airflow/src/ml/data/raw")
    dfs = []
    
    for segment in ["EF1", "EF2"]:
        p = raw_dir / f"{segment}_2025.parquet"
        if p.exists():
            logger.info("Lendo base do Parquet local: %s", p)
            dfs.append(pd.read_parquet(p))
        else:
            logger.info("Arquivo local %s nao encontrado. Simularemos fallback extraindo via Neo4jExtractor.", p.name)
            out = neo.extract_students_base(segment, 2025)
            dfs.append(pd.read_parquet(out))
            
    df_students = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
    
    if not df_students.empty:
        logger.info("Gerando embeddings de Alunos (N=%d)...", len(df_students))
        student_embeddings = embed_students(df_students)
        write_embeddings(
            driver=driver,
            ids=df_students['student_id'].tolist(),
            embeddings=student_embeddings,
            entity="student"
        )
    
    # 2. Escolas
    logger.info("Calculando métricas agregadas da Escola...")
    # Passamos os estudantes extraídos para criar as métricas das escolas
    df_schools = compute_school_metrics(df_students) if not df_students.empty else pd.DataFrame()
    
    if not df_schools.empty:
        logger.info("Gerando embeddings de Escolas (N=%d)...", len(df_schools))
        school_embeddings = embed_schools(df_schools)
        write_embeddings(
            driver=driver,
            ids=df_schools['school_id'].tolist(),
            embeddings=school_embeddings,
            entity="school"
        )
        
    driver.close()
    logger.info("Refresh finalizado com sucesso.")

with DAG(
    'rag_embedding_refresh',
    default_args=default_args,
    description='Recomputa embeddings de alunos e escolas no Neo4j para RAG - Weekly',
    schedule='@weekly',
    catchup=False,
    max_active_runs=1,
) as dag:
    
    update_embeddings = PythonOperator(
        task_id='update_neo4j_embeddings',
        python_callable=_refresh_all_embeddings,
    )

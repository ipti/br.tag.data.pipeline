import os
import gc
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
import logging
import pandas as pd
from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

from src.ml.features.neo4j_extractor import Neo4jExtractor
from src.ml.features.school_aggregator import compute_school_metrics
from src.embeddings.student_embedder import embed_students, student_to_text
from src.embeddings.school_embedder import embed_schools, school_to_text
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


def _get_existing_hashes(driver, entity: str) -> dict[str, str]:
    """Busca o estado atual dos hashes associados aos records para pulos."""
    node_label = "Student" if entity == "student" else "School"
    query = f"MATCH (n:{node_label}) WHERE n.embedding_hash IS NOT NULL RETURN n.id AS id, n.embedding_hash AS hash"
    with driver.session() as session:
        result = session.run(query)
        df_hashes = pd.DataFrame([r.data() for r in result])
        
    if df_hashes.empty:
        return {}
    return dict(zip(df_hashes['id'], df_hashes['hash']))


def _refresh_all_embeddings():
    logger.info("Iniciando refresh semanal dos embeddings RAG...")
    
    neo = Neo4jExtractor.from_env()
    driver = neo._driver
    
    # 1. Alunos — carrega TODOS os anos disponíveis localmente
    logger.info("Buscando dados de alunos para embedding (todos os anos disponíveis)...")
    
    raw_dir = Path("/opt/airflow/src/ml/data/raw")
    dfs = []
    
    # Glob para todos os parquets anuais: EF1_2022.parquet, EF2_2025.parquet, etc.
    # Exclui deltas e arquivos consolidados sem ano (EF1.parquet, EF2.parquet)
    import re
    for pq_file in sorted(raw_dir.glob("EF[12]_[0-9][0-9][0-9][0-9].parquet")):
        logger.info("Lendo Parquet local: %s", pq_file.name)
        dfs.append(pd.read_parquet(pq_file))
    
    if not dfs:
        logger.warning("Nenhum Parquet anual encontrado em %s. Abortando.", raw_dir)
        driver.close()
        return
    
    df_students = pd.concat(dfs, ignore_index=True)
    del dfs
    gc.collect()
    
    # Deduplicação por student_id — CRÍTICO!
    # Cada aluno tem ~26 linhas (uma por disciplina/nota). As features de nível aluno
    # (gênero, bolsa_família, taxa_ausência, nota_final_norm) são idênticas entre duplicatas.
    # Sem dedup, o hash MD5 muda a cada rodada (linhas em ordem diferente → hash diferente)
    # causando loop infinito de "634k alunos precisam atualização".
    n_before = len(df_students)
    df_students = df_students.drop_duplicates(subset="student_id", keep="last")
    n_after = len(df_students)
    logger.info(
        "Dedup por student_id: %d linhas → %d alunos únicos (removidas %d duplicatas)",
        n_before, n_after, n_before - n_after
    )
    
    if not df_students.empty:
        logger.info("Verificando atualizações incrementais em %d Estudantes.", len(df_students))
        existing_hashes = _get_existing_hashes(driver, "student")
        
        # Computa textos e gera hashes (MD5) da combinacao de features
        texts = [student_to_text(row) for _, row in df_students.iterrows()]
        hashes = [hashlib.md5(t.encode('utf-8')).hexdigest() for t in texts]
        
        df_students['text_hash'] = hashes
        df_students['target_text'] = texts # Salvamos pra debug se precisar
        
        # Filtra os que precisam ir pro encoder (hash novo ou ausente)
        df_students['existing_hash'] = df_students['student_id'].map(existing_hashes)
        df_needs_update = df_students[df_students['text_hash'] != df_students['existing_hash']].copy()
        
        logger.info("%d Alunos necessitam atualização de embedding (o restante será ignorado).", len(df_needs_update))
        
        if not df_needs_update.empty:
            # Batch loop processing para prevenir OOM durante o encoding
            CHUNK_SIZE = 20000 
            total = len(df_needs_update)
            
            for start in range(0, total, CHUNK_SIZE):
                chunk = df_needs_update.iloc[start:start+CHUNK_SIZE]
                chunk_ids = chunk['student_id'].tolist()
                chunk_hashes = chunk['text_hash'].tolist()
                
                logger.info("Encoding chunk [%d:%d]/%d", start, start+len(chunk), total)
                
                # Passa apenas o pedaco pro embed model gerar numpy vector
                student_embeddings = embed_students(chunk, batch_size=256)
                write_embeddings(
                    driver=driver,
                    ids=chunk_ids,
                    embeddings=student_embeddings,
                    entity="student",
                    hashes=chunk_hashes
                )
                
                # Forca limpeza de memoria numpy
                del student_embeddings
                gc.collect()

    
    # 2. Escolas
    logger.info("Calculando métricas agregadas da Escola...")
    # Limpa memória base do DataFrame de Estudantes antes da extração de escolas para evitar OOM
    if 'df_students' in locals():
        del df_students
        gc.collect()

    try:
        # Puxa o agregado de features de escolas já mapeado globalmente direto da Extração Neo4j
        school_path = neo.extract_school_features()
        
        # extract_school_features() retorna um caminho Azure Blob quando em modo Azure,
        # precisamos ler com o filesystem correto (fsspec/adlfs)
        if neo._azure and neo._fs is not None:
            import pyarrow.parquet as pq
            logger.info("Lendo school_features do Azure Blob: %s", school_path)
            tbl = pq.read_table(school_path, filesystem=neo._fs)
            df_schools_raw = tbl.to_pandas()
            del tbl
        else:
            df_schools_raw = pd.read_parquet(school_path)
        
        df_schools = compute_school_metrics(df_schools_raw) if not df_schools_raw.empty else pd.DataFrame()
    except Exception as e:
        logger.error("Falha ao extrair features da escola: %s", e)
        df_schools = pd.DataFrame()
    
    if not df_schools.empty:
        logger.info("Verificando atualizações incrementais em %d Escolas.", len(df_schools))
        school_existing_hashes = _get_existing_hashes(driver, "school")
        
        school_texts = [school_to_text(row) for _, row in df_schools.iterrows()]
        school_hashes = [hashlib.md5(t.encode('utf-8')).hexdigest() for t in school_texts]
        
        df_schools['text_hash'] = school_hashes
        df_schools['existing_hash'] = df_schools['school_id'].map(school_existing_hashes)
        df_schools_update = df_schools[df_schools['text_hash'] != df_schools['existing_hash']].copy()
        
        logger.info("%d Escolas necessitam atualização de embedding.", len(df_schools_update))
        
        if not df_schools_update.empty:
            school_embeddings = embed_schools(df_schools_update)
            write_embeddings(
                driver=driver,
                ids=df_schools_update['school_id'].tolist(),
                embeddings=school_embeddings,
                entity="school",
                hashes=df_schools_update['text_hash'].tolist()
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

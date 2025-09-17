from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.dummy import DummyOperator
from airflow.sensors.base import BaseSensorOperator
from datetime import datetime, timedelta
import os

# Import our custom modules
from database_connections import get_db_manager
from airflow_logger import get_logger

# Initialize logger
logger = get_logger("etl_dag")

# Default arguments for the DAG
default_args = {
    'owner': 'data_team',
    'depends_on_past': False,
    'start_date': datetime(2024, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
    'execution_timeout': timedelta(minutes=15)
}


def check_database_connections(**context):
    """
    Initial health check for all database connections.
    This task validates that all required connections are working.
    """
    logger.info("Starting database connection health check")
    
    # Get hotfix mode from DAG configuration
    dag_conf = context['dag_run'].conf or {}
    hotfix_mode = dag_conf.get('hotfix_mode', False)
    
    db_manager = get_db_manager(hotfix_mode=hotfix_mode)
    
    try:
        connection_info = db_manager.get_connection_info()
        logger.info("Database manager initialized", extra_data=connection_info)
        
        # Test SQL Server connection (warehouse)
        if not db_manager.test_sqlserver_connection():
            raise Exception("SQL Server warehouse connection failed")
        
        # Get available MySQL sources and test them
        mysql_sources = db_manager.get_available_mysql_sources()
        
        if not mysql_sources:
            raise Exception("No MySQL sources configured")
        
        working_sources = []
        for source in mysql_sources:
            if db_manager.test_mysql_connection(source):
                working_sources.append(source)
                logger.info(f"MySQL source '{source}' connection successful")
            else:
                logger.warning(f"MySQL source '{source}' connection failed")
        
        if not working_sources:
            raise Exception("No MySQL sources are accessible")
        
        # Return metadata for downstream tasks
        return {
            'status': 'success',
            'environment': connection_info['environment_type'],
            'schema': connection_info['sqlserver_schema'],
            'working_mysql_sources': working_sources,
            'hotfix_mode': hotfix_mode
        }
        
    except Exception as e:
        logger.error("Database connection check failed", exception=e)
        raise
    finally:
        db_manager.close_all_connections()


def extract_business_data(**context):
    """
    Extract business data from MySQL sources.
    Handles multiple potential data sources intelligently.
    """
    logger.info("Starting business data extraction")
    
    # Get upstream task result
    health_check_result = context['task_instance'].xcom_pull(task_ids='check_connections')
    working_sources = health_check_result['working_mysql_sources']
    hotfix_mode = health_check_result['hotfix_mode']
    
    db_manager = get_db_manager(hotfix_mode=hotfix_mode)
    
    try:
        # Prioritize external sources over airflow_mysql for business data
        business_sources = [s for s in working_sources if s.startswith('mysql_source_')]
        
        if business_sources:
            source_name = business_sources[0]  # Use first available business source
            
            # Business data extraction query
            extract_query = """
            SELECT 
                id,
                customer_id,
                order_date,
                total_amount,
                status,
                payment_method,
                created_at,
                updated_at
            FROM orders 
            WHERE DATE(updated_at) = CURDATE()
            AND status IN ('completed', 'pending', 'processing')
            """
            
            target_table = 'staging_daily_orders'
            
        elif 'airflow_mysql' in working_sources:
            source_name = 'airflow_mysql'
            
            # Airflow metadata extraction as fallback
            extract_query = """
            SELECT 
                dag_id,
                task_id,
                execution_date,
                state,
                start_date,
                end_date,
                duration,
                hostname
            FROM task_instance 
            WHERE DATE(execution_date) = CURDATE()
            """
            
            target_table = 'staging_airflow_tasks'
            
        else:
            raise Exception("No suitable MySQL source available for data extraction")
    except Exception as e:
        raise e
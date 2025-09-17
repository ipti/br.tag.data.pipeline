from database_connections import get_db_manager
from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import pandas as pd


# =============================================================================
# BASIC USAGE EXAMPLES
# =============================================================================

def example_connection_discovery():
    """Demonstrate automatic connection discovery."""
    db_manager = get_db_manager()
    
    # Get available MySQL sources
    mysql_sources = db_manager.get_available_mysql_sources()
    print(f"Available MySQL sources: {mysql_sources}")
    
    # Test each available MySQL connection
    for source in mysql_sources:
        if db_manager.mysql_connection_exists(source):
            success = db_manager.test_mysql_connection(source)
            status = "✅" if success else "❌"
            print(f"{status} MySQL '{source}' connection test")
    
    # Test SQL Server connection
    if db_manager.test_sqlserver_connection():
        print("✅ SQL Server connection successful")
    else:
        print("❌ SQL Server connection failed")
    
    # Print detailed connection info
    info = db_manager.get_connection_info()
    print("\n--- Connection Information ---")
    for key, value in info.items():
        print(f"{key}: {value}")
    
    db_manager.close_all_connections()


def example_environment_aware_operations():
    """Show environment-aware database operations."""
    
    # Normal mode - uses dev schema in dev branches, prod schema in main/master
    db_manager = get_db_manager()
    
    print(f"Environment: {db_manager.get_connection_info()['environment_type']}")
    print(f"Schema: {db_manager.get_connection_info()['sqlserver_schema']}")
    
    # Hotfix mode - always uses prod schema
    db_manager_hotfix = get_db_manager(hotfix_mode=True)
    
    print(f"Hotfix Environment: {db_manager_hotfix.get_connection_info()['environment_type']}")
    print(f"Hotfix Schema: {db_manager_hotfix.get_connection_info()['sqlserver_schema']}")
    
    # Clean up
    db_manager.close_all_connections()
    db_manager_hotfix.close_all_connections()


def example_flexible_data_copy():
    """Copy data using the flexible connection system."""
    db_manager = get_db_manager()
    
    try:
        # Check available sources
        available_sources = db_manager.get_available_mysql_sources()
        
        if 'airflow_mysql' in available_sources:
            # Copy from local Airflow MySQL to warehouse
            source_query = """
            SELECT 
                dag_id,
                state,
                execution_date,
                start_date,
                end_date,
                duration
            FROM dag_run 
            WHERE execution_date >= DATE_SUB(NOW(), INTERVAL 1 DAY)
            """
            
            db_manager.copy_data(
                source_name='airflow_mysql',
                source_query=source_query,
                target_table='airflow_dag_runs',
                batch_size=1000,
                truncate_target=True
            )
        
        # Copy from external MySQL source if available
        external_sources = [s for s in available_sources if s.startswith('mysql_source_')]
        
        for source in external_sources:
            print(f"Processing data from {source}")
            
            # Example query - adapt to your actual table structure
            business_query = """
            SELECT 
                id,
                name,
                email,
                status,
                created_at,
                updated_at
            FROM users 
            WHERE updated_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)
            LIMIT 1000
            """
            
            try:
                db_manager.copy_data(
                    source_name=source,
                    source_query=business_query,
                    target_table=f'staging_users_{source.split("_")[-1]}',
                    batch_size=5000,
                    truncate_target=False
                )
            except Exception as e:
                print(f"Failed to process {source}: {e}")
                continue
        
    finally:
        db_manager.close_all_connections()


# =============================================================================
# AIRFLOW DAG EXAMPLES
# =============================================================================

def extract_and_load_business_data(**context):
    """Airflow task to extract and load business data with dynamic source detection."""
    # Get configuration from DAG run
    dag_conf = context['dag_run'].conf or {}
    hotfix_mode = dag_conf.get('hotfix_mode', False)
    source_override = dag_conf.get('mysql_source', None)
    
    db_manager = get_db_manager(hotfix_mode=hotfix_mode)
    
    try:
        # Determine which MySQL source to use
        available_sources = db_manager.get_available_mysql_sources()
        
        if source_override and source_override in available_sources:
            mysql_source = source_override
        elif 'mysql_source_1' in available_sources:
            mysql_source = 'mysql_source_1'
        elif 'airflow_mysql' in available_sources:
            mysql_source = 'airflow_mysql'
        else:
            raise ValueError("No suitable MySQL source found")
        
        # Extract data with dynamic query based on source
        if mysql_source == 'airflow_mysql':
            extract_query = """
            SELECT 
                dag_id,
                task_id,
                execution_date,
                state,
                start_date,
                end_date,
                hostname,
                unixname
            FROM task_instance
            WHERE execution_date >= DATE_SUB(NOW(), INTERVAL 1 DAY)
            """
            target_table = 'airflow_task_history'
        else:
            # Business data query
            extract_query = """
            SELECT 
                id,
                customer_name,
                order_date,
                total_amount,
                status,
                created_at,
                updated_at
            FROM orders
            WHERE updated_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)
            """
            target_table = 'staging_orders'
        
        # Load to warehouse
        db_manager.copy_data(
            source_name=mysql_source,
            source_query=extract_query,
            target_table=target_table,
            batch_size=int(os.getenv('DEFAULT_BATCH_SIZE', 10000)),
            truncate_target=True
        )
        
        # Return metadata for downstream tasks
        connection_info = db_manager.get_connection_info()
        return {
            'status': 'success',
            'mysql_source_used': mysql_source,
            'target_table': target_table,
            'environment': connection_info['environment_type'],
            'schema': connection_info['sqlserver_schema'],
            'hotfix_mode': hotfix_mode
        }
        
    finally:
        db_manager.close_all_connections()


def validate_data_quality_flexible(**context):
    """Validate data quality with flexible source handling."""
    # Get upstream task result
    upstream_result = context['task_instance'].xcom_pull(task_ids='extract_and_load_task')
    mysql_source = upstream_result.get('mysql_source_used')
    target_table = upstream_result.get('target_table')
    
    db_manager = get_db_manager()
    
    try:
        # Count records in source
        if mysql_source == 'airflow_mysql':
            source_query = "SELECT COUNT(*) as count FROM task_instance WHERE execution_date >= DATE_SUB(NOW(), INTERVAL 1 DAY)"
        else:
            source_query = "SELECT COUNT(*) as count FROM orders WHERE updated_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)"
        
        source_count = db_manager.execute_mysql_query(mysql_source, source_query)[0]['count']
        
        # Count records in warehouse
        warehouse_count = db_manager.execute_sqlserver_query(
            f"SELECT COUNT(*) as count FROM {db_manager.sqlserver_config.schema}.{target_table}"
        )[0]['count']
        
        # Validate counts match
        if source_count != warehouse_count:
            raise ValueError(
                f"Data quality check failed: Source={source_count}, Warehouse={warehouse_count}"
            )
        
        return {
            'status': 'success',
            'source_count': source_count,
            'warehouse_count': warehouse_count,
            'table_validated': target_table
        }
        
    finally:
        db_manager.close_all_connections()
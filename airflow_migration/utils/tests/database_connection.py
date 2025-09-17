#!/usr/bin/env python3
"""
Simple database connection test script
Run this file directly to test your database connections locally
"""

import sys
import os
import sys
import sys
from pathlib import Path

# Adiciona o root do projeto ao path
PROJECT_ROOT = Path(__file__).parents[2]  # ajusta conforme sua estrutura
sys.path.insert(0, str(PROJECT_ROOT))

from utils.connections.connection_manager import get_db_manager



def print_separator(title: str):
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def main():
    print("🔄 Starting SQL Server schema test...")

    # Cria instância do DatabaseConnectionManager
    db_manager = get_db_manager()

    print(f"Current Branch: {db_manager.current_branch}")
    print(f"Environment: {'PROD' if db_manager.is_production else 'DEV'}")
    print(f"SQL Server Host: {db_manager.sqlserver_config.host}")
    print(f"SQL Server Database: {db_manager.sqlserver_config.database}")
    print(f"SQL Server Schema (from config): {db_manager.sqlserver_config.schema}")

    print_separator("SCHEMA TABLES")

    try:
        # Executa query para listar tabelas do schema configurado
        query = f"""
        SELECT TABLE_NAME 
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = '{db_manager.sqlserver_config.schema}'
        AND TABLE_TYPE = 'BASE TABLE'
        """

        tables = db_manager.execute_sqlserver_query(query=query)

        if tables:
            print(f"Found {len(tables)} tables in schema '{db_manager.sqlserver_config.schema}':")
            for table in tables[:10]:  # mostra até 10 tabelas
                print(f" - {table['TABLE_NAME']}")
            if len(tables) > 10:
                print(f" ...and {len(tables)-10} more")
        else:
            print(f"No tables found in schema '{db_manager.sqlserver_config.schema}'")

    except Exception as e:
        print(f"❌ SQL Server connection or query failed: {e}")

    print_separator("TEST COMPLETE")
    print("✅ Done!")

if __name__ == "__main__":
    main()

import os
import yaml
import pandas as pd
from typing import Optional, Dict, Any, List, Union, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from sqlalchemy import text, MetaData, Table, inspect
from sqlalchemy.engine import Connection
from contextlib import contextmanager
import hashlib
import numpy as np

from .connection_manager import DatabaseConnectionManager, get_db_manager
from airflow_migration.utils.parser_and_caster.parser import clean_dataframe_for_sql
from airflow_migration.utils.logs.logging_functions import get_logger


@dataclass
class TableMapping:
    """
    Configuration for table column mapping between source and target.
    """

    source_columns: Optional[Dict[str, str]] = None
    target_columns: Optional[List[str]] = None
    column_transformations: Optional[Dict[str, str]] = None
    where_clause: Optional[str] = None


@dataclass
class IncrementalConfig:
    """
    Configuration for incremental loading.
    """

    source_timestamp_columns: List[str]
    target_timestamp_column: str
    lookback_hours: int = 24
    batch_size: int = 10000
    full_refresh: bool = False


@dataclass
class UpsertConfig:
    """
    Configuration for UPSERT operations defining which columns to use for matching records.
    """

    source_key_columns: List[str]
    target_key_columns: Optional[List[str]] = None

    def __post_init__(self):
        """If target_key_columns not specified, use same names as source_key_columns"""
        if self.target_key_columns is None:
            self.target_key_columns = self.source_key_columns.copy()


@dataclass
class LoadResult:
    """
    Result information from load operations.
    """

    success: bool
    rows_processed: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    execution_time_seconds: float = 0.0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class CopyAndLoader:
    """
    Handles batch and incremental data loading between MySQL sources and SQL Server warehouse.
    Integrates with dbt source configurations for SQL Server schema management.
    """

    def __init__(
        self,
        db_manager: Optional[DatabaseConnectionManager] = None,
        dbt_config_file: Optional[str] = None,
    ):
        """
        Initialize the copy and loader with database connection manager.

        Args:
            db_manager: Optional database connection manager. If None, creates a new instance.
            dbt_config_file: Optional path to dbt sources config file. If None, defaults to 'dbo_tia.yml'
        """
        self.logger = get_logger("writer")
        self.db_manager = db_manager or get_db_manager()
        self.dbt_config_file = dbt_config_file or "dbo_tia.yml"
        self.dbt_sources_config = self._load_dbt_sources_config()

        self._schema_cache: Dict[str, Dict[str, Any]] = {}

        self.logger.info(
            "CopyAndLoader initialized",
            {
                "environment": self.db_manager.get_connection_info()[
                    "environment_type"
                ],
                "sqlserver_schema": self.db_manager.sqlserver_config.schema,
                "dbt_config_file": self.dbt_config_file,
                "dbt_sources_loaded": len(self.dbt_sources_config) > 0,
            },
        )

    def _load_dbt_sources_config(self) -> Dict[str, Any]:
        try:
            project_root = Path(__file__).resolve().parent.parent.parent
            dbt_sources_path = (
                project_root / "dbt/models/sources" / self.dbt_config_file
            )

            if not dbt_sources_path.exists():
                self.logger.warning(
                    "dbt sources configuration file not found",
                    {
                        "config_file": self.dbt_config_file,
                        "searched_path": str(dbt_sources_path),
                    },
                )
                return {}

            with open(dbt_sources_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)

            self.logger.info(
                "dbt sources configuration loaded successfully",
                {
                    "config_file": str(dbt_sources_path),
                    "sources_found": len(config.get("sources", [])),
                },
            )
            return config

        except Exception as e:
            self.logger.error(
                "Failed to load dbt sources configuration",
                exception=e,
                extra_data={"config_file": self.dbt_config_file},
            )
            return {}

    def load_additional_dbt_config(self, config_file: str) -> Dict[str, Any]:
        """
        Load an additional dbt sources configuration file and merge with existing config.

        Args:
            config_file: Name of the dbt config file (e.g., 'other_schema.yml')

        Returns:
            Dictionary containing the loaded configuration
        """
        try:
            original_config_file = self.dbt_config_file
            self.dbt_config_file = config_file

            new_config = self._load_dbt_sources_config()

            if new_config and "sources" in new_config:
                if "sources" not in self.dbt_sources_config:
                    self.dbt_sources_config["sources"] = []

                for new_source in new_config["sources"]:
                    existing_source = None
                    for existing in self.dbt_sources_config["sources"]:
                        if existing["name"] == new_source["name"]:
                            existing_source = existing
                            break

                    if existing_source:
                        if "tables" not in existing_source:
                            existing_source["tables"] = []

                        existing_table_names = {
                            table["name"] for table in existing_source["tables"]
                        }
                        for new_table in new_source.get("tables", []):
                            if new_table["name"] not in existing_table_names:
                                existing_source["tables"].append(new_table)
                    else:
                        self.dbt_sources_config["sources"].append(new_source)

                self.logger.info(
                    "Additional dbt configuration loaded and merged",
                    {
                        "config_file": config_file,
                        "new_sources_count": len(new_config["sources"]),
                        "total_sources_count": len(self.dbt_sources_config["sources"]),
                    },
                )

            self.dbt_config_file = original_config_file

            return new_config

        except Exception as e:
            self.logger.error(
                "Failed to load additional dbt configuration",
                exception=e,
                extra_data={"config_file": config_file},
            )
            return {}

    def _get_table_schema(
        self, connection: Connection, table_name: str, schema: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get table schema information with caching.

        Args:
            connection: Database connection
            table_name: Name of the table
            schema: Optional schema name

        Returns:
            Dictionary with table schema information
        """
        cache_key = f"{schema or 'default'}.{table_name}"

        if cache_key in self._schema_cache:
            return self._schema_cache[cache_key]

        try:
            inspector = inspect(connection)
            columns = inspector.get_columns(table_name, schema=schema)

            schema_info = {
                "columns": {col["name"]: col for col in columns},
                "column_names": [col["name"] for col in columns],
                "primary_keys": inspector.get_pk_constraint(table_name, schema=schema)[
                    "constrained_columns"
                ],
            }

            self._schema_cache[cache_key] = schema_info
            return schema_info

        except Exception as e:
            self.logger.error(
                "Failed to get table schema",
                exception=e,
                extra_data={"table": table_name, "schema": schema},
            )
            return {"columns": {}, "column_names": [], "primary_keys": []}

    def _get_dbt_table_config(
        self, table_name: str, source_name: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get table configuration from dbt sources.

        Args:
            table_name: Name of the table
            source_name: Optional source name to search within. If None, searches all sources.

        Returns:
            Table configuration dictionary or None if not found
        """
        try:
            if not self.dbt_sources_config or "sources" not in self.dbt_sources_config:
                return None

            for source in self.dbt_sources_config["sources"]:
                if source_name and source.get("name") != source_name:
                    continue

                if "tables" in source:
                    for table in source["tables"]:
                        if table["name"] == table_name:
                            table_config = table.copy()
                            table_config["_source_name"] = source.get("name")
                            table_config["_source_description"] = source.get(
                                "description"
                            )
                            return table_config
            return None

        except Exception as e:
            self.logger.error(
                "Error retrieving dbt table configuration",
                exception=e,
                extra_data={"table_name": table_name, "source_name": source_name},
            )
            return None

    def get_available_dbt_sources(self) -> List[Dict[str, Any]]:
        """
        Get list of all available dbt sources and their tables.

        Returns:
            List of dictionaries containing source information
        """
        try:
            sources_info = []

            if not self.dbt_sources_config or "sources" not in self.dbt_sources_config:
                return sources_info

            for source in self.dbt_sources_config["sources"]:
                source_info = {
                    "name": source.get("name"),
                    "description": source.get("description", ""),
                    "tags": source.get("tags", []),
                    "tables": [],
                }

                if "tables" in source:
                    for table in source["tables"]:
                        table_info = {
                            "name": table.get("name"),
                            "description": table.get("description", ""),
                            "tags": table.get("tags", []),
                            "columns": len(table.get("columns", [])),
                        }
                        source_info["tables"].append(table_info)

                sources_info.append(source_info)

            return sources_info

        except Exception as e:
            self.logger.error("Error retrieving available dbt sources", exception=e)
            return []

    def _build_select_query(
        self,
        source_table: str,
        table_mapping: Optional[TableMapping] = None,
        incremental_config: Optional[IncrementalConfig] = None,
        last_timestamp: Optional[datetime] = None,
    ) -> str:
        """
        Build SELECT query for source data extraction.

        Args:
            source_table: Source table name
            table_mapping: Optional column mapping configuration
            incremental_config: Optional incremental loading configuration
            last_timestamp: Last timestamp for incremental loading

        Returns:
            SQL SELECT query string
        """
        if table_mapping and table_mapping.source_columns:
            columns = []
            for source_col, target_col in table_mapping.source_columns.items():
                if (
                    table_mapping.column_transformations
                    and source_col in table_mapping.column_transformations
                ):
                    transformation = table_mapping.column_transformations[source_col]
                    columns.append(f"{transformation} AS {target_col}")
                else:
                    columns.append(f"{source_col} AS {target_col}")
            select_clause = ", ".join(columns)
        else:
            select_clause = "*"

        query = f"SELECT {select_clause} FROM {source_table}"

        where_conditions = []

        if table_mapping and table_mapping.where_clause:
            where_conditions.append(table_mapping.where_clause)

        if incremental_config and last_timestamp:
            safe_timestamp = last_timestamp - timedelta(
                hours=incremental_config.lookback_hours
            )
            timestamp_condition = f"{incremental_config.source_timestamp_column} > '{safe_timestamp.strftime('%Y-%m-%d %H:%M:%S')}'"
            where_conditions.append(timestamp_condition)

        if where_conditions:
            query += " WHERE " + " AND ".join(where_conditions)

        if incremental_config:
            query += f" ORDER BY {incremental_config.source_timestamp_column}"

        return query

    def _get_last_timestamp(
        self, target_table: str, timestamp_column: str, schema: Optional[str] = None
    ) -> Optional[datetime]:
        """
        Get the last timestamp from target table for incremental loading.

        Args:
            target_table: Target table name
            timestamp_column: Timestamp column name
            schema: Optional schema name

        Returns:
            Last timestamp or None if table is empty
        """
        try:
            target_schema = schema or self.db_manager.sqlserver_config.schema
            query = f"""
                SELECT MAX({timestamp_column}) as max_timestamp 
                FROM {target_schema}.{target_table}
            """

            result = self.db_manager.execute_sqlserver_query(query, top_n=1)

            if result and len(result) > 0 and result[0][0]:
                last_timestamp = result[0][0]
                self.logger.info(
                    "Retrieved last timestamp from target table",
                    {
                        "table": f"{target_schema}.{target_table}",
                        "last_timestamp": str(last_timestamp),
                        "timestamp_column": timestamp_column,
                    },
                )
                return last_timestamp
            else:
                self.logger.info(
                    "No data found in target table, will perform full load",
                    {"table": f"{target_schema}.{target_table}"},
                )
                return None

        except Exception as e:
            self.logger.warning(
                "Could not retrieve last timestamp, performing full load",
                exception=e,
                extra_data={"table": target_table, "column": timestamp_column},
            )
            return None

    def _insert_dataframe_direct(
        self, df: pd.DataFrame, target_table: str, schema: str, connection=None
    ) -> int:
        """
        Inserts a pandas DataFrame directly into a SQL Server table.

        This method builds an INSERT statement using the DataFrame columns and inserts all rows.
        If the target table is a temporary table (name starts with '#'), schema is ignored.
        Returns the number of rows inserted.

        Args:
            df (pd.DataFrame): DataFrame containing the data to insert.
            target_table (str): Name of the target table in SQL Server.
            schema (str): Target schema name (ignored for temp tables).
            connection: Optional SQLAlchemy Connection object. If None, a new connection is created.

        Returns:
            int: Number of rows inserted.

        Example:
            If df contains:
                | id | name |
                |----|------|
                | 1  | John |
                | 2  | Jane |
            and target_table is "users", the function will insert both rows into [schema].[users].
        """
        if df.empty:
            self.logger.info(
                "No data to insert - DataFrame is empty",
                {"target_table": target_table, "schema": schema},
            )
            return 0
        df = clean_dataframe_for_sql(df)
        columns = list(df.columns)
        columns_str = ", ".join(f"[{col}]" for col in columns)
        placeholders = ", ".join([":" + col for col in columns])

        if target_table.startswith("#"):
            table_ref = target_table
        elif schema and schema.strip():
            table_ref = f"[{schema}].[{target_table}]"
        else:
            table_ref = f"[{target_table}]"

        sql = f"INSERT INTO {table_ref} ({columns_str}) VALUES ({placeholders})"
        records = df.to_dict("records")

        self.logger.info(
            "Inserting DataFrame into table",
            {
                "target_table": table_ref,
                "rows_to_insert": len(records),
                "columns": columns,
            },
        )

        if connection:
            result = connection.execute(text(sql), records)
            self.logger.info(
                "Insert completed using provided connection",
                {"rows_inserted": len(records)},
            )
            return len(records)
        else:
            engine = self.db_manager.get_sqlserver_engine()
            with engine.begin() as conn:
                result = conn.execute(text(sql), records)
                self.logger.info(
                    "Insert completed using new connection",
                    {"rows_inserted": len(records)},
                )
                return len(records)

    def _perform_upsert(
        self,
        df: pd.DataFrame,
        target_table: str,
        upsert_config: UpsertConfig,
        schema: str,
        table_mapping: Optional[TableMapping] = None,
        connection: Optional[Connection] = None,
    ) -> Tuple[int, int]:
        """
        Perform UPSERT operation using SQL Server MERGE statement.

        This method creates a temporary table with the new data and uses SQL Server's MERGE
        statement to either UPDATE existing records or INSERT new ones based on the key columns
        defined in upsert_config.

        Args:
            df: DataFrame with data to upsert
            target_table: Target table name
            upsert_config: Configuration specifying source and target key columns for matching
            schema: Target schema name
            table_mapping: Optional column mapping between source and target
            connection: Optional database connection (if None, creates new one)

        Returns:
            Tuple of (rows_inserted, rows_updated)
        """
        if df.empty:
            return 0, 0

        if connection is None:
            engine = self.db_manager.get_sqlserver_engine()

            with engine.begin() as conn:
                return self._execute_upsert_with_connection(
                    conn, df, target_table, upsert_config, schema, table_mapping
                )
        else:
            return self._execute_upsert_with_connection(
                conn, df, target_table, upsert_config, schema, table_mapping
            )

    def _execute_upsert_with_connection(
        self,
        connection,
        df: pd.DataFrame,
        target_table: str,
        upsert_config: UpsertConfig,
        schema: str,
        table_mapping: Optional[TableMapping] = None,
    ) -> Tuple[int, int]:
        """
        Executes the UPSERT (MERGE) operation in SQL Server using a provided connection.

        This method creates a temporary table with the new data, then performs a MERGE statement
        to update existing records or insert new ones based on the key columns defined in upsert_config.
        After the operation, the temporary table is dropped.

        Args:
            connection: SQLAlchemy Connection object to SQL Server.
            df (pd.DataFrame): DataFrame containing the data to upsert.
            target_table (str): Name of the target table in SQL Server.
            upsert_config (UpsertConfig): Configuration specifying source and target key columns for matching.
            schema (str): Target schema name.
            table_mapping (Optional[TableMapping]): Optional mapping between source and target columns.

        Returns:
            Tuple[int, int]: Number of rows inserted and updated, respectively.

        Example:
            Suppose df contains:
                | id | name | updated_at |
                |----|------|------------|
                | 1  | John | 2024-01-01 |
                | 2  | Jane | 2024-01-02 |

            And upsert_config specifies 'id' as the key column.
            The function will:
                1. Create a temp table with the same structure as target_table.
                2. Insert df into the temp table.
                3. Run a MERGE statement to update rows in target_table where id matches,
                or insert new rows if id does not exist.
                4. Return (rows_inserted, rows_updated).
        """
        if df.empty:
            self.logger.info(
                "No data to upsert - DataFrame is empty",
                {"target_table": target_table, "schema": schema},
            )
            return 0, 0

        temp_table = f"{target_table}_temp_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]}"

        try:
            connection.execute(text("SET LOCK_TIMEOUT 30000"))
            self.logger.info(
                "Creating temporary table for upsert",
                {"temp_table": temp_table, "target_table": target_table},
            )
            create_temp_sql = f"""
                SELECT TOP 0 *
                INTO #{temp_table}
                FROM {schema}.{target_table}
                """
            connection.execute(text(create_temp_sql))

            self._insert_dataframe_direct(df, f"#{temp_table}", "", connection)
            self.logger.info(
                "Inserted data into temporary table",
                {"temp_table": temp_table, "rows": len(df)},
            )

            all_columns = df.columns.tolist()
            source_key_cols = upsert_config.source_key_columns
            target_key_cols = upsert_config.target_key_columns

            if table_mapping and table_mapping.source_columns:
                mapped_source_keys = []
                mapped_target_keys = []
                for i, source_key in enumerate(source_key_cols):
                    if source_key in table_mapping.source_columns:
                        mapped_source_keys.append(
                            table_mapping.source_columns[source_key]
                        )
                        mapped_target_keys.append(target_key_cols[i])
                    else:
                        mapped_source_keys.append(source_key)
                        mapped_target_keys.append(target_key_cols[i])
                actual_source_keys = mapped_source_keys
                actual_target_keys = mapped_target_keys
            else:
                actual_source_keys = source_key_cols
                actual_target_keys = target_key_cols

            join_conditions = []
            for source_col, target_col in zip(actual_source_keys, actual_target_keys):
                join_conditions.append(f"target.[{target_col}] = source.[{source_col}]")
            join_condition = " AND ".join(join_conditions)

            self.logger.info(
                "Preparing MERGE statement for upsert",
                {
                    "target_table": target_table,
                    "merge_keys": actual_target_keys,
                    "source_keys": actual_source_keys,
                    "non_key_columns": [
                        col for col in all_columns if col not in actual_source_keys
                    ],
                },
            )

            non_key_columns = [
                col for col in all_columns if col not in actual_source_keys
            ]

            if non_key_columns:
                update_assignments = []
                for col in non_key_columns:
                    update_assignments.append(f"[{col}] = source.[{col}]")
                update_clause = ", ".join(update_assignments)
            else:
                update_clause = (
                    f"[{actual_target_keys[0]}] = source.[{actual_source_keys[0]}]"
                )

            insert_columns = ", ".join([f"[{col}]" for col in all_columns])
            insert_values = ", ".join([f"source.[{col}]" for col in all_columns])

            merge_sql = f"""
                MERGE {schema}.{target_table} AS target
                USING #{temp_table} AS source
                ON {join_condition}
                WHEN MATCHED THEN
                    UPDATE SET {update_clause}
                WHEN NOT MATCHED THEN
                    INSERT ({insert_columns})
                    VALUES ({insert_values})
                OUTPUT $action;
                """

            self.logger.info(
                "Executing MERGE statement",
                {
                    "merge_sql_preview": (
                        merge_sql[:200] + "..." if len(merge_sql) > 200 else merge_sql
                    )
                },
            )

            result = connection.execute(text(merge_sql))

            actions = list(result)
            rows_inserted = sum(1 for row in actions if row[0] == "INSERT")
            rows_updated = sum(1 for row in actions if row[0] == "UPDATE")

            self.logger.info(
                "Upsert completed",
                {
                    "rows_inserted": rows_inserted,
                    "rows_updated": rows_updated,
                    "target_table": target_table,
                },
            )

            return rows_inserted, rows_updated

        finally:
            try:
                connection.execute(text(f"DROP TABLE IF EXISTS #{temp_table}"))
                self.logger.info(
                    "Temporary table dropped after upsert", {"temp_table": temp_table}
                )
            except Exception as e:
                self.logger.warning(
                    "Failed to drop temporary table after upsert",
                    {"temp_table": temp_table, "error": str(e)},
                )

    def incremental_load(
        self,
        source_name: str,
        target_table: str,
        incremental_config: IncrementalConfig,
        source_table: Optional[str] = None,
        table_mapping: Optional[TableMapping] = None,
        target_schema: Optional[str] = None,
        upsert_config: Optional[UpsertConfig] = None,
        source_query: Optional[str] = None,
    ) -> LoadResult:
        """
        Performs incremental data loading from a MySQL source table to a SQL Server target table.

        Now supports automatic timestamp injection in custom queries using placeholders:
        - {last_timestamp} - Gets replaced with the actual last timestamp from target
        - {safe_timestamp} - Gets replaced with last_timestamp minus lookback_hours

        Args:
            source_name (str): Name of the MySQL source connection.
            source_table (Optional[str]): Name of the source table in MySQL. Required unless using source_query.
            target_table (str): Name of the target table in SQL Server.
            incremental_config (IncrementalConfig): Configuration for incremental loading.
            table_mapping (Optional[TableMapping]): Optional mapping between source and target columns.
            target_schema (Optional[str]): Optional schema name for the target table in SQL Server.
            upsert_config (Optional[UpsertConfig]): Optional configuration for upsert operations.
            source_query (Optional[str]): Optional custom SQL query. Can use {last_timestamp} and {safe_timestamp} placeholders.

        Returns:
            LoadResult: Object containing details about the load operation.
        """
        start_time = datetime.now()
        result = LoadResult(success=False)

        try:
            schema = target_schema or self.db_manager.sqlserver_config.schema

            self.logger.info(
                "Starting incremental load operation",
                {
                    "source_name": source_name,
                    "source_table": source_table,
                    "target_table": f"{schema}.{target_table}",
                    "source_timestamp_columns": ", ".join(
                        incremental_config.source_timestamp_columns
                    ),
                    "target_timestamp_column": incremental_config.target_timestamp_column,
                    "full_refresh": incremental_config.full_refresh,
                    "batch_size": incremental_config.batch_size,
                    "upsert_enabled": upsert_config is not None,
                    "custom_query": bool(source_query),
                },
            )

            last_timestamp = None
            safe_timestamp = None

            if not incremental_config.full_refresh:
                last_timestamp = self._get_last_timestamp(
                    target_table, incremental_config.target_timestamp_column, schema
                )

                if last_timestamp:
                    safe_timestamp = last_timestamp - timedelta(
                        hours=incremental_config.lookback_hours
                    )

                    self.logger.info(
                        "Timestamp information retrieved",
                        {
                            "last_timestamp": str(last_timestamp),
                            "safe_timestamp": str(safe_timestamp),
                            "lookback_hours": incremental_config.lookback_hours,
                        },
                    )
                else:
                    safe_timestamp = datetime(1900, 1, 1)
                    self.logger.info(
                        "First execution detected - will fetch all records"
                    )

            if source_query:
                query = self._process_query_placeholders(
                    source_query,
                    last_timestamp,
                    safe_timestamp,
                    incremental_config.full_refresh,
                    incremental_config.source_timestamp_columns,
                )
            else:
                if not source_table:
                    raise ValueError(
                        "source_table must be provided if not using source_query"
                    )
                query = self._build_select_query(
                    source_table, table_mapping, incremental_config, last_timestamp
                )

            self.logger.debug(
                "Executing query",
                {"query_preview": query[:200] + "..." if len(query) > 200 else query},
            )

            source_data = self.db_manager.execute_mysql_query(source_name, query)

            if not source_data:
                self.logger.info("No new data found for incremental load")
                result.success = True
                result.rows_processed = 0
                result.execution_time_seconds = (
                    datetime.now() - start_time
                ).total_seconds()
                return result

            total_rows = len(source_data)
            result.rows_processed = total_rows

            if table_mapping and table_mapping.target_columns:
                columns = table_mapping.target_columns
            else:
                columns = list(source_data[0].keys())

            df = pd.DataFrame(source_data, columns=columns)
            batch_size = incremental_config.batch_size
            total_inserted = 0
            total_updated = 0

            for i in range(0, len(df), batch_size):
                batch_df = df.iloc[i : i + batch_size]

                if upsert_config:
                    inserted, updated = self._perform_upsert(
                        batch_df, target_table, upsert_config, schema, table_mapping
                    )
                    total_inserted += inserted
                    total_updated += updated
                else:
                    batch_inserted = self._insert_dataframe_direct(
                        batch_df, target_table, schema
                    )
                    total_inserted += batch_inserted

                self.logger.debug(
                    f"Processed batch {i//batch_size + 1}, rows: {len(batch_df)}"
                )

            result.rows_inserted = total_inserted
            result.rows_updated = total_updated
            result.success = True
            execution_time = (datetime.now() - start_time).total_seconds()
            result.execution_time_seconds = execution_time

            self.logger.info(
                "Incremental load completed successfully",
                {
                    "source_name": source_name,
                    "source_table": source_table,
                    "target_table": f"{schema}.{target_table}",
                    "rows_processed": result.rows_processed,
                    "rows_inserted": result.rows_inserted,
                    "rows_updated": result.rows_updated,
                    "execution_time_seconds": round(execution_time, 2),
                    "batches_processed": (total_rows // batch_size) + 1,
                },
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            result.execution_time_seconds = execution_time
            result.error_message = str(e)

            self.logger.error(
                "Incremental load failed",
                exception=e,
                extra_data={
                    "source_name": source_name,
                    "source_table": source_table,
                    "target_table": target_table,
                    "execution_time_seconds": round(execution_time, 2),
                },
            )

        return result

    def _process_query_placeholders(
        self,
        source_query: str,
        last_timestamp: Optional[datetime],
        safe_timestamp: Optional[datetime],
        full_refresh: bool,
        source_timestamp_columns: List[str],
    ) -> str:
        """
        Replaces timestamp placeholders in a custom SQL query for incremental loads.

        This function supports two placeholders:
        - {safe_timestamp}: Replaced with the safe timestamp string (last_timestamp minus lookback_hours, or '1900-01-01 00:00:00' for full refresh/first execution).
        - {last_timestamp}: (Not currently used, but can be added for future needs.)

        If this is the first execution (no last_timestamp) and not a full refresh, it also modifies the WHERE clause to include records where the timestamp column is NULL.

        Args:
            source_query (str): The custom SQL query containing placeholders.
            last_timestamp (Optional[datetime]): The last timestamp found in the target table.
            safe_timestamp (Optional[datetime]): The safe timestamp for incremental loading.
            full_refresh (bool): If True, performs a full refresh (loads all records).
            source_timestamp_column (str): The name of the timestamp column in the source table.

        Returns:
            str: The processed query with placeholders replaced.

        Example:
            If source_query is:
                "SELECT * FROM users WHERE (updated_at > '{safe_timestamp}')"
            and this is the first execution (no last_timestamp, not full_refresh),
            the result will be:
                "SELECT * FROM users WHERE (updated_at > '1900-01-01 00:00:00' OR updated_at IS NULL)"
        """
        is_first_execution = last_timestamp is None

        if full_refresh or is_first_execution:
            safe_ts_str = "1900-01-01 00:00:00"
        else:
            safe_ts_str = safe_timestamp.strftime("%Y-%m-%d %H:%M:%S")

        processed_query = source_query.replace("{safe_timestamp}", f"'{safe_ts_str}'")

        if is_first_execution and not full_refresh:
            null_checks = " ".join(
                [f"OR {col} IS NULL" for col in source_timestamp_columns]
            )
            processed_query = processed_query.replace(
                "{first_run_null_check}", null_checks
            )
        else:
            processed_query = processed_query.replace("{first_run_null_check}", "")

        return processed_query

    def batch_loader(
        self,
        source_type: str,
        source_schema: str,
        source_table: str,
        target_schema: str,
        target_table: str,
        source_name: Optional[str] = None,
        table_mapping: Optional[TableMapping] = None,
        chunk_size: int = 100000,
        if_exists: str = "append",
    ) -> LoadResult:
        """
        Generic batch loader to move data from MySQL or SQL Server into SQL Server.

        This function fetches data from the source (MySQL or SQL Server) and loads it into a
        SQL Server target table. The target table is created automatically if it does not exist,
        based on inferred data types. Note that constraints, primary keys, and indexes are not
        automatically created.

        Args:
            source_type: "mysql" or "sqlserver".
            source_schema: Source schema (used only for SQL Server sources).
            source_table: Source table name.
            target_schema: Destination schema in SQL Server.
            target_table: Destination table in SQL Server.
            source_name: MySQL source name (required if source_type="mysql").
            table_mapping: Optional TableMapping object to transform columns or apply where clauses.
            chunk_size: Number of rows per insert batch.
            if_exists: Behavior if target table exists: "append", "replace", or "fail".

        Returns:
            LoadResult: Contains success status, rows processed/inserted, execution time, and error message if any.
        """
        start_time = datetime.now()
        result = LoadResult(success=False)

        try:
            # Construir query de origem
            if source_type.lower() == "sqlserver":
                query = f"SELECT * FROM {source_schema}.{source_table}"
            elif source_type.lower() == "mysql":
                query = f"SELECT * FROM {source_table}"
            else:
                raise ValueError(f"Unsupported source_type: {source_type}")

            source_data = self.db_manager.fetch_data(
                source_type=source_type,
                query=query,
                source_name=source_name,
                schema=source_schema if source_type == "sqlserver" else None,
            )

            if not source_data:
                self.logger.info(
                    "Batch load concluído: Nenhum dado encontrado na tabela origem",
                    {
                        "source": f"{source_schema}.{source_table}",
                        "target": f"{target_schema}.{target_table}",
                    },
                )
                result.success = True
                result.rows_processed = 0
                result.execution_time_seconds = (
                    datetime.now() - start_time
                ).total_seconds()
                return result

            columns = list(source_data[0].keys())
            df = pd.DataFrame(source_data, columns=columns)
            result.rows_processed = len(df)

            if table_mapping and hasattr(table_mapping, "transform"):
                df = table_mapping.transform(df)

            engine = self.db_manager.get_sqlserver_engine()
            with engine.begin() as conn:
                for i in range(0, len(df), chunk_size):
                    chunk_df = df.iloc[i : i + chunk_size]
                    self._insert_dataframe_direct(
                        chunk_df, target_table, target_schema, conn
                    )

            result.rows_inserted = result.rows_processed
            result.success = True
            execution_time = (datetime.now() - start_time).total_seconds()
            result.execution_time_seconds = execution_time

            self.logger.info(
                "Batch load concluído com sucesso",
                {
                    "source_type": source_type,
                    "source": f"{source_schema}.{source_table}",
                    "target": f"{target_schema}.{target_table}",
                    "rows_processed": result.rows_processed,
                    "rows_inserted": result.rows_inserted,
                    "execution_time_seconds": round(execution_time, 2),
                    "query_preview": query[:100] + "..." if len(query) > 100 else query,
                },
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            result.error_message = str(e)
            result.execution_time_seconds = execution_time
            self.logger.error(
                "Batch load falhou",
                exception=e,
                extra_data={
                    "source_type": source_type,
                    "source": f"{source_schema}.{source_table}",
                    "target": f"{target_schema}.{target_table}",
                    "rows_processed": result.rows_processed,
                    "execution_time_seconds": round(execution_time, 2),
                    "query_preview": query[:100] + "..." if len(query) > 100 else query,
                },
            )

        return result

    def validate_table_compatibility(
        self,
        source_name: str,
        source_table: str,
        target_table: str,
        table_mapping: Optional[TableMapping] = None,
        target_schema: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate compatibility between source and target tables.

        Args:
            source_name: MySQL source name
            source_table: Source table name
            target_table: Target table name
            table_mapping: Optional column mapping
            target_schema: Optional target schema

        Returns:
            Dictionary with validation results
        """
        try:
            validation_result = {
                "compatible": False,
                "issues": [],
                "recommendations": [],
                "source_columns": [],
                "target_columns": [],
                "mapping_coverage": 0.0,
            }

            with self.db_manager.mysql_connection(source_name) as source_conn:
                source_schema = self._get_table_schema(source_conn, source_table)
                validation_result["source_columns"] = source_schema["column_names"]

            schema = target_schema or self.db_manager.sqlserver_config.schema
            with self.db_manager.sqlserver_connection() as target_conn:
                target_schema_info = self._get_table_schema(
                    target_conn, target_table, schema
                )
                validation_result["target_columns"] = target_schema_info["column_names"]

            if table_mapping and table_mapping.source_columns:
                missing_source = set(table_mapping.source_columns.keys()) - set(
                    source_schema["column_names"]
                )
                if missing_source:
                    validation_result["issues"].append(
                        f"Missing source columns: {list(missing_source)}"
                    )

                missing_target = set(table_mapping.source_columns.values()) - set(
                    target_schema_info["column_names"]
                )
                if missing_target:
                    validation_result["issues"].append(
                        f"Missing target columns: {list(missing_target)}"
                    )

                validation_result["mapping_coverage"] = len(
                    table_mapping.source_columns
                ) / len(source_schema["column_names"])
            else:
                common_columns = set(source_schema["column_names"]).intersection(
                    set(target_schema_info["column_names"])
                )
                validation_result["mapping_coverage"] = len(common_columns) / len(
                    source_schema["column_names"]
                )

                if validation_result["mapping_coverage"] < 0.5:
                    validation_result["issues"].append(
                        "Low column compatibility - consider explicit mapping"
                    )

            validation_result["compatible"] = len(validation_result["issues"]) == 0

            if not validation_result["compatible"]:
                validation_result["recommendations"].append(
                    "Review column mappings and data types"
                )
                validation_result["recommendations"].append(
                    "Consider using TableMapping to handle differences"
                )

            self.logger.info(
                "Table compatibility validation completed",
                {
                    "source_table": source_table,
                    "target_table": f"{schema}.{target_table}",
                    "compatible": validation_result["compatible"],
                    "mapping_coverage": round(validation_result["mapping_coverage"], 2),
                    "issues_count": len(validation_result["issues"]),
                },
            )

            return validation_result

        except Exception as e:
            self.logger.error(
                "Table compatibility validation failed",
                exception=e,
                extra_data={"source_table": source_table, "target_table": target_table},
            )
            return {
                "compatible": False,
                "issues": [f"Validation error: {str(e)}"],
                "recommendations": ["Fix validation errors before proceeding"],
                "source_columns": [],
                "target_columns": [],
                "mapping_coverage": 0.0,
            }


def get_copy_loader(
    db_manager: Optional[DatabaseConnectionManager] = None,
    dbt_config_file: Optional[str] = None,
) -> CopyAndLoader:
    """
    Factory function to create CopyAndLoader instance.

    Args:
        db_manager: Optional database connection manager
        dbt_config_file: Optional path to dbt sources config file

    Returns:
        CopyAndLoader instance
    """
    return CopyAndLoader(db_manager, dbt_config_file)

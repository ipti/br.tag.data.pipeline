# Plan: Neo4j Incremental Pipeline

This document defines the implementation plan for the incremental Neo4j synchronization DAG, designed to process only new or changed data from the SQL Server Data Warehouse (`dbo_tia` schema) into Neo4j.

## 1. Architectural Strategy

The incremental pipeline will leverage the existing upsert capabilities of Cypher (`MERGE`) combined with Airflow's Jinja templating for time-bounding SQL extraction. 

**Maximized Reuse:** 
- The target Cypher scripts (`src/utils/neo4j/queries.py`) remain **100% untouched** since `MERGE` inherently handles Upserts (Creates if not exists, Updates if exists).
- The `Neo4jIngestor` class and `stream_to_neo4j` Python callable will be reused.
- The Python Transformer logic (ID slicing) will be extracted into a shared module to avoid code duplication across Full and Incremental DAGs.

## 2. Phase 1: Refactoring for Reusability (DRY Principle)

Currently, the Transformer functions (e.g., `transform_school_node`, `transform_avaliation_student`) and the `stream_to_neo4j` function live inside `dag__neo4j_full_migration.py`. 

- **Task 1.1:** Create `src/utils/neo4j/transformers.py`.
- **Task 1.2:** Move all 9 transformer functions from `dag__neo4j_full_migration.py` into this new file.
- **Task 1.3:** Create `src/utils/neo4j/airflow_tasks.py` (optional, or keep `stream_to_neo4j` in a shared location) so both DAGs use the exact same streaming execution code.

## 3. Phase 2: Creating the Incremental DAG

Create a new file: `dags/dag__neo4j_incremental_migration.py`.

### 3.1 Time-Bound SQL Queries
We will redefine the SQL extraction strings to include a `WHERE` clause using Airflow's Jinja templating. The best practice for Airflow incremental loads is to use `{{ data_interval_start }}` and `{{ data_interval_end }}` or `{{ prev_data_interval_end_success }}`.

*Example pattern for all 10 SQL Queries:*
```sql
SELECT HASH_ID as id, name, ...
FROM dbo_tia.d_school
WHERE updated_at >= '{{ prev_data_interval_end_success | default(data_interval_start) }}'
   OR inserted_at >= '{{ prev_data_interval_end_success | default(data_interval_start) }}'
```

### 3.2 Target Tables & Attributes
All 10 Tables and 12 Relationships will be included using the exact same flow:
- `Dimension Nodes` (Student, School, Classroom, Health, SchoolGeograph, StudentDiscipline)
- `Fact Nodes` (Avaliation, Class, StudentClass)
- `Relationships` (Enrollment, Geograph, Held_At, Evaluated_In, etc.)

## 4. Phase 3: Edge Cases and Deletions

- **Upserts vs Hard Deletes:** `MERGE` handles creation and updates. However, it *does not* delete nodes removed from the SQL Server.
- **Decision:** As standard practice for Warehouse -> Graph, we will only handle Upserts in the incremental. If soft-deletes exist (`status = 'DELETED'`), the `SET` block in Cypher will update the Neo4j node status, which is the desired behavior.
- **Relationship updates:** Cypher `MERGE (a)-[r:REL]->(b)` will not delete old relationships if a node changes its parent (e.g. Student changes Classroom). `MERGE` will create a *second* relationship. 
  *Solution (to be discussed):* Does the standard ETL logic emit hard deletes or rely on soft updates? If `F_ENROLLMENT` changes, we might need a specific handling for `MERGE` to replace the relation, or assume `F_ENROLLMENT` immutable per year/term.

## 5. Execution Order

1. **Wait Mechanism:** The DAG should have an `ExternalTaskSensor` waiting for the SQL Data Warehouse incremental pipeline (`dag__workflow-warehouse__incremental_upsert__prod`) to finish.
2. **Dimension Load:** Load all nodes concurrently except constraints.
3. **Fact Load:** Load facts concurrently.
4. **Relationship Load:** Build edges.

## Verification Checklist
- [ ] `transformers.py` created and imported into both DAGs.
- [ ] `dag__neo4j_incremental_migration.py` created.
- [ ] All 17 SQL queries updated with `WHERE updated_at >= '{{ ... }}'`.
- [ ] Both DAGs successfully parsed by Airflow (`airflow dags reserialize`).

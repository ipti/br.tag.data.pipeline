# Features Documentation

This directory contains the core feature engineering operations, defining schemas, extracting from Neo4j, aggregating, and assembling the encoded feature matrix for our models.

## Structure
- `feature_pipeline.py`: Contains the logic for raw DataFrame processing and feature engineering matrix building.
- `neo4j_extractor.py`: Defines Cypher queries and extracts feature data from Neo4j in a clean isolation pattern.
- `schema.py`: Dictates feature set contracts and schemas utilized throughout the ML system.
- `school_aggregator.py`: Provides school-level aggregations from extracted student-level records.

## feature_pipeline.py
Feature engineering pipeline mapping raw DataFrames to encoded feature matrices. This is strictly separated from `neo4j_extractor.py` to allow unit testing without requiring an active Neo4j connection.

**Key design decisions:**
1. **Missing Grades (Sentinel Value):** Missing grades are explicitly filled with `-1` (instead of `0` or median) up front. Absence of a grade contains meaningful information (i.e. the school doesn't register grades for students) and `-1` preserves this signal correctly for tree-based models to split explicitly.
2. **Missing IBGE Fields:** IBGE fields are filled in Cypher with a UF proxy. If still null (such as State-level fields missing values entirely), they fall back to column median via the sklearn imputation pipeline.
3. **Mandatory Temporal Splits:** The dataset cannot be randomly split because the same student may appear across different school years and would inflate metrics. Data is always split temporally.
4. **Source Flag Elimination:** Source flag indicator columns (e.g. `muni_freq_fonte`) are dropped out of the model feature matrix but retained for pipeline data monitoring.

*References*:
- Feature contracts: schema.py
- IBGE sparsity documentation: neo4_schema_and_tips.md §4.4
- Performance anti-patterns: neo4_schema_and_tips.md §6

## neo4j_extractor.py
Neo4j feature extraction layer. Defines all raw Cypher queries, keeping the Neo4j Python driver strictly contained. Each public extraction method returns a natively typed Pandas DataFrame suitable for consumption by `feature_pipeline.py`.

**Query Design Considerations:**
Uses a `collect → isolate → aggregate` performance pattern. Optional MATCHes are separated inside individual `CALL` blocks (one for attendance, one for grades, etc.), circumventing N×M×K cartesian performance blowups.

**IBGE Fallback Details:**
Because many municipalities carry absent tracking fields (such as racial equity), a one-time pre-computation queries a fallback UF-level average. This average is passed dynamically as Cypher parameters `($uf_avg... )` and saves extreme N+1 complexity during actual extraction.

**Architecture — streaming generation:**
- Schools are natively grouped and fetched by UF.
- IBGE UF averages are fetched one-time per UF.
- School chunks are sent to Parquet via PyArrow `RecordBatchWriter` (no large DataFrame accumulation in RAM).
- Single persistent Neo4j sessions are heavily recycled locally to sidestep network exhaustion.
- Explicit PyArrow schemas are supplied to guard against null-only chunk inference bugs.

*References*:
- EF1 extraction query: PLAN-ML-NEO4J-SCHOOL.md §3.1
- EF2 grade pivot query: PLAN-ML-NEO4J-SCHOOL.md §3.2
- Full analytic query matrix: CYPHER-QUERY-MATRIX-ML.md Q1–Q15
- Dropout risk score structure: Q_RISCO_EVASAO_EF2.md

## schema.py
Feature set contracts that enforce our models' input domains. Provides exact array shapes, categorical mapping dictionaries, target labels, and lists of columns that are explicitly barred from ever retaining nulls at the end of the pipeline.

If any feature is altered, added, or dropped, the change must be initialized here rather than hard-coded down the execution lines.

*References*:
- Node properties: neo4_schema_and_tips.md §1-2
- Canonical grade_level filters: neo4_schema_and_tips.md §5
- Municipality IBGE sparsity: neo4_schema_and_tips.md §4.4

## school_aggregator.py
School-level dimension aggregation derived strictly from student-level datasets post-extraction. Yields downstream school metrics: overall health score, BF concentration, failing grades alerts, and electronic journal tracking flags.

Because this transformation is entirely computational, it never calls Neo4j nor produces external file streams. Used heavily by string serialization for the LLM embedder and `/report/school/{id}` inference API calls.

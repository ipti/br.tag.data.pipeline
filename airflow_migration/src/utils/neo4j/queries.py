"""
Neo4j Queries Module.

This module contains the Cypher queries used to ingest data into the Neo4j graph.
Queries use the UNWIND pattern to process batches of data efficiently.
"""

# Index Creation Queries
CREATE_INDEX_STUDENT = "CREATE INDEX IF NOT EXISTS FOR (s:Student) ON (s.id)"
CREATE_INDEX_SCHOOL = "CREATE INDEX IF NOT EXISTS FOR (s:School) ON (s.inep_id)"
CREATE_INDEX_CLASSROOM = "CREATE INDEX IF NOT EXISTS FOR (c:Classroom) ON (c.id)"

# Node Merge Queries
MERGE_STUDENT = """
UNWIND $rows AS row
MERGE (s:Student {id: row.id})
SET s.name = row.name,
    s.birth_city = row.birth_city,
    s.gender = row.gender,
    s.ethnicity = row.ethnicity,
    s.deficiency = row.deficiency,
    s.updated_at = row.updated_at
"""

MERGE_SCHOOL = """
UNWIND $rows AS row
MERGE (s:School {inep_id: row.inep_id})
SET s.name = row.name,
    s.location_lat = row.latitude,
    s.location_lon = row.longitude,
    s.address = row.address,
    s.situation = row.situation,
    s.updated_at = row.updated_at
"""

MERGE_CLASSROOM = """
UNWIND $rows AS row
MERGE (c:Classroom {id: row.id})
SET c.year = row.year,
    c.grade_level = row.grade_level,
    c.stage = row.stage,
    c.updated_at = row.updated_at
"""

# Relationship Merge Queries
# Expects rows with: student_id, classroom_id, status, year
LINK_ENROLLMENT = """
UNWIND $rows AS row
MATCH (s:Student {id: row.student_id})
MATCH (c:Classroom {id: row.classroom_id})
MERGE (s)-[r:ENROLLED_IN]->(c)
SET r.status = row.status,
    r.year = row.year,
    r.updated_at = row.updated_at
"""

# Link Classroom to School
# Expects rows with: classroom_id, school_id
LINK_CLASS_SCHOOL = """
UNWIND $rows AS row
MATCH (c:Classroom {id: row.classroom_id})
MATCH (s:School {inep_id: row.school_id})
MERGE (c)-[r:HELD_AT]->(s)
SET r.updated_at = row.updated_at
"""

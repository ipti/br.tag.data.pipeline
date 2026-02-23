"""
Neo4j Queries Module.

This module contains the Cypher queries used to ingest data into the Neo4j graph.
Queries use the UNWIND pattern to process batches of data efficiently.

Tables covered (dbo_tia):
  Dimensions: D_STUDENT, D_SCHOOL, D_CLASSROOM, D_HEALTH, D_SCHOOL_GEOGRAPH, D_STUDENT_DISCIPLINE
  Facts:      F_AVALIATION, F_CLASS, F_ENROLLMENT, F_STUDENT_CLASS

Relationships (12 total):
  ENROLLED_IN, ENROLLED_AT_SCHOOL, HAS_HEALTH, HELD_AT, HAS_GEOGRAPHY,
  HAS_DISCIPLINE, EVALUATED_IN, AVALIATION_OF, TAUGHT_IN, CLASS_AT_SCHOOL,
  ATTENDED, ATTENDANCE_OF
"""

# ============================================================
# INDEX CREATION
# ============================================================

CREATE_INDEX_STUDENT = "CREATE INDEX IF NOT EXISTS FOR (s:Student) ON (s.id)"
CREATE_INDEX_SCHOOL = "CREATE INDEX IF NOT EXISTS FOR (s:School) ON (s.id)"
CREATE_INDEX_CLASSROOM = "CREATE INDEX IF NOT EXISTS FOR (c:Classroom) ON (c.id)"
CREATE_INDEX_HEALTH = "CREATE INDEX IF NOT EXISTS FOR (h:Health) ON (h.id)"
CREATE_INDEX_SCHOOL_GEOGRAPH = "CREATE INDEX IF NOT EXISTS FOR (g:SchoolGeograph) ON (g.id)"
CREATE_INDEX_STUDENT_DISCIPLINE = "CREATE INDEX IF NOT EXISTS FOR (sd:StudentDiscipline) ON (sd.id)"
CREATE_INDEX_AVALIATION = "CREATE INDEX IF NOT EXISTS FOR (a:Avaliation) ON (a.id)"
CREATE_INDEX_CLASS = "CREATE INDEX IF NOT EXISTS FOR (cl:Class) ON (cl.id)"
CREATE_INDEX_STUDENT_CLASS = "CREATE INDEX IF NOT EXISTS FOR (sc:StudentClass) ON (sc.id)"

ALL_INDEXES = [
    CREATE_INDEX_STUDENT,
    CREATE_INDEX_SCHOOL,
    CREATE_INDEX_CLASSROOM,
    CREATE_INDEX_HEALTH,
    CREATE_INDEX_SCHOOL_GEOGRAPH,
    CREATE_INDEX_STUDENT_DISCIPLINE,
    CREATE_INDEX_AVALIATION,
    CREATE_INDEX_CLASS,
    CREATE_INDEX_STUDENT_CLASS,
]

# ============================================================
# NODE MERGE QUERIES – Dimensions
# ============================================================

MERGE_STUDENT = """
UNWIND $rows AS row
MERGE (s:Student {id: row.id})
SET s.name = row.name,
    s.birth_city = row.birth_city,
    s.gender = row.gender,
    s.ethnicity = row.ethnicity,
    s.deficiency = row.deficiency,
    s.birthday = row.birthday,
    s.bolsa_familia = row.bolsa_familia_participator,
    s.mother_name = row.mother_name,
    s.father_name = row.father_name,
    s.student_cpf = row.student_cpf,
    s.residence_zone = row.residence_zone,
    s.city_address = row.city_address,
    s.uf = row.uf,
    s.updated_at = row.inserted_at
"""

MERGE_SCHOOL = """
UNWIND $rows AS row
MERGE (s:School {id: row.id})
SET s.name = row.name,
    s.latitude = row.latitude,
    s.longitude = row.longitude,
    s.address = row.address,
    s.number_address = row.number_address,
    s.address_complement = row.address_complement,
    s.address_neighborhood = row.address_neighborhood,
    s.situation = row.situation,
    s.updated_at = row.inserted_at
"""

MERGE_CLASSROOM = """
UNWIND $rows AS row
MERGE (c:Classroom {id: row.id})
SET c.name = row.name,
    c.year = row.class_year,
    c.grade_level = row.serie,
    c.stage = row.stage,
    c.status = row.status,
    c.updated_at = row.inserted_at
"""

MERGE_HEALTH = """
UNWIND $rows AS row
MERGE (h:Health {id: row.id})
SET h.celiac = row.celiac_desase,
    h.diabetes = row.diabetes_desease,
    h.hypertension = row.hypertension_desease,
    h.iron_deficiency_anemia = row.iron_deficiency_anemia_desease,
    h.lactose_intolerance = row.lactose_intolerance_desease,
    h.malnutrition = row.malnutrition_desease,
    h.obesity = row.obesity_desease,
    h.sickle_cell_anemia = row.sickle_cell_anemia,
    h.other_problems = row.other_health_problems,
    h.updated_at = row.updated_at
"""

MERGE_SCHOOL_GEOGRAPH = """
UNWIND $rows AS row
MERGE (g:SchoolGeograph {id: row.id})
SET g.cep = row.cep,
    g.city = row.city,
    g.uf = row.uf,
    g.updated_at = row.inserted_at
"""

MERGE_STUDENT_DISCIPLINE = """
UNWIND $rows AS row
MERGE (sd:StudentDiscipline {id: row.id})
SET sd.discipline_name = row.discipline_name,
    sd.grade_1 = row.grade_1,
    sd.grade_2 = row.grade_2,
    sd.grade_3 = row.grade_3,
    sd.grade_4 = row.grade_4,
    sd.rec_bim_1 = row.rec_bim_1,
    sd.rec_bim_2 = row.rec_bim_2,
    sd.rec_sem_1 = row.rec_sem_1,
    sd.rec_sem_2 = row.rec_sem_2,
    sd.rec_sem_3 = row.rec_sem_3,
    sd.rec_sem_4 = row.rec_sem_4,
    sd.rec_final = row.rec_final,
    sd.final_mean = row.final_mean,
    sd.updated_at = row.updated_at
"""

# ============================================================
# NODE MERGE QUERIES – Facts
# ============================================================

MERGE_AVALIATION = """
UNWIND $rows AS row
MERGE (a:Avaliation {id: row.id})
SET a.situation = row.situation,
    a.updated_at = row.updated_at
"""

MERGE_CLASS = """
UNWIND $rows AS row
MERGE (cl:Class {id: row.id})
SET cl.scheduled_day = row.scheduled_day,
    cl.scheduled_class_days = row.scheduled_class_days,
    cl.scheduled_month = row.scheduled_month,
    cl.scheduled_lessons_per_day = row.scheduled_lessons_per_day,
    cl.scheduled_year = row.scheduled_year,
    cl.discipline_name = row.discipline_name,
    cl.updated_at = row.updated_at
"""

MERGE_STUDENT_CLASS = """
UNWIND $rows AS row
MERGE (sc:StudentClass {id: row.id})
SET sc.total_faults_per_day = row.total_faults_per_day,
    sc.total_faults_per_discipline = row.total_faults_per_discipline,
    sc.scheduled_student_class_days = row.scheduled_student_class_days,
    sc.updated_at = row.updated_at
"""

# ============================================================
# RELATIONSHIP QUERIES
# ============================================================

# F_ENROLLMENT: Student -[ENROLLED_IN]-> Classroom
LINK_ENROLLMENT = """
UNWIND $rows AS row
MATCH (s:Student {id: row.student_id})
MATCH (c:Classroom {id: row.classroom_id})
MERGE (s)-[r:ENROLLED_IN]->(c)
SET r.status = row.enrollment_status,
    r.updated_at = row.inserted_at
"""

# F_ENROLLMENT: Student -[ENROLLED_AT_SCHOOL]-> School
LINK_ENROLLMENT_SCHOOL = """
UNWIND $rows AS row
MATCH (s:Student {id: row.student_id})
MATCH (sc:School {id: row.school_id})
MERGE (s)-[r:ENROLLED_AT_SCHOOL]->(sc)
SET r.status = row.enrollment_status,
    r.updated_at = row.inserted_at
"""

# F_ENROLLMENT: links to Health via health_id
LINK_ENROLLMENT_HEALTH = """
UNWIND $rows AS row
MATCH (s:Student {id: row.student_id})
MATCH (h:Health {id: row.health_id})
MERGE (s)-[r:HAS_HEALTH]->(h)
SET r.updated_at = row.inserted_at
"""

# D_CLASSROOM -> D_SCHOOL (via HASH_ID split)
LINK_CLASS_SCHOOL = """
UNWIND $rows AS row
MATCH (c:Classroom {id: row.classroom_id})
MATCH (s:School {id: row.school_id})
MERGE (c)-[r:HELD_AT]->(s)
SET r.updated_at = row.inserted_at
"""

# D_SCHOOL -> D_SCHOOL_GEOGRAPH (F_HASH_ID -> HASH_ID)
LINK_SCHOOL_GEOGRAPH = """
UNWIND $rows AS row
MATCH (s:School {id: row.school_id})
MATCH (g:SchoolGeograph {id: row.geograph_id})
MERGE (s)-[r:HAS_GEOGRAPHY]->(g)
SET r.updated_at = row.inserted_at
"""

# D_STUDENT -> D_STUDENT_DISCIPLINE (F_HASH_ID -> student's F_HASH_ID)
LINK_STUDENT_DISCIPLINE = """
UNWIND $rows AS row
MATCH (s:Student {id: row.student_id})
MATCH (sd:StudentDiscipline {id: row.discipline_id})
MERGE (s)-[r:HAS_DISCIPLINE]->(sd)
SET r.updated_at = row.updated_at
"""

# F_AVALIATION: Student -[EVALUATED_IN]-> Avaliation
LINK_AVALIATION_STUDENT = """
UNWIND $rows AS row
MATCH (s:Student {id: row.student_id})
MATCH (a:Avaliation {id: row.avaliation_id})
MERGE (s)-[r:EVALUATED_IN]->(a)
SET r.updated_at = row.updated_at
"""

# F_AVALIATION: Avaliation -[AVALIATION_OF]-> StudentDiscipline
LINK_AVALIATION_DISCIPLINE = """
UNWIND $rows AS row
MATCH (a:Avaliation {id: row.avaliation_id})
MATCH (sd:StudentDiscipline {id: row.discipline_id})
MERGE (a)-[r:AVALIATION_OF]->(sd)
SET r.updated_at = row.updated_at
"""

# F_CLASS: Class -[TAUGHT_IN]-> Classroom
LINK_CLASS_CLASSROOM = """
UNWIND $rows AS row
MATCH (cl:Class {id: row.class_id})
MATCH (c:Classroom {id: row.classroom_id})
MERGE (cl)-[r:TAUGHT_IN]->(c)
SET r.updated_at = row.updated_at
"""

# F_CLASS: Class -[CLASS_AT_SCHOOL]-> School
LINK_CLASS_AT_SCHOOL = """
UNWIND $rows AS row
MATCH (cl:Class {id: row.class_id})
MATCH (s:School {id: row.school_id})
MERGE (cl)-[r:CLASS_AT_SCHOOL]->(s)
SET r.updated_at = row.updated_at
"""

# F_STUDENT_CLASS: StudentClass -[ATTENDED]-> Student
LINK_STUDENT_CLASS_STUDENT = """
UNWIND $rows AS row
MATCH (sc:StudentClass {id: row.student_class_id})
MATCH (s:Student {id: row.student_id})
MERGE (sc)-[r:ATTENDED]->(s)
SET r.updated_at = row.updated_at
"""

# F_STUDENT_CLASS: StudentClass -[ATTENDANCE_OF]-> Class
LINK_STUDENT_CLASS_CLASS = """
UNWIND $rows AS row
MATCH (sc:StudentClass {id: row.student_class_id})
MATCH (cl:Class {id: row.class_id})
MERGE (sc)-[r:ATTENDANCE_OF]->(cl)
SET r.updated_at = row.updated_at
"""

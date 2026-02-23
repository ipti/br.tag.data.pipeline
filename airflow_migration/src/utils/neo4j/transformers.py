"""
Transformer functions for Neo4j ingestion.
These functions help normalize and extract base IDs from composite SQL HASH_IDs 
so that Neo4j can form correct relationships between nodes.
"""

# --- NODE TRANSFORMERS ---
def transform_school_node(row):
    """School HASH_ID is 'inep-cep'. We just want 'inep' as the Neo4j ID."""
    return {
        **row,
        'id': str(row['id']).split('-')[0] if row.get('id') else None
    }

def transform_classroom_node(row):
    """Classroom HASH_ID is 'class-inep'. F_HASH_ID is 'class'. We want 'class' as Neo4j ID."""
    return {
        **row,
        'id': row.get('F_HASH_ID')
    }

# --- RELATIONSHIP TRANSFORMERS ---
def transform_enrollment_student(row):
    """Extract base student_id from composite HASH: 'si.id-school-classroom' -> si.id"""
    return {
        **row,
        'student_id': str(row['student_id']).split('-')[0] if row.get('student_id') else None,
        'classroom_id': str(row['classroom_id']).split('-')[0] if row.get('classroom_id') else None,
    }

def transform_classroom_school(row):
    """Extract school_id from d_classroom.HASH_ID: 'classroom_fk-school_inep' -> school_inep"""
    parts = str(row.get('HASH_ID', '')).split('-')
    return {
        'classroom_id': row.get('classroom_fk'),
        'school_id': parts[1] if len(parts) > 1 else None,
        'inserted_at': row.get('inserted_at'),
    }

def transform_school_geograph_rel(row):
    """SchoolGeograph.HASH_ID is identical to School.HASH_ID (inep-cep).
    Since School Neo4j ID is just 'inep', we extract it from geograph_id."""
    return {
        'geograph_id': row.get('geograph_id'),
        'school_id': str(row.get('geograph_id', '')).split('-')[0] if row.get('geograph_id') else None,
        'inserted_at': row.get('inserted_at'),
    }

def transform_enrollment_school(row):
    """Keep school_id and student_id for enrollment-school relationship."""
    return {
        'student_id': str(row['student_id']).split('-')[0] if row.get('student_id') else None,
        'school_id': str(row.get('school_id')).split('-')[0] if row.get('school_id') else None,
        'enrollment_status': row.get('enrollment_status'),
        'inserted_at': row.get('inserted_at'),
    }

def transform_enrollment_health(row):
    """Keep student_id and health_id for enrollment-health relationship."""
    return {
        'student_id': str(row['student_id']).split('-')[0] if row.get('student_id') else None,
        'health_id': str(row['health_id']).split('-')[0] if row.get('health_id') else None,
        'inserted_at': row.get('inserted_at'),
    }

def transform_avaliation_student(row):
    """Avaliation student_id is composite 'id-school-class'. We just need 'id'."""
    return {
        'avaliation_id': row.get('avaliation_id'),
        'student_id': str(row['student_id']).split('-')[0] if row.get('student_id') else None,
        'updated_at': row.get('updated_at')
    }

def transform_student_class_student(row):
    """StudentClass student_id is composite 'id-school-class'. We just need 'id'."""
    return {
        'student_class_id': row.get('student_class_id'),
        'student_id': str(row['student_id']).split('-')[0] if row.get('student_id') else None,
        'updated_at': row.get('updated_at')
    }

def transform_class_classroom(row):
    """F_Class classroom_id is composite or simple. Ensure we only get the classroom part."""
    return {
        'class_id': row.get('class_id'),
        'classroom_id': str(row['classroom_id']).split('-')[0] if row.get('classroom_id') else None,
        'updated_at': row.get('updated_at')
    }

def transform_class_school(row):
    """F_Class school_id is composite or simple. Ensure we only get the inep part."""
    return {
        'class_id': row.get('class_id'),
        'school_id': str(row['school_id']).split('-')[0] if row.get('school_id') else None,
        'updated_at': row.get('updated_at')
    }

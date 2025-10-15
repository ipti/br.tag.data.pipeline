{% macro table_columns(table_name) %}

{% set columns_dict = {
    'D_CLASSROOM': 'HASH_ID, F_HASH_ID, inserted_at, name, stage, status, serie, class_year, updated_at',
    'D_HEALTH': 'HASH_ID, inserted_at, F_HASH_ID, celiac_desase, diabetes_desease, iron_deficiency_anemia_desease, lactose_intolerance_desease, malnutrition_desease, hypertension_desease, obesity_desease, other_health_problems, updated_at, sickle_cell_anemia',
    'D_SCHOOL': 'HASH_ID, F_HASH_ID, inserted_at, latitude, longitude, name, address, number_address, address_complement, address_neighborhood, situation, exported_educacenso, join_at',
    'D_SCHOOL_GEOGRAPH': 'HASH_ID, cep, city, uf, F_HASH_ID, inserted_at',
    'D_STUDENT': 'HASH_ID, F_HASH_ID, inserted_at, name, street_addrees, bolsa_familia_participator, gender, ethnicity, birth_city, deficiency, birthday, neighborhood_address, cep, public_transport, city_address, mother_name, father_name, residence_zone, student_cpf, responsable_cpf, uf, mapped_city',
    'D_STUDENT_DISCIPLINE': 'HASH_ID, inserted_at, F_HASH_ID, discipline_name, grade_1, grade_2, grade_3, grade_4, rec_bim_1, rec_bim_2, rec_sem_1, rec_sem_2, rec_sem_3, rec_sem_4, rec_final, final_mean, updated_at',
    'F_CLASS': 'HASH_ID, inserted_at, teacher_id, classroom_id, scheduled_class_days, scheduled_month, scheduled_lessons_per_day, scheduled_year, school_id, discipline_id, updated_at, discipline_name, scheduled_day',
    'F_STUDENT_CLASS': 'HASH_ID, F_HASH_ID, student_id, discipline_id, total_faults_per_day, total_faults_per_discipline, inserted_at, updated_at, scheduled_student_class_days, class_id',
    'F_AVALIATION': 'HASH_ID, student_id, discipline_id, inserted_at, situation, updated_at',
    'F_ENROLLMENT': 'HASH_ID, school_id, classroom_id, student_id, db_name, data_origin, inserted_at, log_lineage, health_id, status, enrollment_status'
} %}

{{ return(columns_dict[table_name]) }}

{% endmacro %}

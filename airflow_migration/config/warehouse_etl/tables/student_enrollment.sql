SELECT
    itd.classroom_fk,
    itd.school_inep_id_fk,
    itd.enrollment_id,
    itd.edcenso_stage_vs_modality_fk,
    itd.student_fk,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.student_enrollment AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';

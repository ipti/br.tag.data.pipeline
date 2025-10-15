SELECT
    itd.id,
    itd.school_inep_id_fk,
    itd.created_at,
    itd.updated_at,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.student_identification AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';

SELECT
    itd.id,
    itd.school_inep_fk,
    itd.created_at,
    itd.updated_at,
    '{{ database_raw }}' AS database_name,
    itd.edcenso_stage_vs_modality_fk,
    itd.school_year,
    '{{ execution_timestamp }}' AS 'inserted_at'
FROM {{ database }}.classroom AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';

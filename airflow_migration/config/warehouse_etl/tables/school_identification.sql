SELECT
    itd.inep_id,
    itd.cep,
    itd.created_at,
    itd.updated_at,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.school_identification AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';

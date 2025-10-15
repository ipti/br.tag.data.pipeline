SELECT
    itd.id,
    itd.name,
    itd.edcenso_base_discipline_fk,
    itd.abbreviation,
    itd.created_at,
    itd.updated_at,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.edcenso_discipline AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';

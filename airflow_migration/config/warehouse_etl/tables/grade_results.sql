SELECT
    itd.*,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.grade_results AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';
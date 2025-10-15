SELECT DISTINCT
    c.id,
    c.school_inep_fk
FROM raw.classroom c
JOIN raw.schedule s
    ON s.classroom_fk = c.id
    AND s.database_name = c.database_name
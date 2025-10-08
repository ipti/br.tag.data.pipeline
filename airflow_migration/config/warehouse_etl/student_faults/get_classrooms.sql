SELECT 
    classroom_id as id,
    school_id as school_inep_fk
FROM (
    SELECT DISTINCT
        c.id AS classroom_id,
        c.school_inep_fk AS school_id,
        CASE WHEN cf.id IS NULL THEN 1 ELSE 0 END AS has_no_faults
    FROM raw.schedule s
    JOIN raw.classroom c
        ON c.id = s.classroom_fk
        AND c.database_name = s.database_name
    LEFT JOIN raw.class_faults cf
        ON cf.schedule_fk = s.id
        AND cf.database_name = s.database_name
) AS subquery
ORDER BY 
    has_no_faults,
    school_id,
    classroom_id;
WITH FaultSummary AS (
    SELECT
        cf.student_fk,
        s.classroom_fk,
        cf.database_name,
        MIN(s.id) AS schedule_id,
        COUNT(DISTINCT s.day) AS total_faults_per_day,
        MAX(cf.updated_at) AS last_fault_updated_at
    FROM raw.class_faults cf
    JOIN raw.schedule s
        ON cf.schedule_fk = s.id
        AND cf.database_name = s.database_name
    WHERE
        cf.updated_at > '{{ last_timestamp }}'
        AND s.unavailable = 0
        AND cf.database_name = '{{ database_raw }}'
    GROUP BY
        cf.student_fk,
        s.classroom_fk,
        cf.database_name
),
ScheduleSummary AS (
    SELECT
        classroom_fk,
        database_name,
        COUNT(DISTINCT day) AS scheduled_days
    FROM raw.schedule
    WHERE unavailable = 0
    GROUP BY classroom_fk, database_name
)
SELECT
    CONCAT(fs.schedule_id, '-', c.id, '-', c.school_inep_fk, '-', si.id) AS HASH_ID,
    fs.schedule_id AS F_HASH_ID,
    CONCAT(COALESCE(si.id, 'NO_ID'), '-', COALESCE(c.school_inep_fk, 'NO_SCHOOL'), '-', COALESCE(c.id, 'NO_CLASSROOM')) AS student_id,
    'elementary_school' AS discipline_id,
    fs.total_faults_per_day,
    NULL AS total_faults_per_discipline,
    fs.last_fault_updated_at AS updated_at,
    '{{ execution_timestamp }}' AS inserted_at,
    ss.scheduled_days AS scheduled_student_class_days,
    CONCAT(fs.schedule_id, '-', c.id, '-', c.school_inep_fk, '-', COALESCE((SELECT TOP 1 CAST(instructor_fk AS VARCHAR(50)) FROM raw.instructor_teaching_data WHERE classroom_id_fk = c.id AND database_name = c.database_name), 'NO_INSTRUCTOR')) AS class_id
FROM FaultSummary fs
JOIN raw.student_identification si
    ON fs.student_fk = si.id
    AND fs.database_name = si.database_name
JOIN raw.classroom c
    ON fs.classroom_fk = c.id
    AND fs.database_name = c.database_name
LEFT JOIN ScheduleSummary ss
    ON fs.classroom_fk = ss.classroom_fk
    AND fs.database_name = ss.database_name;
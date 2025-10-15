WITH FaultSummary AS (
    SELECT
        cf.student_fk,
        s.classroom_fk,
        s.discipline_fk,
        cf.database_name,
        MIN(s.id) as schedule_id,
        COUNT(DISTINCT s.day) AS total_faults_per_day,
        COUNT(cf.id) AS total_faults,
        MAX(cf.updated_at) AS last_fault_updated_at
    FROM raw.class_faults cf
    JOIN raw.schedule s
        ON cf.schedule_fk = s.id
        AND cf.database_name = s.database_name
    JOIN raw.classroom c
        ON s.classroom_fk = c.id
        AND s.database_name = c.database_name
    JOIN raw.edcenso_stage_vs_modality svm
        ON c.edcenso_stage_vs_modality_fk = svm.id
        AND c.database_name = svm.database_name
    WHERE
        cf.updated_at > '{{ last_timestamp }}'
        AND cf.database_name = '{{ database_raw }}'
        AND s.unavailable = 0
        AND NOT (
            svm.unified_frequency = 1
            OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        )
    GROUP BY
        cf.student_fk,
        s.classroom_fk,
        s.discipline_fk,
        cf.database_name
),
ScheduleSummary AS (
    SELECT
        classroom_fk,
        discipline_fk,
        database_name,
        COUNT(DISTINCT day) AS scheduled_days
    FROM raw.schedule
    WHERE unavailable = 0
    GROUP BY classroom_fk, discipline_fk, database_name
)
SELECT
    CONCAT(
        fs.schedule_id, '-', 
        c.id, '-', 
        c.school_inep_fk, '-', 
        COALESCE(fs.discipline_fk, 'NO_DISCIPLINE'), '-', 
        COALESCE(
            (SELECT TOP 1 CAST(instructor_fk AS VARCHAR(50)) 
             FROM raw.instructor_teaching_data 
             WHERE classroom_id_fk = c.id 
             AND database_name = c.database_name), 
            'NO_INSTRUCTOR'
        )
    ) AS class_id,
    CONCAT(
        fs.schedule_id, '-',
        c.id, '-',
        si.school_inep_id_fk, '-',
        si.id, '-',
        fs.discipline_fk, '-',
        c.school_year
    ) AS HASH_ID,
    fs.schedule_id AS F_HASH_ID,
    CONCAT(
        si.id, '-',
        si.school_inep_id_fk, '-',
        fs.discipline_fk, '-',
        fs.classroom_fk
    ) AS discipline_id,
    CONCAT(
        COALESCE(si.id, 'NO_ID'), '-',
        COALESCE(c.school_inep_fk, 'NO_SCHOOL'), '-',
        COALESCE(c.id, 'NO_CLASSROOM')
    ) AS student_id,
    fs.total_faults_per_day,
    fs.total_faults AS total_faults_per_discipline,
    COALESCE(ss.scheduled_days, 0) AS scheduled_student_class_days,
    fs.last_fault_updated_at AS updated_at,
    '{{ execution_timestamp }}' AS inserted_at
FROM FaultSummary fs
JOIN raw.student_identification si
    ON fs.student_fk = si.id
    AND fs.database_name = si.database_name
JOIN raw.classroom c
    ON fs.classroom_fk = c.id
    AND fs.database_name = c.database_name
LEFT JOIN ScheduleSummary ss
    ON fs.classroom_fk = ss.classroom_fk
    AND fs.discipline_fk = ss.discipline_fk
    AND fs.database_name = ss.database_name
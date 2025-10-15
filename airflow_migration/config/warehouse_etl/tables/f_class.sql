WITH ScheduleSummary AS (
    SELECT
        t.id AS schedule_id,
        t.classroom_fk,
        t.discipline_fk,
        t.database_name,
        t.day,
        t.month,
        MAX(t.updated_at) AS last_schedule_updated_at
    FROM raw.schedule t
    JOIN raw.classroom c 
        ON c.id = t.classroom_fk 
        AND c.database_name = t.database_name
    JOIN raw.edcenso_stage_vs_modality svm 
        ON svm.id = c.edcenso_stage_vs_modality_fk 
        AND svm.database_name = c.database_name
    WHERE 
        t.unavailable = 0
        AND t.updated_at > '{{ last_timestamp }}'
        AND t.database_name = '{{ database_raw }}'
    GROUP BY
        t.id,
        t.classroom_fk,
        t.discipline_fk,
        t.database_name,
        t.day,
        t.month
),
ScheduleAggregated AS (
    SELECT
        ss.classroom_fk,
        ss.discipline_fk,
        ss.database_name,
        ss.day,
        ss.month,
        MIN(ss.schedule_id) AS min_schedule_id,
        COUNT(DISTINCT ss.day) AS scheduled_class_days,
        COUNT(DISTINCT ss.schedule_id) AS scheduled_lessons_per_day,
        MAX(ss.last_schedule_updated_at) AS updated_at
    FROM ScheduleSummary ss
    GROUP BY
        ss.classroom_fk,
        ss.discipline_fk,
        ss.database_name,
        ss.day,
        ss.month
)
SELECT
    CASE
        WHEN svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        THEN CONCAT(sa.min_schedule_id, '-', c.id, '-', c.school_inep_fk, '-', COALESCE((SELECT TOP 1 CAST(instructor_fk AS VARCHAR(50)) FROM raw.instructor_teaching_data WHERE classroom_id_fk = c.id AND database_name = c.database_name), 'NO_INSTRUCTOR'))
        ELSE CONCAT(sa.min_schedule_id, '-', c.id, '-', c.school_inep_fk, '-', COALESCE(sa.discipline_fk, 'NO_DISCIPLINE'), '-', COALESCE((SELECT TOP 1 CAST(instructor_fk AS VARCHAR(50)) FROM raw.instructor_teaching_data WHERE classroom_id_fk = c.id AND database_name = c.database_name), 'NO_INSTRUCTOR'))
    END AS HASH_ID,
    sa.day AS scheduled_day,
    CONCAT(c.school_inep_fk, '-', COALESCE((SELECT TOP 1 CAST(instructor_fk AS VARCHAR(50)) FROM raw.instructor_teaching_data WHERE classroom_id_fk = c.id AND database_name = c.database_name), 'NO_INSTRUCTOR'), '-', c.id) AS teacher_id,
    CONCAT(c.id, '-', c.school_inep_fk) AS classroom_id,
    '{{ execution_timestamp }}' AS inserted_at,
    sa.scheduled_class_days,
    sa.month AS scheduled_month,
    sa.scheduled_lessons_per_day,
    c.school_year AS scheduled_year,
    CONCAT(c.school_inep_fk, '-', si.cep) AS school_id,
    CASE
        WHEN svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        THEN 'elementary_school'
        ELSE CONCAT(COALESCE(sa.discipline_fk, 'unified'), '-', c.school_inep_fk, '-', c.id)
    END AS discipline_id,
    sa.updated_at,
    CASE
        WHEN svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        THEN 'Ensino Fundamental'
        ELSE COALESCE(ed.name, 'Disciplina Não Identificada')
    END AS discipline_name
FROM ScheduleAggregated sa
JOIN raw.classroom c 
    ON sa.classroom_fk = c.id 
    AND sa.database_name = c.database_name
JOIN raw.edcenso_stage_vs_modality svm 
    ON svm.id = c.edcenso_stage_vs_modality_fk 
    AND svm.database_name = c.database_name
LEFT JOIN raw.edcenso_discipline ed 
    ON sa.discipline_fk = ed.id 
    AND ed.database_name = sa.database_name
JOIN raw.school_identification si 
    ON c.school_inep_fk = si.inep_id 
    AND c.database_name = si.database_name
ORDER BY sa.day, c.id, sa.month, discipline_id;
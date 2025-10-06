SELECT
    CONCAT(MIN(t.id), '-', c.id, '-', se.school_inep_id_fk, '-', si.id, '-', t.discipline_fk, '-', c.school_year) AS HASH_ID,
    MIN(t.id) AS F_HASH_ID,
    CONCAT(si.id, '-', si.school_inep_id_fk, '-', se.classroom_fk) AS student_id,
    concat (si.id, '-', si.school_inep_id_fk,'-' ,t.discipline_fk,'-',se.classroom_fk) as 'discipline_id',
    (
        SELECT COUNT(DISTINCT s_inner.day)
        FROM class_faults cf_inner
        JOIN schedule s_inner ON s_inner.id = cf_inner.schedule_fk
        WHERE cf_inner.student_fk = si.id
        AND s_inner.classroom_fk = c.id
        AND s_inner.discipline_fk = t.discipline_fk
        AND s_inner.month = t.month
        AND s_inner.unavailable = 0
    ) AS total_faults_per_day,
    (
        SELECT COUNT(cf_inner.id)
        FROM class_faults cf_inner
        JOIN schedule s_inner ON s_inner.id = cf_inner.schedule_fk
        WHERE cf_inner.student_fk = si.id
        AND s_inner.classroom_fk = c.id
        AND s_inner.discipline_fk = t.discipline_fk
        AND s_inner.month = t.month
        AND s_inner.unavailable = 0
    ) AS total_faults_per_discipline,
    '{{ execution_timestamp }}' AS inserted_at,
    MAX(t.updated_at) AS updated_at,
    COUNT(DISTINCT t.day) AS scheduled_student_class_days,
    CONCAT(MIN(t.id), '-', c.id, '-', si.school_inep_id_fk, '-', t.discipline_fk, '-', itd.instructor_fk) AS class_id
FROM `{{ database }}`.schedule t
JOIN `{{ database }}`.classroom c ON c.id = t.classroom_fk
JOIN `{{ database }}`.edcenso_stage_vs_modality svm ON svm.id = c.edcenso_stage_vs_modality_fk
JOIN `{{ database }}`.student_enrollment se ON se.classroom_fk = t.classroom_fk
JOIN `{{ database }}`.student_identification si ON se.student_fk = si.id
JOIN `{{ database }}`.edcenso_discipline ed ON t.discipline_fk = ed.id
left join `{{ database }}`.instructor_teaching_data itd on c.id = itd.classroom_id_fk
WHERE t.unavailable = 0
AND t.month IN {{ months }}
and c.id = {{ classroom_id }}
AND si.school_inep_id_fk = {{ school_inep_fk }}
AND (svm.unified_frequency = 0 OR svm.id NOT IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84))
-- AND (
--    SELECT MAX(cf.updated_at)
--    FROM`{{ database }}`.class_faults cf
--    JOIN`{{ database }}`.schedule s_cf ON s_cf.id = cf.schedule_fk
--    WHERE cf.student_fk = si.id
--    AND s_cf.classroom_fk = c.id
--    AND s_cf.discipline_fk = t.discipline_fk  -- Específico por disciplina
--    AND s_cf.month = t.month
-- ) > '2024-07-01 00:00:00'
GROUP BY c.id, si.id, t.discipline_fk, t.month, se.school_inep_id_fk, se.classroom_fk, c.school_year;
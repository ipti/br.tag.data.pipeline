SELECT
    CONCAT(MIN(t.id), '-', c.id, '-', si.school_inep_id_fk, '-', si.id) AS HASH_ID,
    MIN(t.id) AS F_HASH_ID,
    CONCAT(si.id, '-', si.school_inep_id_fk, '-', se.classroom_fk) AS student_id,
    'elementary school' AS discipline_id,
    (
        SELECT COUNT(DISTINCT s_inner.day)
        FROM class_faults cf_inner
        JOIN schedule s_inner ON s_inner.id = cf_inner.schedule_fk
        WHERE cf_inner.student_fk = si.id
        AND s_inner.classroom_fk = c.id
        AND s_inner.month = t.month
        AND s_inner.unavailable = 0
    ) AS total_faults_per_day,
    NULL AS total_faults_per_discipline,
    '{{ execution_timestamp }}' AS inserted_at,
    MAX(t.updated_at) AS updated_at,
    COUNT(DISTINCT t.day) AS scheduled_student_class_days,
    CONCAT(MIN(t.id), '-', c.id, '-', si.school_inep_id_fk,'-' ,itd.instructor_fk) AS class_id
FROM `{{ database }}`.schedule t
JOIN `{{ database }}`.classroom c ON c.id = t.classroom_fk
JOIN `{{ database }}`.edcenso_stage_vs_modality svm ON svm.id = c.edcenso_stage_vs_modality_fk
JOIN `{{ database }}`.student_enrollment se ON se.classroom_fk = t.classroom_fk
JOIN `{{ database }}`.student_identification si ON se.student_fk = si.id
left join `{{ database }}`.instructor_teaching_data itd on c.id = itd.classroom_id_fk
WHERE t.unavailable = 0 
and c.id = {{ classroom_id }}
and t.month IN {{ months }}
and si.school_inep_id_fk = {{ school_inep_fk }}
-- AND (
--    SELECT MAX(cf.updated_at)
--    FROM`{{ database }}`.class_faults cf
--    JOIN`{{ database }}`.schedule s_cf ON s_cf.id = cf.schedule_fk
--    WHERE cf.student_fk = si.id
--    AND s_cf.classroom_fk = c.id
--    AND s_cf.month = t.month
-- ) > '2024-07-06 00:00:00'
GROUP BY c.id, si.id, t.month, se.school_inep_id_fk, se.classroom_fk;
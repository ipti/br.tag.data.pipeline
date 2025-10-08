SELECT
    CONCAT(MIN(t.id), '-', c.id, '-', c.school_inep_fk, '-', si.id) AS 'HASH_ID',
    MIN(t.id) AS 'F_HASH_ID',
      CONCAT(
        COALESCE(si.id, 'NO_ID'), '-', 
        COALESCE(c.school_inep_fk, 'NO_SCHOOL'), '-', 
        COALESCE(c.id, 'NO_CLASSROOM')
    ) AS 'student_id',
    'elementary_school' AS 'discipline_id',
    (
        SELECT COUNT(DISTINCT s_inner.day)
        FROM raw.class_faults cf_inner
        JOIN raw.schedule s_inner ON s_inner.id = cf_inner.schedule_fk AND s_inner.database_name = cf_inner.database_name
        WHERE cf_inner.student_fk = si.id
        AND s_inner.classroom_fk = c.id
        AND s_inner.month IN {{ months }}
        AND s_inner.unavailable = 0
    ) AS 'total_faults_per_day',
    NULL AS 'total_faults_per_discipline',
    MAX(t.updated_at) AS 'updated_at',
    GETUTCDATE() AS 'inserted_at',
    COUNT(DISTINCT t.day) AS 'scheduled_student_class_days',
    CONCAT(MIN(t.id), '-', c.id, '-', c.school_inep_fk, '-',COALESCE(MIN(CAST(itd.instructor_fk AS VARCHAR(50))), 'NO_INSTRUCTOR')) AS 'class_id'
FROM raw.schedule t
JOIN raw.classroom c ON c.id = t.classroom_fk AND c.database_name = t.database_name
JOIN raw.edcenso_stage_vs_modality svm ON svm.id = c.edcenso_stage_vs_modality_fk AND svm.database_name = c.database_name
JOIN raw.student_enrollment se ON se.classroom_fk = t.classroom_fk AND se.database_name = t.database_name
JOIN raw.student_identification si ON se.student_fk = si.id AND si.database_name = se.database_name
LEFT JOIN raw.instructor_teaching_data itd ON c.id = itd.classroom_id_fk AND itd.database_name = c.database_name
WHERE t.unavailable = 0
  AND t.month IN {{ months }}
  AND c.school_inep_fk = {{ school_inep_fk }}
  AND c.id = {{ id }}
GROUP BY
    c.id, 
    c.school_inep_fk,
    si.id,
    si.school_inep_id_fk,
    se.classroom_fk;
SELECT
CONCAT(MIN(t.id), '-', c.id, '-', se.school_inep_id_fk, '-', t.discipline_fk) AS 'class_id',
CONCAT(MIN(t.id), '-', c.id, '-', se.school_inep_id_fk, '-', si.id, '-', t.discipline_fk, '-', c.school_year) AS 'HASH_ID',
MIN(t.id) as 'F_HASH_ID',
t.discipline_fk as discipline_id,
ed.name,
CONCAT(
        COALESCE(si.id, 'NO_ID'), '-', 
        COALESCE(c.school_inep_fk, 'NO_SCHOOL'), '-', 
        COALESCE(c.id, 'NO_CLASSROOM')
    ) AS 'student_id',
MAX(t.updated_at) as updated_at,
COUNT(DISTINCT t.day) AS scheduled_student_class_days,
COUNT(t.id) AS total_scheduled_classes,
(SELECT COUNT(cf_inner.id)
FROM raw.class_faults cf_inner
JOIN raw.schedule s_inner ON s_inner.id = cf_inner.schedule_fk AND s_inner.database_name = cf_inner.database_name
WHERE cf_inner.student_fk = si.id
AND s_inner.classroom_fk = c.id
AND s_inner.discipline_fk = t.discipline_fk
AND s_inner.month = t.month
AND s_inner.unavailable = 0
) AS total_faults,
(SELECT COUNT(DISTINCT s_inner.day)
FROM raw.class_faults cf_inner
JOIN raw.schedule s_inner ON s_inner.id = cf_inner.schedule_fk AND s_inner.database_name = cf_inner.database_name
WHERE cf_inner.student_fk = si.id
AND s_inner.classroom_fk = c.id
AND s_inner.discipline_fk = t.discipline_fk
AND s_inner.month = t.month
AND s_inner.unavailable = 0
) AS total_faults_per_day,
c.school_year
FROM raw.schedule t
JOIN raw.classroom c ON c.id = t.classroom_fk AND c.database_name = t.database_name
JOIN raw.edcenso_stage_vs_modality svm ON svm.id = c.edcenso_stage_vs_modality_fk AND svm.database_name = c.database_name
JOIN raw.student_enrollment se ON se.classroom_fk = t.classroom_fk AND se.database_name = t.database_name
JOIN raw.student_identification si ON se.student_fk = si.id AND si.database_name = se.database_name
JOIN raw.edcenso_discipline ed ON t.discipline_fk = ed.id AND ed.database_name = t.database_name
WHERE t.unavailable = 0
AND t.month IN {{ months }}
AND c.school_inep_fk = {{ school_inep_fk }}
AND c.id = {{ id }}
GROUP BY
    c.id,
    c.school_year,
    si.id,
    se.school_inep_id_fk,
    se.classroom_fk,
    t.discipline_fk,
    t.month,
    c.school_inep_fk,
    ed.name
ORDER BY si.id, t.discipline_fk, c.school_year;
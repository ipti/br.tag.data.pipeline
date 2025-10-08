SELECT
    CASE
        WHEN svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        THEN CONCAT(MIN(t.id), '-', c.id, '-', c.school_inep_fk, '-', COALESCE(min(itd.instructor_fk), 'NO_INSTRUCTOR'))
        ELSE CONCAT(MIN(t.id), '-', c.id, '-', c.school_inep_fk, '-', COALESCE(t.discipline_fk, 'NO_DISCIPLINE'), '-', COALESCE(min(itd.instructor_fk), 'NO_INSTRUCTOR'))
    END AS HASH_ID,
    t.day AS scheduled_day,
    CONCAT(c.school_inep_fk, '-', COALESCE(min(itd.instructor_fk), 'NO_INSTRUCTOR'), '-', c.id) AS teacher_id,
    concat (c.id, '-', c.school_inep_fk ) as classroom_id,
    GETUTCDATE() AS inserted_at,
    COUNT(DISTINCT(t.[day] )) AS scheduled_class_days,
    t.month as scheduled_month,
    COUNT(distinct (t.id)) AS  scheduled_lessons_per_day,
    c.school_year AS scheduled_year,
     concat(c.school_inep_fk,'-',si.cep) AS school_id,
    CASE
        WHEN svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        THEN 'elementary_school'
        ELSE CONCAT(COALESCE(t.discipline_fk, 'unified'), '-', c.school_inep_fk, '-', c.id)
    END AS discipline_id,
    MAX(t.updated_at) AS updated_at,
    CASE
        WHEN svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
        THEN 'Ensino Fundamental'
        ELSE COALESCE(ed.name, 'Disciplina Não Identificada')
    END AS discipline_name
FROM raw.schedule t
JOIN raw.classroom c ON c.id = t.classroom_fk and c.database_name = t.database_name
JOIN raw.edcenso_stage_vs_modality svm ON svm.id = c.edcenso_stage_vs_modality_fk and svm.database_name = c.database_name
LEFT JOIN raw.edcenso_discipline ed ON t.discipline_fk = ed.id and ed.database_name = t.database_name
left join raw.instructor_teaching_data itd on c.id = itd.classroom_id_fk and itd.database_name = c.database_name
join raw.school_identification si on c.school_inep_fk = si.inep_id and c.database_name = si.database_name
WHERE t.unavailable = 0
AND t.month IN {{ months }}
AND c.school_inep_fk = {{ school_inep_fk }}
AND c.id = {{ id }}
GROUP BY
    c.id,
    c.school_inep_fk,
    c.school_year,
    t.[day],
    t.month,
    t.discipline_fk,
    svm.unified_frequency,
    svm.id,
    si.cep,
    ed.name
ORDER BY t.[day]  ,c.id, t.month, discipline_id;
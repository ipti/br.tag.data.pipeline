SELECT 
    CONCAT(si.id, '-', si.school_inep_id_fk, '-', gr.discipline_fk, '-', se.classroom_fk) AS 'HASH_ID',
    ed.name,
    gr.updated_at,
    gr.situation,
    gr.grade_1,
    gr.grade_2, 
    gr.grade_3,
    gr.grade_4,
    gr.sem_rec_partial_1,
    gr.sem_rec_partial_2,
    gr.rec_partial_1,
    gr.rec_partial_2,
    gr.rec_partial_3,
    gr.rec_partial_4,
    '{execution_timestamp}' AS inserted_at,
    gr.id AS "F_HASH_ID"
FROM {database_name}.student_identification si
LEFT JOIN {database_name}.student_enrollment se ON si.id = se.student_fk
LEFT JOIN {database_name}.grade_results gr ON se.student_fk = gr.enrollment_fk
LEFT JOIN {database_name}.edcenso_discipline ed ON gr.discipline_fk = ed.id
WHERE si.id IS NOT NULL
    AND se.school_inep_id_fk IS NOT NULL
    AND gr.discipline_fk IS NOT NULL
    AND se.classroom_fk IS NOT NULL
    AND (
        gr.grade_1 IS NOT NULL OR
        gr.grade_2 IS NOT NULL OR
        gr.grade_3 IS NOT NULL OR
        gr.grade_4 IS NOT NULL
    )
    AND (
        gr.updated_at >= '{safe_timestamp}' OR
        se.updated_at >= '{safe_timestamp}' OR
        si.updated_at >= '{safe_timestamp}'
    )
GROUP BY si.id, gr.discipline_fk, se.classroom_fk
ORDER BY si.id, gr.discipline_fk;

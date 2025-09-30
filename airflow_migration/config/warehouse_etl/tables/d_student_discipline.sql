SELECT 
    CONCAT(si.id, '-', si.school_inep_id_fk, '-', gr.discipline_fk, '-', se.classroom_fk) AS `HASH_ID`,
    '{{ execution_timestamp }}' AS `inserted_at`,
    gr.id AS `F_HASH_ID`,
    ed.name AS `discipline_name`,
    gr.grade_1,
    gr.grade_2,
    gr.grade_3,
    gr.grade_4,
    gr.sem_rec_partial_1 AS `rec_bim_1`,
    gr.sem_rec_partial_2 AS `rec_bim_2`,
    gr.rec_partial_1 AS `rec_sem_1`,
    gr.rec_partial_2 AS `rec_sem_2`,
    gr.rec_partial_3 AS `rec_sem_3`,
    gr.rec_partial_4 AS `rec_sem_4`,
    gr.rec_final,
    gr.final_media AS `final_mean`,
    gr.updated_at
FROM {{ database }}.student_identification si
LEFT JOIN {{ database }}.student_enrollment se ON si.id = se.student_fk
LEFT JOIN {{ database }}.grade_results gr ON se.student_fk = gr.enrollment_fk
LEFT JOIN {{ database }}.edcenso_discipline ed ON gr.discipline_fk = ed.id
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
        gr.updated_at >= '{{ safe_timestamp }}' OR
        se.updated_at >= '{{ safe_timestamp }}' OR
        si.updated_at >= '{{ safe_timestamp }}'
    )
group by si.id, gr.discipline_fk , se.classroom_fk 
ORDER BY si.id, gr.discipline_fk;

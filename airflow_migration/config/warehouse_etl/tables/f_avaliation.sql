SELECT 
    CONCAT(si.id, '-', si.school_inep_id_fk, '-', gr.discipline_fk, '-', se.classroom_fk) AS 'discipline_id',
    CONCAT(
        COALESCE(si.id, 'NO_ID'), '-', 
        COALESCE(si.school_inep_id_fk, 'NO_SCHOOL'), '-', 
        COALESCE(se.classroom_fk, 'NO_CLASSROOM')
    ) AS student_id,
    CONCAT(si.id, '-', se.school_inep_id_fk, '-', se.classroom_fk, '-', gr.id) AS 'HASH_ID',
    gr.situation,
    '{{execution_timestamp}}' AS 'inserted_at',
    gr.updated_at
FROM {{ database }}.student_identification si
LEFT JOIN {{ database }}.student_enrollment se ON si.id = se.student_fk
LEFT JOIN {{ database }}.grade_results gr ON se.student_fk = gr.enrollment_fk
LEFT JOIN {{ database }}.edcenso_discipline ed ON gr.discipline_fk = ed.id
WHERE si.id IS NOT NULL
    AND si.school_inep_id_fk IS NOT NULL
    AND gr.discipline_fk IS NOT NULL
    AND se.classroom_fk IS NOT NULL
    AND (
        gr.grade_1 IS NOT NULL OR
        gr.grade_2 IS NOT NULL OR
        gr.grade_3 IS NOT NULL OR
        gr.grade_4 IS NOT NULL
    )
    AND (
        si.updated_at >= '{{ safe_timestamp }}' OR
        se.updated_at >= '{{ safe_timestamp }}' OR
        gr.updated_at >= '{{ safe_timestamp }}'
    )
ORDER BY si.id, gr.id;
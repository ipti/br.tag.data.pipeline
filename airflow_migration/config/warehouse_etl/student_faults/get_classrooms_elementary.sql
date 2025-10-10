SELECT DISTINCT
    c.id,
    c.school_inep_fk
FROM raw.classroom c
JOIN raw.edcenso_stage_vs_modality svm 
    ON svm.id = c.edcenso_stage_vs_modality_fk 
    AND svm.database_name = c.database_name
JOIN raw.schedule s
    ON s.classroom_fk = c.id
    AND s.database_name = c.database_name
WHERE 
    s.unavailable = 0
    AND (
        svm.unified_frequency = 1 OR svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 12, 13, 22, 23, 24, 41, 56, 83, 84)
    );
select concat (se.classroom_fk, '-', se.school_inep_id_fk) as 'HASH_ID',
c.id as "F_HASH_ID",
c.name,
(CASE
        WHEN svm.stage = '1' THEN 'EDUCAÇÃO INFANTIL'
        WHEN svm.stage = '2' THEN 'ENSINO FUNDAMENTAL'
        WHEN svm.stage = '3' THEN 'ENSINO FUNDAMENTAL'
        WHEN svm.stage = '4' THEN 'ENSINO MÉDIO'
        WHEN svm.stage = '5' THEN 'EDUCAÇÃO PROFISSIONAL'
        WHEN svm.stage = '6' THEN 'EDUCAÇÃO DE JOVENS E ADULTOS'
        WHEN svm.stage = '7' THEN
            (CASE
                WHEN svm.id = '56' THEN 'MULTIETAPA'
                ELSE 'ENSINO FUNDAMENTAL'
            END)
    END) AS `stage`,
    CONCAT(
        (CASE
            WHEN svm.id IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38) THEN 'NA '
            WHEN svm.id IN (14, 15, 16, 17, 18, 19, 20, 21, 41) THEN 'NO '
            ELSE ''
        END),
        (CASE
            WHEN svm.id = 1 THEN 'CRECHE'
            WHEN svm.id = 2 THEN 'PRÉ-ESCOLA'
            WHEN svm.id = 3 THEN 'EDUCAÇÃO INFANTIL'
            WHEN svm.id IN (4, 14, 25, 30, 35) THEN '1'
            WHEN svm.id IN (5, 15, 26, 31, 36) THEN '2'
            WHEN svm.id IN (6, 16, 27, 32, 37) THEN '3'
            WHEN svm.id IN (7, 17, 28, 33, 38) THEN '4'
            WHEN svm.id IN (8, 18) THEN '5'
            WHEN svm.id IN (9, 19) THEN '6'
            WHEN svm.id IN (10, 20) THEN '7'
            WHEN svm.id IN (11, 21) THEN '8'
            WHEN svm.id = 41 THEN '9'
            ELSE ''
        END),
        (CASE
            WHEN svm.id IN (1, 2, 3) THEN ''
            WHEN svm.id IN (4, 5, 6, 7, 8, 9, 10, 11, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38) THEN '* SÉRIE'
            WHEN svm.id IN (14, 15, 16, 17, 18, 19, 20, 21, 41) THEN '* ANO'
            ELSE 'NA ____________________'
        END)
    ) AS `serie`,
    c.school_year as 'class_year',
    c.updated_at,
'{{ execution_timestamp }}' AS `inserted_at`
from {{ database }}.classroom c
LEFT JOIN {{ database }}.edcenso_stage_vs_modality svm ON c.edcenso_stage_vs_modality_fk = svm.id
inner join {{ database }}.student_enrollment se on se.classroom_fk = c.id
where c.id is not null 
and se.school_inep_id_fk is not null
-- AND (
--    c.updated_at >= '@{variables('LastInsertGloria')}'
-- OR se.updated_at >= '@{variables('LastInsertGloria')}'
--  OR svm.updated_at >= '@{variables('LastInsertGloria')}'  
-- )
group by 
    concat (se.classroom_fk, '-', se.school_inep_id_fk),
    c.id,
    c.name,
    svm.stage,
    c.school_year,
    c.updated_at
order by c.school_year, c.id;
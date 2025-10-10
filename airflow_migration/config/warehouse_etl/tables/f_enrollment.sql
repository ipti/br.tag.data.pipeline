select CONCAT(
  COALESCE(si.id, 'NO_ID'), '-', 
  COALESCE(si.school_inep_id_fk, 'NO_SCHOOL'), '-', 
  COALESCE(se.classroom_fk, 'NO_CLASSROOM'), '-', 
  COALESCE(si2.cep, 'NO_CEP')
) AS HASH_ID,
CONCAT(
  COALESCE(si.id, 'NO_ID'), '-', 
  COALESCE(si.school_inep_id_fk, 'NO_SCHOOL'), '-', 
  COALESCE(se.classroom_fk, 'NO_CLASSROOM')
) AS student_id, 
concat (se.classroom_fk, '-', se.school_inep_id_fk) as classroom_id,
concat(si2.inep_id, '-', si2.cep) as school_id,
CONCAT(
    COALESCE(sr.id, 'NO_RESTRICTION'), '-', 
    si.school_inep_id_fk, '-',  
    si.id, '-', 
    COALESCE(se.classroom_fk, 'NO_CLASSROOM') 
) as health_id,
si.updated_at,
'{{ execution_timestamp }}' AS `inserted_at`,
'{{ database_raw }}' AS `db_name`, 
'tagDatabase' as data_origin,
   (CASE
        WHEN se.status = '1' THEN 'ATIVO'
        WHEN se.status = '2' THEN 'TRANSFERIDO'
        WHEN se.status = '3' THEN 'CANCELADO'
        WHEN se.status = '4' THEN 'ABANDONADO'
        WHEN se.status = '5' THEN 'RESTAURADO'
        WHEN se.status = '6' THEN 'APROVADO'
        WHEN se.status = '7' THEN 'APROVADO_PELO_CONSELHO'
        WHEN se.status = '8' THEN 'REPROVADO'
        WHEN se.status = '9' THEN 'CONCLUÍDO'
        WHEN se.status = '10' THEN 'INDETERMINADO'
        WHEN se.status = '11' THEN 'FALECIMENTO'
        ELSE NULL
    END) AS `enrollment_status`
from {{ database }}.student_identification si
left join {{ database }}.student_enrollment se on si.id = se.student_fk
left join {{ database }}.student_restrictions sr on si.id = sr.student_fk
left join {{ database }}.school_identification si2 on si.school_inep_id_fk = si2.inep_id
WHERE si.id IS NOT NULL
AND si.school_inep_id_fk IS NOT NULL
AND si2.cep IS NOT NULL
AND (
  si.updated_at > '{{ safe_timestamp }}'
  OR se.updated_at > '{{ safe_timestamp }}'
  OR sr.updated_at > '{{ safe_timestamp }}'
)
group by si.id, se.classroom_fk, si.school_inep_id_fk
order by si.id;
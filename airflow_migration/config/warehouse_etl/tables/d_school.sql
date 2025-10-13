select 
concat(si.inep_id , '-', si.cep) as 'HASH_ID',
concat(si.inep_id , '-', si.cep, '-', si.initial_date) as 'F_HASH_ID',
 '{{ execution_timestamp }}' AS `inserted_at`,
si.latitude ,
si.longitude ,
si.name,
si.address ,
si.address_number as 'number_address',
si.address_complement ,
si.address_neighborhood ,
si.situation,
si.initial_date as 'join_at',
0 + MAX(CASE WHEN l.crud = 'E' THEN 1 ELSE 0 END) AS exported_educacenso
FROM
{{ database }}.school_identification si
LEFT JOIN {{ database }}.log l ON si.inep_id = l.school_fk 
WHERE 
  si.updated_at >= '{{ safe_timestamp }}'
  OR l.updated_at >= '{{ safe_timestamp }}'
group by si.inep_id 

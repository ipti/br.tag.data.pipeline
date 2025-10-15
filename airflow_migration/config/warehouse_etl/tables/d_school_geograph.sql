select 
concat(si.inep_id , '-', si.cep) as 'HASH_ID',
concat(si.inep_id , '-', si.cep, '-', ec.id, '-', eu.id) as 'F_HASH_ID',
si.cep,
ec.name as 'city' ,
eu.acronym as 'uf',
'{{ execution_timestamp }}' AS `inserted_at`
FROM
   {{ database }}.school_identification si
left join {{ database }}.edcenso_city ec on si.edcenso_city_fk = ec.id 
left join {{ database }}.edcenso_uf eu on si.edcenso_uf_fk = eu.id 
where si.updated_at > '{{ safe_timestamp }}'

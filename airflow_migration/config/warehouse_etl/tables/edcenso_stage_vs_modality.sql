select 
    '{{ database_raw }}' AS database_name,
    itd.* from {{ database }}.edcenso_stage_vs_modality itd 
where itd.updated_at > '{{ safe_timestamp }}'
{% if database == 'altodorodrigues.tag.ong.br' %}
AND 1 = 0
{% endif %}
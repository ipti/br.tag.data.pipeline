SELECT
    itd.id,
    itd.name,
    itd.alias,
    itd.stage,
    itd.edcenso_associated_stage_id,
    itd.is_edcenso_stage,
    itd.created_at,
    itd.updated_at,
    itd.unified_frequency,
    itd.aggregated_stage,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.edcenso_stage_vs_modality AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}'
{% if database == 'altodorodrigues.tag.ong.br' %}
  AND 1 = 0
{% endif %}

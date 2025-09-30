SELECT 
    CONCAT(
        COALESCE(si.id, 'NO_ID'), '-', 
        COALESCE(si.school_inep_id_fk, 'NO_SCHOOL'), '-', 
        COALESCE(se.classroom_fk, 'NO_CLASSROOM')
    ) AS 'HASH_ID',
    SUBSTRING('{{ database }}', 1, LOCATE('.', '{{ database }}') - 1) AS mapped_city,    
    si.id AS 'F_HASH_ID',
    '{{ execution_timestamp }}' AS 'inserted_at',
    si.name,
    sd.neighborhood AS `neighborhood_address`,
    si.bf_participator AS 'bolsa_familia_participator',
    sd.address AS `street_addrees`,
    IF(si.sex = 1, 'Masculino', 'Feminino') AS `gender`,
    (CASE 
        WHEN si.color_race = '1' THEN 'Branca'
        WHEN si.color_race = '2' THEN 'Preta'
        WHEN si.color_race = '3' THEN 'Parda'
        WHEN si.color_race = '4' THEN 'Amarela'
        WHEN si.color_race = '5' THEN 'Indígena'
        ELSE 'Não Declarada'
    END) AS `ethnicity`,
    (CASE 
        WHEN si.deficiency = 0 THEN 'Não'
        ELSE CONCAT_WS(': ',
            'Possui',
            CONCAT_WS(', ',
                (CASE WHEN si.deficiency_type_blindness = 1 THEN 'Cegueira' END),
                (CASE WHEN si.deficiency_type_low_vision = 1 THEN 'Baixa visão' END),
                (CASE WHEN si.deficiency_type_deafness = 1 THEN 'Surdez' END),
                (CASE WHEN si.deficiency_type_disability_hearing = 1 THEN 'Deficiência Auditiva' END),
                (CASE WHEN si.deficiency_type_deafblindness = 1 THEN 'Surdocegueira' END),
                (CASE WHEN si.deficiency_type_phisical_disability = 1 THEN 'Deficiência Física' END),
                (CASE WHEN si.deficiency_type_intelectual_disability = 1 THEN 'Deficiência Intelectual' END),
                (CASE WHEN si.deficiency_type_multiple_disabilities = 1 THEN 'Deficiência Múltipla' END),
                (CASE WHEN si.deficiency_type_autism = 1 THEN 'Autismo Infantil' END),
                (CASE WHEN si.deficiency_type_aspenger_syndrome = 1 THEN 'Síndrome de Asperger' END),
                (CASE WHEN si.deficiency_type_rett_syndrome = 1 THEN 'Síndrome de Rett' END),
                (CASE WHEN si.deficiency_type_childhood_disintegrative_disorder = 1 THEN 'Transtorno Desintegrativo da Infância' END),
                (CASE WHEN si.deficiency_type_gifted = 1 THEN 'Altas habilidades / Superdotação' END)
            )
        )
    END) AS `deficiency`,
    ec.name AS `birth_city`,
    si.birthday,
    eu.acronym AS 'uf',
    sd.cep,
    (CASE 
        WHEN se.vehicle_type_bus = 0 THEN 'Não'
        WHEN se.vehicle_type_bus = 1 THEN 'Sim'
    END) AS `public_transport`,
    si.filiation_1 AS `mother_name`,
    si.filiation_2 AS `father_name`,
    (CASE 
        WHEN sd.residence_zone = '1' THEN 'Urbano'
        WHEN sd.residence_zone = '2' THEN 'Rural'
    END) AS `residence_zone`,
    si.responsable_cpf AS 'responsable_cpf',
    sd.cpf AS 'student_cpf'
FROM {{ database }}.student_identification si
LEFT JOIN {{ database }}.student_enrollment se ON si.id = se.student_fk
LEFT JOIN {{ database }}.student_documents_and_address sd ON si.id = sd.id
LEFT JOIN {{ database }}.school_identification si2 ON si.school_inep_id_fk = si2.inep_id
LEFT JOIN {{ database }}.edcenso_city ec ON si.edcenso_city_fk = ec.id
LEFT JOIN {{ database }}.edcenso_uf eu ON si.edcenso_uf_fk = eu.id
WHERE si.id IS NOT NULL
    AND si.school_inep_id_fk IS NOT NULL
    AND (
        si.updated_at >= '{{ safe_timestamp }}' OR
        se.updated_at >= '{{ safe_timestamp }}' OR
        sd.updated_at >= '{{ safe_timestamp }}'

        {# Lógica para a primeira execução: busca registros com data nula #}
        {% if last_timestamp is none %}
        OR si.updated_at IS NULL
        OR se.updated_at IS NULL
        OR sd.updated_at IS NULL
        {% endif %}
    ); 
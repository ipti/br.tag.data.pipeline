SELECT
    CONCAT(s.id, '-', sci.inep_id) AS 'Special-id',
    se.updated_at AS max_date,
    SUBSTRING('{{ database_raw }}', 1, LOCATE('.', '{{ database_raw }}') - 1) AS `city_name`,
    '{{ database_raw }}' AS `db_name`,
    c.name AS `Turmas`,
    s.id AS `id`,
    s.name AS `name`,
    sci.name AS `school name`,
    '{{ execution_timestamp }}' as DataLineageIngestion
    sd.neighborhood AS `Bairro`,
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
    END) AS `status`,
    sd.address AS `Rua`,
    IF(s.bf_participator = 1, 'Sim', 'Não') AS `Bolsa_familia_char`,
    s.bf_participator AS `Bolsa_Familia`,
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
    ) AS `class`,
    IF(s.sex = 1, 'Masculino', 'Feminino') AS `gender`,
    (CASE
        WHEN s.color_race = '1' THEN 'Branca'
        WHEN s.color_race = '2' THEN 'Preta'
        WHEN s.color_race = '3' THEN 'Parda'
        WHEN s.color_race = '4' THEN 'Amarela'
        WHEN s.color_race = '5' THEN 'Indígena'
        ELSE 'Não Declarada'
    END) AS `color`,
    (CASE
        WHEN s.deficiency = 0 THEN 'Não'
        ELSE CONCAT_WS(': ',
            'Possui',
            CONCAT_WS(', ',
                (CASE WHEN s.deficiency_type_blindness = 1 THEN 'Cegueira' END),
                (CASE WHEN s.deficiency_type_low_vision = 1 THEN 'Baixa visão' END),
                (CASE WHEN s.deficiency_type_deafness = 1 THEN 'Surdez' END),
                (CASE WHEN s.deficiency_type_disability_hearing = 1 THEN 'Deficiência Auditiva' END),
                (CASE WHEN s.deficiency_type_deafblindness = 1 THEN 'Surdocegueira' END),
                (CASE WHEN s.deficiency_type_phisical_disability = 1 THEN 'Deficiência Física' END),
                (CASE WHEN s.deficiency_type_intelectual_disability = 1 THEN 'Deficiência Intelectual' END),
                (CASE WHEN s.deficiency_type_multiple_disabilities = 1 THEN 'Deficiência Múltipla' END),
                (CASE WHEN s.deficiency_type_autism = 1 THEN 'Autismo Infantil' END),
                (CASE WHEN s.deficiency_type_aspenger_syndrome = 1 THEN 'Síndrome de Asperger' END),
                (CASE WHEN s.deficiency_type_rett_syndrome = 1 THEN 'Síndrome de Rett' END),
                (CASE WHEN s.deficiency_type_childhood_disintegrative_disorder = 1 THEN 'Transtorno Desintegrativo da Infância' END),
                (CASE WHEN s.deficiency_type_gifted = 1 THEN 'Altas habilidades / Superdotação' END)
            )
        )
    END) AS `deficiency`,
    ec.name AS `birth_city`,
    s.birthday AS `birthday`,
    eca.name AS `adddress_city`,
    sd.cep AS `cep`,
    (CASE
        WHEN se.vehicle_type_bus = 0 THEN 'Não'
        WHEN se.vehicle_type_bus = 1 THEN 'Sim'
    END) AS `Utiliza Onibus`,
    s.filiation_1 AS `mother`,
    s.filiation_2 AS `father`,
    c.school_year AS `school_year`,
    (CASE
        WHEN sd.residence_zone = '1' THEN 'Urbano'
        WHEN sd.residence_zone = '2' THEN 'Rural'
    END) AS `Localidade`,
    (CASE
        WHEN sr.celiac = 1 THEN 'Doença Celíaca'
    END) AS `Doença_Celíaca`,
    (CASE
        WHEN sr.diabetes = 1 THEN 'Diabetes'
    END) AS `Diabetes`,
    (CASE
        WHEN sr.hypertension = 1 THEN 'Hipertensão'
    END) AS `Hipertensão`,
    (CASE
        WHEN sr.iron_deficiency_anemia = 1 THEN 'Anemia por Deficiência de Ferro'
    END) AS `Anemia_Por_Deficiência_de_Ferro`,
    (CASE
        WHEN sr.sickle_cell_anemia = 1 THEN 'Anemia Falciforme'
    END) AS `Anemia_Falciforme`,
    (CASE
        WHEN sr.lactose_intolerance = 1 THEN 'Intolerância à Lactose'
    END) AS `Intolerância_à_Lactose`,
    (CASE
        WHEN sr.malnutrition = 1 THEN 'Desnutrição'
    END) AS `Desnutrição`,
    (CASE
        WHEN sr.obesity = 1 THEN 'Obesidade'
    END) AS `Obesidade`,
    sr.others AS `others`,
    vcn.name AS 'vaccine_name',
    sci.latitude,
    sci.longitude,
    sci.address AS 'school_address',
    sci.address_number AS 'school_number',
    sci.address_complement AS 'school_complement',
    sci.address_neighborhood AS 'school_neighborhood',
    sci.cep AS 'school_cep',
    sci.inep_id AS 'schoolId',
    svc.vaccine_id as 'vaccine_id'
FROM
    {{ database }}.student_identification s
LEFT JOIN {{ database }}.edcenso_city ec ON s.edcenso_city_fk = ec.id
LEFT JOIN {{ database }}.edcenso_nation en ON s.edcenso_nation_fk = en.id
LEFT JOIN {{ database }}.student_documents_and_address sd ON s.id = sd.id
LEFT JOIN {{ database }}.edcenso_city eca ON sd.edcenso_city_fk = eca.id
LEFT JOIN {{ database }}.edcenso_uf eun ON sd.notary_office_uf_fk = eun.id
LEFT JOIN {{ database }}.edcenso_city ecn ON sd.notary_office_city_fk = ecn.id
LEFT JOIN {{ database }}.student_enrollment se ON s.id = se.student_fk
LEFT JOIN {{ database }}.classroom c ON se.classroom_fk = c.id
LEFT JOIN {{ database }}.edcenso_stage_vs_modality svm ON c.edcenso_stage_vs_modality_fk = svm.id
LEFT JOIN {{ database }}.school_identification sci ON s.school_inep_id_fk = sci.inep_id
LEFT JOIN {{ database }}.student_restrictions sr ON s.id = sr.id
LEFT JOIN {{ database }}.student_vaccine svc ON s.id = svc.student_id
left JOIN {{ database }}.vaccine vcn ON svc.vaccine_id = vcn.id
where se.updated_at > '{{ safe_timestamp }}'
order by s.id;


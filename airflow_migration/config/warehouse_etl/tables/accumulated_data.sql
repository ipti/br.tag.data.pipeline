SELECT
    CONCAT(s.id, '-', sci.inep_id) AS `HASH`,
    se.updated_at AS LogDate,
    '{{ database_raw }}' AS Database_name,
    SUBSTRING('{{ database_raw }}', 1, LOCATE('.', '{{ database_raw }}') - 1) AS CityName,
    s.id AS ID,
    CONCAT(
        (CASE
            WHEN svm.id IN (1,2,3,4,5,6,7,8,9,10,11,25,26,27,28,29,30,31,32,33,34,35,36,37,38) THEN 'NA '
            WHEN svm.id IN (14,15,16,17,18,19,20,21,41) THEN 'NO '
            ELSE ''
        END),
        (CASE
            WHEN svm.id = 1 THEN 'CRECHE'
            WHEN svm.id = 2 THEN 'PRÉ-ESCOLA'
            WHEN svm.id = 3 THEN 'EDUCAÇÃO INFANTIL'
            WHEN svm.id IN (4,14,25,30,35) THEN '1'
            WHEN svm.id IN (5,15,26,31,36) THEN '2'
            WHEN svm.id IN (6,16,27,32,37) THEN '3'
            WHEN svm.id IN (7,17,28,33,38) THEN '4'
            WHEN svm.id IN (8,18) THEN '5'
            WHEN svm.id IN (9,19) THEN '6'
            WHEN svm.id IN (10,20) THEN '7'
            WHEN svm.id IN (11,21) THEN '8'
            WHEN svm.id = 41 THEN '9'
            ELSE ''
        END),
        (CASE
            WHEN svm.id IN (1,2,3) THEN ''
            WHEN svm.id IN (4,5,6,7,8,9,10,11,25,26,27,28,29,30,31,32,33,34,35,36,37,38) THEN '* SÉRIE'
            WHEN svm.id IN (14,15,16,17,18,19,20,21,41) THEN '* ANO'
            ELSE 'NA ____________________'
        END)
    ) AS Class,
    s.name AS StudentName,
    sci.name AS SchoolName,
    sd.neighborhood AS StudentNeighborhood,
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
    END) AS StudentStatus,
    sd.address AS StudentStreet,
    IF(s.bf_participator = 1, 'Sim', 'Não') AS StudentBolsaFamiliaChar,
    s.bf_participator AS StudentBolsaFamilia,
    (CASE
        WHEN svm.stage = '1' THEN 'EDUCAÇÃO INFANTIL'
        WHEN svm.stage = '2' THEN 'ENSINO FUNDAMENTAL'
        WHEN svm.stage = '3' THEN 'ENSINO FUNDAMENTAL'
        WHEN svm.stage = '4' THEN 'ENSINO MÉDIO'
        WHEN svm.stage = '5' THEN 'EDUCAÇÃO PROFISSIONAL'
        WHEN svm.stage = '6' THEN 'EDUCAÇÃO DE JOVENS E ADULTOS'
        WHEN svm.stage = '7' THEN
            (CASE WHEN svm.id = '56' THEN 'MULTIETAPA' ELSE 'ENSINO FUNDAMENTAL' END)
    END) AS StudentStage,
    IF(s.sex = 1, 'Masculino', 'Feminino') AS StudentGender,
    (CASE
        WHEN s.color_race = '1' THEN 'Branca'
        WHEN s.color_race = '2' THEN 'Preta'
        WHEN s.color_race = '3' THEN 'Parda'
        WHEN s.color_race = '4' THEN 'Amarela'
        WHEN s.color_race = '5' THEN 'Indígena'
        ELSE 'Não Declarada'
    END) AS StudentColor,
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
    END) AS StudentDeficiency,
    ec.name AS StudentBirthCity,
    s.birthday AS StudentBirthday,
    eca.name AS StudentAddressCity,
    sd.cep AS StudentCep,
    (CASE WHEN se.vehicle_type_bus = 1 THEN 'Sim' ELSE 'Não' END) AS StudentBus,
    s.filiation_1 AS StudentMotherName,
    s.filiation_2 AS StudentFatherName,
    c.school_year AS ClasssYear,
    (CASE WHEN sd.residence_zone = '1' THEN 'Urbano' ELSE 'Rural' END) AS StudentLocality,
    (CASE WHEN sr.celiac = 1 THEN 'Doença Celíaca' END) AS StudentHasCeliac,
    (CASE WHEN sr.diabetes = 1 THEN 'Diabetes' END) AS StudentHasDiabetes,
    (CASE WHEN sr.hypertension = 1 THEN 'Hipertensão' END) AS StudentHasHypertension,
    (CASE WHEN sr.iron_deficiency_anemia = 1 THEN 'Anemia por Deficiência de Ferro' END) AS StudentHasIronDeficiencyAnemia,
    (CASE WHEN sr.sickle_cell_anemia = 1 THEN 'Anemia Falciforme' END) AS StudentHasSickleCellAnemia,
    (CASE WHEN sr.lactose_intolerance = 1 THEN 'Intolerância à Lactose' END) AS StudentHasLactoseIntolerance,
    (CASE WHEN sr.malnutrition = 1 THEN 'Desnutrição' END) AS StudentHasMalnutrition,
    (CASE WHEN sr.obesity = 1 THEN 'Obesidade' END) AS StudentHasObesity,
    sr.others AS StudentDiferentHealthProblems,
    vcn.name AS StudentVaccine,
    sci.latitude AS SchoolLatitude,
    sci.longitude AS SchoolLongitude,
    sci.address AS SchoolAddress,
    sci.address_number AS SchoolNumber,
    sci.address_complement AS SchoolComplementAddress,
    sci.address_neighborhood AS SchoolComplementNeigborhood,
    sci.cep AS SchoolCep,
    sci.inep_id AS SchoolId,
    '{{ execution_timestamp }}' AS DataLineageIngestion,
    CONCAT(
        (CASE
            WHEN svm.id IN (4,5,6,7,8,9,10,11,25,26,27,28,29,30,31,32,33,34,35,36,37,38) THEN '* SÉRIE'
            WHEN svm.id IN (14,15,16,17,18,19,20,21,41) THEN '* ANO'
            ELSE ''
        END),
        ''
    ) AS StudentSerie,
    svc.vaccine_id AS Vaccine_id
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
where se.updated_at > '{{ last_timestamp }}'
order by s.id;


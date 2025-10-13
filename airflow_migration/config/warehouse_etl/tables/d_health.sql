SELECT
  CONCAT(
    COALESCE(sr.id, 'NO_RESTRICTION'), '-', 
    si.school_inep_id_fk, '-', 
    si.id, '-', 
    COALESCE(se.classroom_fk, 'NO_CLASSROOM')
  ) AS `HASH_ID`,
  COALESCE(sr.id, 'NO_RESTRICTION') AS `F_HASH_ID`,
  sr.celiac AS `celiac_desase`,
  sr.diabetes AS `diabetes_desease`,
  sr.hypertension AS `hypertension_desease`,
  sr.iron_deficiency_anemia AS `iron_deficiency_anemia_desease`,
  sr.lactose_intolerance AS `lactose_intolerance_desease`,
  sr.malnutrition AS `malnutrition_desease`,
  sr.obesity AS `obesity_desease`,
  sr.sickle_cell_anemia,
  sr.`others` AS `other_health_problems`,
  sr.updated_at,
  '{{ execution_timestamp }}' AS `inserted_at`
FROM {{ database }}.student_identification si
LEFT JOIN {{ database }}.student_enrollment se 
  ON si.id = se.student_fk
LEFT JOIN {{ database }}.student_restrictions sr 
  ON si.id = sr.student_fk
LEFT JOIN {{ database }}.school_identification si2 
  ON si.school_inep_id_fk = si2.inep_id 
GROUP BY
  CONCAT(
    COALESCE(sr.id, 'NO_RESTRICTION'), '-', 
    si.school_inep_id_fk, '-', 
    si.id, '-', 
    COALESCE(se.classroom_fk, 'NO_CLASSROOM')
  ),
  COALESCE(sr.id, 'NO_RESTRICTION'), 
  sr.celiac, 
  sr.diabetes, 
  sr.hypertension, 
  sr.iron_deficiency_anemia, 
  sr.lactose_intolerance, 
  sr.malnutrition, 
  sr.obesity, 
  sr.sickle_cell_anemia, 
  sr.`others`, 
  sr.updated_at;

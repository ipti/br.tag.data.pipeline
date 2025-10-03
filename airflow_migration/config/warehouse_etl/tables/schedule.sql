SELECT
    itd.id,
    itd.instructor_fk,
    itd.discipline_fk,
    itd.classroom_fk,
    itd.day,
    itd.month,
    itd.year,
    itd.week,
    itd.week_day,
    itd.schedule,
    itd.turn,
    itd.unavailable,
    itd.fkid,
    itd.hash,
    itd.created_at,
    itd.updated_at,
    '{{ database_raw }}' AS database_name
FROM {{ database }}.schedule AS itd
WHERE itd.updated_at > '{{ safe_timestamp }}';

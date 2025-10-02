select 
    '{{ database_raw }}' AS database_name,
itd.* 
from {{ database }}.edcenso_discipline itd 
where itd.updated_at > '{{ safe_timestamp }}'
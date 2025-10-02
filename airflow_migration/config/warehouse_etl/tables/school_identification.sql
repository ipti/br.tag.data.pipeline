select 
    '{{ database_raw }}' AS database_name,
itd.* 
from {{ database }}.school_identification itd 
where itd.updated_at > '{{ safe_timestamp }}'
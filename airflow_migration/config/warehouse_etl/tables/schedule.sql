select 
    '{{ database_raw }}' AS database_name,
itd.* 
from {{ database }}.schedule itd 
where itd.updated_at > '{{ safe_timestamp }}'
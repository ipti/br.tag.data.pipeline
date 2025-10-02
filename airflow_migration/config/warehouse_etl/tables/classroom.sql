select 
    '{{ database_raw }}' AS database_name,
itd.* 
from {{ database }}.classroom itd 
where itd.updated_at > '{{ safe_timestamp }}'
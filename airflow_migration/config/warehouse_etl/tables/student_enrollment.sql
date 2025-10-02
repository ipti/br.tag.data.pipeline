select 
    '{{ database_raw }}' AS database_name,
itd.* 
from {{ database }}.student_enrollment itd 
where itd.updated_at > '{{ safe_timestamp }}'
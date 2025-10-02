select 
    '{{ database_raw }}' AS database_name,
itd.* 
from {{ database }}.instructor_teaching_data itd 
where itd.updated_at > '{{ safe_timestamp }}'
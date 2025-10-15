{{ config(materialized='ephemeral') }}

select *
from {{ source('dbo_tia', 'F_STUDENT_CLASS') }}

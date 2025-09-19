{{ config(materialized='ephemeral') }}

select *
from {{ source('dbo_tia', 'D_STUDENT') }}

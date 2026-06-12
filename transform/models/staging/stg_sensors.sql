-- Sensor reference data, one row per counting location.

with source as (

    select * from {{ source('raw', 'sensors') }}

)

select
    cast(location_id as integer) as location_id,
    sensor_description as location_name,
    sensor_name,
    cast(installation_date as date) as installation_date,
    location_type,
    status,
    direction_1,
    direction_2,
    cast(latitude as double) as latitude,
    cast(longitude as double) as longitude
from source
qualify row_number() over (partition by location_id order by installation_date desc) = 1

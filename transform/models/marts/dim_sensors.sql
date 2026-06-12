-- One row per counting location, with observed activity bounds.

with sensors as (

    select * from {{ ref('stg_sensors') }}

),

activity as (

    select
        location_id,
        min(sensing_date) as first_observed_date,
        max(sensing_date) as last_observed_date
    from {{ ref('stg_counts') }}
    group by 1

)

select
    sensors.location_id,
    sensors.location_name,
    sensors.sensor_name,
    sensors.installation_date,
    sensors.location_type,
    sensors.status,
    sensors.status = 'A' as is_active,
    sensors.direction_1,
    sensors.direction_2,
    sensors.latitude,
    sensors.longitude,
    activity.first_observed_date,
    activity.last_observed_date
from sensors
left join activity using (location_id)

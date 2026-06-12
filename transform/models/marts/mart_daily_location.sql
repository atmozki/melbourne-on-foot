-- Daily totals per location. This is the main table behind the dashboard:
-- small enough to ship as a Parquet file, detailed enough for trends,
-- rankings and the map.

with daily as (

    select
        location_id,
        sensing_date,
        iso_day_of_week,
        is_weekend,
        sum(pedestrian_count) as daily_count,
        count(*) as hours_reported
    from {{ ref('fct_hourly_counts') }}
    group by 1, 2, 3, 4

)

select
    daily.location_id,
    coalesce(sensors.location_name, 'Location ' || daily.location_id) as location_name,
    sensors.latitude,
    sensors.longitude,
    daily.sensing_date,
    daily.iso_day_of_week,
    daily.is_weekend,
    daily.daily_count,
    daily.hours_reported
from daily
left join {{ ref('dim_sensors') }} as sensors using (location_id)

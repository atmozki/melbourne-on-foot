-- Average hourly traffic per location over the trailing 90 days,
-- broken down by day of week. Feeds the time-of-day heatmap and the
-- weekday versus weekend profiles.

with bounds as (

    select max(sensing_date) as max_date
    from {{ ref('fct_hourly_counts') }}

),

recent as (

    select counts.*
    from {{ ref('fct_hourly_counts') }} as counts
    cross join bounds
    where counts.sensing_date > bounds.max_date - interval 90 day

)

select
    recent.location_id,
    coalesce(sensors.location_name, 'Location ' || recent.location_id) as location_name,
    recent.iso_day_of_week,
    recent.day_name,
    recent.is_weekend,
    recent.hour_of_day,
    avg(recent.pedestrian_count) as avg_count,
    count(*) as n_observations
from recent
left join {{ ref('dim_sensors') }} as sensors using (location_id)
group by 1, 2, 3, 4, 5, 6

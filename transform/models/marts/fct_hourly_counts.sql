-- Hourly grain fact table, enriched with calendar attributes.

select
    observation_id,
    location_id,
    sensing_date,
    hour_of_day,
    cast(sensing_date as timestamp) + hour_of_day * interval 1 hour as observed_at,
    dayname(sensing_date) as day_name,
    isodow(sensing_date) as iso_day_of_week,
    isodow(sensing_date) >= 6 as is_weekend,
    direction_1_count,
    direction_2_count,
    pedestrian_count
from {{ ref('stg_counts') }}

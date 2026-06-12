-- Hourly pedestrian counts, typed and deduplicated.
-- Monthly raw partitions are replaced whole on refresh, but a lookback
-- window can briefly overlap, so keep one row per observation id.

with source as (

    select * from {{ source('raw', 'counts') }}

),

deduplicated as (

    select
        id as observation_id,
        cast(location_id as integer) as location_id,
        cast(sensing_date as date) as sensing_date,
        cast(hourday as integer) as hour_of_day,
        cast(direction_1 as integer) as direction_1_count,
        cast(direction_2 as integer) as direction_2_count,
        cast(pedestriancount as integer) as pedestrian_count,
        sensor_name
    from source
    qualify row_number() over (partition by id order by sensing_date) = 1

)

select * from deduplicated

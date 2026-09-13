{{ config(
    materialized='table',
    indexes=[{'columns': ['user_id', 'ds'], 'unique': True},
             {'columns': ['cohort_month', 'day_offset']}]
) }}

with first_post as (
    select
        user_id,
        posted_at::date as first_post_on
    from {{ ref('fct_first_post') }}
),

days as (
    select
        author_id as user_id,
        posted_at::date as ds,
        count(*) as messages,
        count(*) filter (where is_reply) as replies,
        count(distinct channel_id) as channels
    from {{ ref('fct_member_message') }}
    group by 1, 2
)

select
    d.user_id,
    d.ds,
    date_trunc('month', f.first_post_on)::date as cohort_month,
    f.first_post_on,
    (d.ds - f.first_post_on)::integer as day_offset,
    d.messages::integer as messages,
    d.replies::integer as replies,
    d.channels::integer as channels,
    'v1' as metric_version
from days d
inner join first_post f on f.user_id = d.user_id
where d.ds >= f.first_post_on

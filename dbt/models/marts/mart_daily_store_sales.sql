-- One of the two required marts. Fill the join to fact_sales on the day.
select
    date_key,
    store_key,
    sum(amount) as revenue,
    sum(quantity) as units
from {{ ref('fact_sales') }}
group by 1, 2

-- placeholder staging model; point at your silver product table on the day
select
    product_id,
    product_name,
    category,
    unit_price
from {{ source('silver', 'product') }}

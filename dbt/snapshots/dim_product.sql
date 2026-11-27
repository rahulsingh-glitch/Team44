-- SCD2 for free: dbt snapshot keeps history when price/category change.
{% snapshot dim_product %}
{{
  config(
    target_schema='gold',
    unique_key='product_id',
    strategy='check',
    check_cols=['product_name', 'category', 'unit_price']
  )
}}
select product_id, product_name, category, unit_price
from {{ ref('stg_product') }}
{% endsnapshot %}

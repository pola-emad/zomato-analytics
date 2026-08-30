with source as (

    select * from {{ source('raw', 'RAW_ORDERS') }}

),

renamed as (

    select
        
        order_id,
        order_timestamp::timestamp as order_timestamp,
        order_date::date as order_date,
        user_id as customer_id,
        r_id as restaurant_id,
        trim(coalesce(regexp_substr(restaurant_city, '[^,]+$'), restaurant_city)) as city,
        cuisine,
        items_count,
        sales_qty,
        subtotal,
        discount,
        delivery_fee,
        gst,
        sales_amount,
        currency,
        payment_method,
        order_status,
        customer_rating,
        (order_status='Delivered') as is_delivered,
        delivery_time_min

    from source

)

select * from renamed

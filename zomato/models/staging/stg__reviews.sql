with source as (

    select * from {{ source('raw', 'RAW_REVIEWS') }}

),

renamed as (

    select
        review_id,
        order_id,
        user_id,
        restaurant_id,
        rating,
        comment,
        review_date::date as review_date,

    from source

)

select * from renamed

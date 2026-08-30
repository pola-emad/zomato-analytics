with source as (

    select * from {{ source('raw', 'RAW_MENU') }}

),

renamed as (

    select
        
        menu_id,
        r_id as restaurant_id,
        f_id as food_id,
        cuisine,
        price::decimal(10,2) as price

    from source

)

select * from renamed

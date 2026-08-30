with source as (

    select * from {{ source('raw', 'RAW_FOOD') }}

),

renamed as (

    select
        
        f_id as food_id,
        item as food_name,
        veg_or_non_veg

    from source

)

select * from renamed

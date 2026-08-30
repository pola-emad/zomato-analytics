with source as (

    select * from {{ source('raw', 'RAW_USERS') }}

),

renamed as (

    select
        
        user_id as customer_id,
        name as customer_name,
        email,
        age::integer as age,
        gender,
        "MARITAL STATUS" as marital_status,
        occupation,
        "MONTHLY INCOME" as income_band,
        "EDUCATIONAL QUALIFICATIONS" as education,
        "FAMILY SIZE" as family_size

    from source
limit 4
)

select * from renamed

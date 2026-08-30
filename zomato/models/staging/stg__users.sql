with source as (

    select * from {{ source('raw', 'RAW_USERS') }}

),

renamed as (

    select
        
        user_id,
        name as user_name,
        email,
        age::integer as age,
        gender,
        "MARITAL STATUS" as marital_status,
        occupation,
        "MONTHLY INCOME" as monthly_income,
        "EDUCATIONAL QUALIFICATIONS" as educational_qualifications,
        "FAMILY SIZE" as family_size

    from source
limit 4
)

select * from renamed

"""解析结果的长度和数量边界。"""


_PARSED_BASIC_FIELD_LIMITS = {
    "name": 64,
    "gender": 64,
    "birth_year": 32,
    "phone": 32,
    "email": 128,
    "city": 64,
    "target_city": 64,
    "job_intent": 128,
    "personal_website": 256,
    "github": 256,
}
_PARSED_ENTRY_FIELD_LIMITS = {
    "educations": {
        "reference_file_name": 255,
        "reference_content": 200_000,
        "school": 128,
        "major": 128,
        "degree": 32,
        "start_date": 32,
        "end_date": 32,
        "gpa": 64,
        "courses": 200_000,
        "achievements": 200_000,
    },
    "experiences": {
        "reference_file_name": 255,
        "reference_content": 200_000,
        "company": 128,
        "role": 128,
        "start_date": 32,
        "end_date": 32,
        "description": 200_000,
    },
    "campus_experiences": {
        "reference_file_name": 255,
        "reference_content": 200_000,
        "organization": 128,
        "role": 128,
        "start_date": 32,
        "end_date": 32,
        "description": 200_000,
    },
    "projects": {
        "reference_file_name": 255,
        "reference_content": 200_000,
        "name": 128,
        "role": 64,
        "start_date": 32,
        "end_date": 32,
        "tech_stack": 10_000,
        "description": 200_000,
        "highlights": 200_000,
    },
    "skills": {"name": 64, "level": 32},
    "awards": {"name": 128, "date": 32, "description": 2_000},
}
_MAX_PARSED_SECTION_ITEMS = 200

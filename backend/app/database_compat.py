"""早期未版本化数据库所需的兼容字段定义。"""

SQLITE_REQUIRED_COLUMNS = {
    "job": {
        "note": "TEXT NOT NULL DEFAULT ''",
        "favorite": "BOOLEAN NOT NULL DEFAULT 0",
    },
    "user_profile": {
        "photo": "TEXT NOT NULL DEFAULT ''",
        "section_order": "TEXT NOT NULL DEFAULT '[]'",
    },
    "education": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "experience": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "campus_experience": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "project": {
        "reference_file_name": "VARCHAR(255) NOT NULL DEFAULT ''",
        "reference_content": "TEXT NOT NULL DEFAULT ''",
    },
    "resume_record": {
        "job_id": "INTEGER",
        "source": "VARCHAR(16) NOT NULL DEFAULT 'ai'",
        "enhancement_enabled": "BOOLEAN NOT NULL DEFAULT 0",
        "enhancement_level": "VARCHAR(16) NOT NULL DEFAULT 'balanced'",
    },
    "chat_conversation": {
        "pinned": "BOOLEAN NOT NULL DEFAULT 0",
        "favorite": "BOOLEAN NOT NULL DEFAULT 0",
    },
}

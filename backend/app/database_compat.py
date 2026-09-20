"""早期未版本化数据库所需的兼容字段定义。"""

SQLITE_REQUIRED_COLUMNS = {
    "job": {
        "note": "TEXT NOT NULL DEFAULT ''",
        "favorite": "BOOLEAN NOT NULL DEFAULT 0",
        "note_images": "TEXT NOT NULL DEFAULT '[]'",
        "recognition_source": "VARCHAR(32) NOT NULL DEFAULT ''",
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
        "template": "VARCHAR(32) NOT NULL DEFAULT 'classic'",
        "format_name": "VARCHAR(64) NOT NULL DEFAULT ''",
        "format_config": "JSON NOT NULL DEFAULT '{}'",
        "page_limit": "INTEGER NOT NULL DEFAULT 1",
        "font_scale": "VARCHAR(16) NOT NULL DEFAULT 'standard'",
        "custom_instruction": "TEXT NOT NULL DEFAULT ''",
        "note": "TEXT NOT NULL DEFAULT ''",
    },
    "chat_conversation": {
        "pinned": "BOOLEAN NOT NULL DEFAULT 0",
        "favorite": "BOOLEAN NOT NULL DEFAULT 0",
        "archived": "BOOLEAN NOT NULL DEFAULT 0",
        "group_name": "VARCHAR(64) NOT NULL DEFAULT ''",
    },
    "chat_message": {
        "quoted_message_id": "INTEGER",
    },
    "llm_config_record": {
        "top_p": "FLOAT",
        "frequency_penalty": "FLOAT",
        "presence_penalty": "FLOAT",
        "seed": "INTEGER",
        "api_style": "VARCHAR(16) NOT NULL DEFAULT 'openai'",
        "top_k": "INTEGER",
        "repetition_penalty": "FLOAT",
        "stop": "TEXT NOT NULL DEFAULT '[]'",
        "thinking_budget": "INTEGER",
        "extra_body": "TEXT NOT NULL DEFAULT '{}'",
    },
}

"""个人资料条目参考文件的 API 校验与持久化测试。"""
import pytest

from app.schemas.profile import (
    MAX_REFERENCE_CONTENT_CHARS,
    MAX_REFERENCE_FILE_NAME_CHARS,
)


def test_profile_reference_files_roundtrip(client):
    reference_content = """# 应用软件项目实习总结

## 项目背景
面向实际业务完成需求分析、系统设计和交付。

## 个人贡献
- 负责 FastAPI 接口设计
- 完成 React 页面联调
"""
    payload = {
        "educations": [
            {
                "school": "示例大学",
                "reference_file_name": "本科培养总结.md",
                "reference_content": reference_content,
            }
        ],
        "experiences": [
            {
                "company": "示例科技",
                "reference_file_name": "实习复盘.txt",
                "reference_content": reference_content,
            }
        ],
        "campus_experiences": [
            {
                "organization": "学生会",
                "reference_file_name": "学生工作总结.md",
                "reference_content": reference_content,
            }
        ],
        "projects": [
            {
                "name": "简历通",
                "reference_file_name": "应用软件项目实习2项目总结.md",
                "reference_content": reference_content,
            }
        ],
    }

    saved_response = client.put("/api/profile", json=payload)

    assert saved_response.status_code == 200
    saved = saved_response.json()
    assert saved["educations"][0]["reference_file_name"] == "本科培养总结.md"
    assert saved["experiences"][0]["reference_content"] == reference_content
    assert saved["campus_experiences"][0]["reference_file_name"] == "学生工作总结.md"
    assert saved["projects"][0]["reference_file_name"] == "应用软件项目实习2项目总结.md"

    loaded = client.get("/api/profile").json()
    assert loaded["educations"][0]["reference_content"] == reference_content
    assert loaded["experiences"][0]["reference_file_name"] == "实习复盘.txt"
    assert loaded["campus_experiences"][0]["reference_content"] == reference_content
    assert loaded["projects"][0]["reference_content"] == reference_content


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "reference_file_name",
            "文" * (MAX_REFERENCE_FILE_NAME_CHARS + 1),
            f"参考文件名不能超过 {MAX_REFERENCE_FILE_NAME_CHARS} 个字符",
        ),
        (
            "reference_content",
            "内" * (MAX_REFERENCE_CONTENT_CHARS + 1),
            f"参考文件内容不能超过 {MAX_REFERENCE_CONTENT_CHARS} 个字符",
        ),
    ],
    ids=["file-name", "content"],
)
def test_profile_rejects_oversized_reference_file_fields(client, field, value, message):
    response = client.put(
        "/api/profile",
        json={"projects": [{"name": "超长输入测试", field: value}]},
    )

    assert response.status_code == 422
    assert message in response.text

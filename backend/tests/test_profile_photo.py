"""个人照片的 API 往返、校验与简历渲染链路测试。"""
import base64

import pytest

from app.models.resume import ResumeRecord
from app.schemas.profile import MAX_PROFILE_PHOTO_BYTES


PHOTO_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Zl2kAAAAASUVORK5CYII="
)


def test_profile_photo_roundtrip(client):
    response = client.put("/api/profile", json={"name": "张三", "photo": PHOTO_DATA_URL})

    assert response.status_code == 200
    assert response.json()["photo"] == PHOTO_DATA_URL
    assert client.get("/api/profile").json()["photo"] == PHOTO_DATA_URL


@pytest.mark.parametrize(
    ("photo", "message"),
    [
        ("https://example.com/avatar.png", "JPEG、PNG 或 WebP"),
        ("data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==", "JPEG、PNG 或 WebP"),
        ("data:image/png;base64,not-valid-base64!", "有效的 base64"),
        (
            "data:image/png;base64," + base64.b64encode(b"not a png").decode(),
            "图片格式不一致",
        ),
    ],
)
def test_profile_rejects_invalid_photo(client, photo, message):
    response = client.put("/api/profile", json={"name": "张三", "photo": photo})

    assert response.status_code == 422
    assert message in response.text


def test_profile_rejects_oversized_photo(client):
    max_encoded_chars = 4 * ((MAX_PROFILE_PHOTO_BYTES + 2) // 3)
    photo = "data:image/png;base64," + "A" * (max_encoded_chars + 4)

    response = client.put("/api/profile", json={"name": "张三", "photo": photo})

    assert response.status_code == 422
    assert "2 MB" in response.text


def test_resume_preview_conditionally_renders_photo(client):
    with_photo = client.post(
        "/api/resumes/render",
        json={"content": {"name": "张三", "photo": PHOTO_DATA_URL}},
    )
    without_photo = client.post("/api/resumes/render", json={"content": {"name": "张三"}})

    assert with_photo.status_code == 200
    assert f'src="{PHOTO_DATA_URL}"' in with_photo.text
    assert '<img class="profile-photo"' in with_photo.text
    assert without_photo.status_code == 200
    assert '<img class="profile-photo"' not in without_photo.text


def test_resume_preview_rejects_untrusted_photo_url(client):
    response = client.post(
        "/api/resumes/render",
        json={"content": {"name": "张三", "photo": "https://example.com/avatar.png"}},
    )

    assert response.status_code == 422
    assert "base64 data URL" in response.text


def test_saved_resume_preserves_photo_in_detail_and_exports(client, db_session):
    record = ResumeRecord(
        title="张三-测试简历",
        job_title="后端开发工程师",
        company="示例公司",
        content={"name": "张三", "photo": PHOTO_DATA_URL},
    )
    db_session.add(record)
    db_session.commit()

    detail = client.get(f"/api/resumes/{record.id}")
    html = client.get(f"/api/resumes/{record.id}/export", params={"format": "html"})
    markdown = client.get(f"/api/resumes/{record.id}/export", params={"format": "md"})
    exported_json = client.get(f"/api/resumes/{record.id}/export", params={"format": "json"})

    assert detail.status_code == 200
    assert detail.json()["content"]["photo"] == PHOTO_DATA_URL
    assert html.status_code == 200 and f'src="{PHOTO_DATA_URL}"' in html.text
    assert markdown.status_code == 200
    assert markdown.headers["content-type"].startswith("text/markdown")
    assert PHOTO_DATA_URL not in markdown.text
    assert "个人照片" not in markdown.text
    assert exported_json.status_code == 200
    assert "photo" not in exported_json.json()

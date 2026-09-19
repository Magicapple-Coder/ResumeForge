"""``privacy`` 脱敏变换的纯函数测试。"""
from app.schemas.resume import ResumeContent
from app.services.privacy import MASK, RedactionOptions, redact


def _resume() -> ResumeContent:
    return ResumeContent(
        name="张三",
        phone="13800000000",
        email="a@example.com",
        summary="负责 XX 产品从 0 到 1 的搭建",
        education=[{"school": "清华大学", "major": "计算机"}],
        experience=[
            {"company": "字节跳动", "role": "工程师", "description": ["参与 XX 产品研发"]}
        ],
        projects=[
            {
                "name": "XX 产品",
                "role": "核心开发",
                "tech_stack": ["Python"],
                "description": ["在字节跳动负责 XX 产品"],
                "highlights": [],
            }
        ],
    )


def test_default_masks_pii_but_not_school_or_project():
    resume = redact(_resume())
    assert resume.name == MASK
    assert resume.phone == MASK
    assert resume.email == MASK
    assert resume.experience[0].company == MASK
    # 学校 / 项目默认不遮罩。
    assert resume.education[0].school == "清华大学"
    assert resume.projects[0].name == "XX 产品"


def test_optional_masks():
    resume = redact(
        _resume(),
        RedactionOptions(mask_school=True, mask_project=True),
    )
    assert resume.education[0].school == MASK
    assert resume.projects[0].name == MASK


def test_mask_product_replaces_known_tokens_in_prose():
    resume = redact(_resume(), RedactionOptions(mask_product=True))
    assert "XX 产品" not in resume.summary
    assert "字节跳动" not in resume.experience[0].description[0]
    assert "XX 产品" not in resume.projects[0].description[0]


def test_redact_does_not_mutate_input():
    original = _resume()
    redact(original)
    assert original.name == "张三"
    assert original.phone == "13800000000"
    assert original.experience[0].company == "字节跳动"
    assert original.projects[0].name == "XX 产品"


def test_empty_values_stay_empty():
    resume = redact(ResumeContent())
    assert resume.name == ""
    assert resume.phone == ""

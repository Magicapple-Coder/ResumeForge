"""纯文本（txt）导出：复用 Markdown 结构、去掉 Markdown 标记。"""
from app.schemas.resume import ResumeContent
from app.services.exporter import export_markdown
from app.services.txt_exporter import export_txt, strip_markdown


def _resume() -> ResumeContent:
    return ResumeContent(
        name="张三",
        phone="13800000000",
        summary="负责后端服务的设计与开发。",
        education=[{"school": "清华大学", "major": "计算机", "degree": "本科", "gpa": "3.9"}],
        experience=[{"company": "字节跳动", "role": "工程师", "description": ["实现检索接口"]}],
        skills=[{"name": "Python", "level": "熟练"}],
        awards=[{"name": "校级奖学金", "date": "2023"}],
    )


def test_export_txt_keeps_all_sections_without_markdown():
    text = export_txt(_resume())

    for section in ("个人总结", "教育经历", "实习/工作经历", "专业技能", "荣誉奖项"):
        assert section in text
    # 去掉了 Markdown 标记：无标题井号、无加粗、无列表短横线。
    assert "#" not in text
    assert "**" not in text
    assert "\n- " not in text


def test_export_txt_is_word_for_word_the_markdown_body():
    """纯文本与 Markdown 同源：正文关键词一个都不能少（照片本就都不包含）。"""
    resume = _resume()
    md = export_markdown(resume)
    txt = export_txt(resume)

    # 确认确实是从 Markdown 剥出来的（源里有标记、目标里没有）。
    assert md.count("#") > 0
    assert "#" not in txt

    for keyword in (
        "张三",
        "清华大学",
        "字节跳动",
        "Python",
        "校级奖学金",
        "实现检索接口",
        "绩点/排名：3.9",
    ):
        assert keyword in txt


def test_strip_markdown_removes_headings_bullets_and_bold():
    source = "# 标题\n## 子标题\n### 条目\n- 项目一\n- 项目二\n**加粗**文字"
    assert strip_markdown(source) == "标题\n子标题\n条目\n项目一\n项目二\n加粗文字"

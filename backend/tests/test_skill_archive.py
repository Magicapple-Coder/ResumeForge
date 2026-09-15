"""技能包解包与解析的测试。

这一层是导入链路上风险最高的地方：内容完全来自用户提供的压缩包，必须把
zip bomb、路径穿越、非法类型都挡在外面。
"""
import zipfile
from pathlib import Path

import pytest

from app.services.skill_archive import (
    MAX_SKILL_FILES,
    SkillImportError,
    parse_markdown_skill,
    parse_zip_skill,
)

FRONTMATTER = """---
name: 面试模拟官
description: 用户想练面试时使用
---

你是面试官，逐题提问并追问。
"""


def _zip(path: Path, members: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return path


def test_single_markdown_imports_as_a_prompt_only_skill(tmp_path):
    target = tmp_path / "面试模拟官.md"
    target.write_text(FRONTMATTER, encoding="utf-8")

    skill = parse_markdown_skill(target)

    assert skill.name == "面试模拟官"
    assert skill.description == "用户想练面试时使用"
    assert "你是面试官" in skill.prompt
    assert skill.files == []


def test_markdown_without_frontmatter_falls_back_to_the_filename(tmp_path):
    target = tmp_path / "简历诊断.md"
    target.write_text("请逐条指出简历里的问题。", encoding="utf-8")

    skill = parse_markdown_skill(target)

    assert skill.name == "简历诊断"
    assert skill.warnings and "文件名" in skill.warnings[0]


def test_markdown_with_an_empty_prompt_is_rejected(tmp_path):
    target = tmp_path / "空的.md"
    target.write_text("---\nname: 空技能\n---\n\n", encoding="utf-8")

    with pytest.raises(SkillImportError, match="提示词是空的"):
        parse_markdown_skill(target)


def test_markdown_that_is_not_utf8_is_rejected(tmp_path):
    target = tmp_path / "乱码.md"
    target.write_bytes(b"\xff\xfe\x00\x00bad")

    with pytest.raises(SkillImportError, match="不是 UTF-8"):
        parse_markdown_skill(target)


def test_zip_imports_prompt_plus_knowledge_files(tmp_path):
    archive = _zip(
        tmp_path / "面试包.zip",
        {
            "SKILL.md": FRONTMATTER,
            "互联网面试常见题型.md": "常见题型包括自我介绍、项目追问。",
            "行为面 STAR 模板.txt": "Situation / Task / Action / Result。",
        },
    )

    skill = parse_zip_skill(archive)

    assert skill.name == "面试模拟官"
    assert "你是面试官" in skill.prompt
    assert [path for path, _ in skill.files] == ["互联网面试常见题型.md", "行为面 STAR 模板.txt"]


def test_zip_needs_an_unambiguous_prompt(tmp_path):
    archive = _zip(
        tmp_path / "两份.md.zip",
        {"一.md": "甲", "二.md": "乙"},
    )

    with pytest.raises(SkillImportError, match="需要有且只有一份提示词"):
        parse_zip_skill(archive)


def test_zip_without_any_prompt_is_rejected(tmp_path):
    archive = _zip(tmp_path / "没有提示词.zip", {"知识.txt": "一些资料"})

    with pytest.raises(SkillImportError, match="需要有且只有一份提示词"):
        parse_zip_skill(archive)


@pytest.mark.parametrize("name", ["../evil.md", "/etc/passwd.md", "sub/../../up.md", "C:evil.md"])
def test_zip_rejects_path_traversal_members(tmp_path, name):
    archive = tmp_path / "穿越.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("SKILL.md", FRONTMATTER)
        handle.writestr(zipfile.ZipInfo(name), "内容")

    with pytest.raises(SkillImportError, match="越级路径|绝对路径"):
        parse_zip_skill(archive)


def test_zip_rejects_disallowed_extensions(tmp_path):
    archive = _zip(
        tmp_path / "脚本.zip",
        {"SKILL.md": FRONTMATTER, "run.exe": "MZ"},
    )

    with pytest.raises(SkillImportError, match="只允许 .md/.txt"):
        parse_zip_skill(archive)


def test_zip_rejects_too_many_members(tmp_path):
    members = {"SKILL.md": FRONTMATTER}
    members.update({f"知识{i}.md": "内容" for i in range(MAX_SKILL_FILES + 5)})

    with pytest.raises(SkillImportError, match="最多包含"):
        parse_zip_skill(_zip(tmp_path / "太多.zip", members))


def test_zip_rejects_a_zip_bomb(tmp_path):
    """一个解压后极大的成员必须被挡下，而不是读进内存。"""
    archive = tmp_path / "bomb.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as handle:
        handle.writestr("SKILL.md", FRONTMATTER)
        handle.writestr("巨大.md", "0" * 2_000_000)

    with pytest.raises(SkillImportError, match="过大"):
        parse_zip_skill(archive)


def test_zip_rejects_an_encrypted_member(tmp_path):
    """加密成员读不出内容，应当明确拒绝而不是解出乱码。"""
    archive = _zip(tmp_path / "加密.zip", {"SKILL.md": FRONTMATTER, "秘密.md": "内容"})
    raw = bytearray(archive.read_bytes())

    # 置上通用位标记的加密位（本地文件头偏移 6、中央目录偏移 8）。
    local = raw.find(b"PK\x03\x04")
    central = raw.find(b"PK\x01\x02")
    assert local >= 0 and central >= 0
    raw[local + 6] |= 0x1
    raw[central + 8] |= 0x1
    archive.write_bytes(bytes(raw))

    with pytest.raises(SkillImportError, match="加密文件"):
        parse_zip_skill(archive)


def test_broken_archive_is_rejected(tmp_path):
    broken = tmp_path / "坏.zip"
    broken.write_bytes(b"not a zip at all")

    with pytest.raises(SkillImportError, match="不是有效的压缩文件"):
        parse_zip_skill(broken)


def test_overlong_name_is_rejected(tmp_path):
    target = tmp_path / "长名.md"
    target.write_text(f"---\nname: {'长' * 100}\n---\n\n内容", encoding="utf-8")

    with pytest.raises(SkillImportError, match="名称不能超过"):
        parse_markdown_skill(target)

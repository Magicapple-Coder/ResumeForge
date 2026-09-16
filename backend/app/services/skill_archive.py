"""技能包的解包与解析。

技能有两种形态：单独一份提示词（``.md``），或者一个压缩包里含提示词加若干知识文件。

``data_backup.extract_database`` 的做法不能直接照搬：它只读**固定成员名**，一旦放开到
任意成员就必须补上它不需要的防护——成员数量、**单成员解压后的大小**（否则是 zip bomb
敞口）、压缩比、扩展名白名单、加密成员。这里把这些补齐，并保持不用 ``extractall``。
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

# 单个知识文件的上限，与经历参考文件保持一致（schemas/profile.py）。
MAX_SKILL_FILE_CHARS = 200_000
# 一个技能包的整体上限，避免导入超大技能把上下文与数据库都撑爆。
MAX_SKILL_TOTAL_CHARS = 600_000
MAX_SKILL_FILES = 50
# 压缩比上限：正常文本压缩比在 10 倍上下，超过这个量级基本可以断定是 zip bomb。
MAX_COMPRESSION_RATIO = 120
ALLOWED_SUFFIXES = (".md", ".txt")
PROMPT_MEMBER_NAMES = ("SKILL.md", "skill.md", "README.md")
MAX_NAME_CHARS = 64
MAX_DESCRIPTION_CHARS = 255


class SkillImportError(Exception):
    """面向使用者的错误，消息可直接展示。"""


@dataclass
class ParsedSkill:
    name: str
    description: str
    prompt: str
    source_name: str
    files: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _strip_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆出 YAML frontmatter。只支持 ``key: value`` 这种最简单的形式。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    header = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, str] = {}
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if not separator:
            continue
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, body


def _safe_member_path(name: str) -> str:
    """把成员名规范化成安全的相对路径；任何可疑形式一律拒绝。"""
    candidate = name.replace("\\", "/").strip()
    if not candidate or candidate.endswith("/"):
        raise SkillImportError("技能包里包含空文件名或目录项")
    if candidate.startswith("/") or ":" in candidate:
        raise SkillImportError(f"技能包里包含绝对路径：{name}")
    parts = PurePosixPath(candidate).parts
    if ".." in parts:
        raise SkillImportError(f"技能包里包含越级路径：{name}")
    base = parts[-1]
    if not base.lower().endswith(ALLOWED_SUFFIXES):
        raise SkillImportError(f"技能包只允许 .md/.txt 文件，收到：{name}")
    # 只保留末段，避免嵌套目录带来的歧义（技能不需要目录结构）。
    return base


def _decode(raw: bytes, label: str) -> str:
    try:
        # utf-8-sig 能顺带吃掉 BOM。
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SkillImportError(f"{label} 不是 UTF-8 文本") from exc


def _read_members(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    infos = [info for info in archive.infolist() if not info.is_dir()]
    if not infos:
        raise SkillImportError("技能包是空的")
    if len(infos) > MAX_SKILL_FILES:
        raise SkillImportError(f"技能包最多包含 {MAX_SKILL_FILES} 个文件，收到 {len(infos)} 个")

    files: list[tuple[str, str]] = []
    total = 0
    for info in infos:
        if info.flag_bits & 0x1:
            raise SkillImportError(f"技能包里包含加密文件，无法读取：{info.filename}")
        path = _safe_member_path(info.filename)
        # 先按声明的大小卡一道，避免把 zip bomb 读进内存。
        if info.file_size > MAX_SKILL_FILE_CHARS * 4:
            raise SkillImportError(f"{path} 过大，单个文件不能超过 {MAX_SKILL_FILE_CHARS} 个字符")
        if info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
            raise SkillImportError(f"{path} 的压缩比异常，已拒绝导入")
        with archive.open(info) as handle:
            raw = handle.read(MAX_SKILL_FILE_CHARS * 4 + 1)
        if len(raw) > MAX_SKILL_FILE_CHARS * 4:
            raise SkillImportError(f"{path} 过大，单个文件不能超过 {MAX_SKILL_FILE_CHARS} 个字符")
        content = _decode(raw, path)
        if len(content) > MAX_SKILL_FILE_CHARS:
            raise SkillImportError(f"{path} 过大，单个文件不能超过 {MAX_SKILL_FILE_CHARS} 个字符")
        total += len(content)
        if total > MAX_SKILL_TOTAL_CHARS:
            raise SkillImportError(f"技能包总长度超过 {MAX_SKILL_TOTAL_CHARS} 个字符，请拆分后再导入")
        files.append((path, content))
    return files


def _pick_prompt(files: list[tuple[str, str]]) -> tuple[str, list[tuple[str, str]]]:
    """选出作为提示词的那份，其余视为知识文件。"""
    for preferred in PROMPT_MEMBER_NAMES:
        for path, content in files:
            if path.lower() == preferred.lower():
                return content, [(p, c) for p, c in files if p != path]
    markdown = [(p, c) for p, c in files if p.lower().endswith(".md")]
    if len(markdown) == 1:
        path, content = markdown[0]
        return content, [(p, c) for p, c in files if p != path]
    raise SkillImportError(
        "技能包里需要有且只有一份提示词：请把它命名为 SKILL.md，"
        "或让包里只保留一份 .md 文件"
    )


def _finish(name: str, description: str, prompt: str, rest, source_name: str, warnings) -> ParsedSkill:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise SkillImportError("技能缺少名称：请在提示词顶部用 frontmatter 写明 name")
    if len(cleaned_name) > MAX_NAME_CHARS:
        raise SkillImportError(f"技能名称不能超过 {MAX_NAME_CHARS} 个字符")
    if not prompt.strip():
        raise SkillImportError("技能提示词是空的")
    return ParsedSkill(
        name=cleaned_name,
        description=description.strip()[:MAX_DESCRIPTION_CHARS],
        prompt=prompt,
        source_name=source_name,
        files=rest,
        warnings=warnings,
    )


def parse_markdown_skill(path: Path, source_name: str | None = None) -> ParsedSkill:
    """导入单独一份 .md：只有提示词，没有知识文件。

    ``source_name`` 是使用者看到的原始文件名。上传时请求体是裸字节，落盘的临时文件只能用
    随机名，所以名字必须由调用方传进来——否则"用文件名作为技能名称"会退化成随机 UUID。
    """
    display_name = source_name or path.name
    text = _decode(path.read_bytes(), display_name)
    if len(text) > MAX_SKILL_FILE_CHARS:
        raise SkillImportError(f"技能提示词不能超过 {MAX_SKILL_FILE_CHARS} 个字符")
    meta, body = _strip_frontmatter(text)
    warnings = []
    name = meta.get("name", "")
    if not name:
        name = PurePosixPath(display_name).stem
        warnings.append("提示词没有 frontmatter 的 name，已用文件名作为技能名称")
    return _finish(name, meta.get("description", ""), body, [], display_name, warnings)


def parse_zip_skill(path: Path, source_name: str | None = None) -> ParsedSkill:
    """导入一个技能包：一份提示词 + 若干知识文件。"""
    display_name = source_name or path.name
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise SkillImportError("技能包不是有效的压缩文件") from exc

    with archive:
        files = _read_members(archive)

    prompt_text, rest = _pick_prompt(files)
    meta, body = _strip_frontmatter(prompt_text)
    warnings = []
    name = meta.get("name", "")
    if not name:
        name = PurePosixPath(display_name).stem
        warnings.append("提示词没有 frontmatter 的 name，已用文件名作为技能名称")
    return _finish(name, meta.get("description", ""), body, rest, display_name, warnings)

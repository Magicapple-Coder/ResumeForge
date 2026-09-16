"""随包资源的完整性检查。

发行包是维护者打包的（正确做法见 ``scripts/Build-Release.ps1``，它会自检压缩包里的必需
文件）。历史上出现过手工压缩包漏掉 ``backend/app/data/`` 的情况：后端在**导入阶段**就抛
``FileNotFoundError``，用户在控制台只看到一句 "Backend exited ... See
runtime\\backend.stderr.log"，分不清是包不完整、环境不对还是代码有问题。

这里在导入应用之前把这些资源检查一遍，用一句话说清"缺什么、怎么办"。调用点在
``app/__init__.py``：导入 ``app.main`` 时会先执行包初始化，所以检查跑在任何子模块的导入
之前——放到后面就又变成一条看不懂的导入栈了。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

_BACKEND_ROOT: Final = Path(__file__).resolve().parent.parent

# 随包发送、缺了就无法正常工作的文件：(相对 backend/ 的路径, 用途)。
_REQUIRED_FILES: Final[tuple[tuple[str, str], ...]] = (
    ("app/data/skills.json", "内置技能词典，岗位解析与匹配要用"),
    ("app/prompts/assistant_system.md", "AI 助手系统提示词"),
    ("app/prompts/assistant_welcome.md", "求职助手的默认引导对话"),
    ("app/prompts/image_extraction_addendum.md", "图片识别补充提示词"),
    ("app/prompts/job_analysis.md", "岗位分析提示词"),
    ("app/prompts/job_text_extract.md", "招聘信息识别提示词"),
    ("app/prompts/profile_text_extract.md", "个人资料识别提示词"),
    ("app/prompts/resume_fix_json.md", "简历 JSON 修复提示词"),
    ("app/prompts/resume_generate_system.md", "简历生成系统提示词"),
    ("app/prompts/resume_generate_user.md", "简历生成用户提示词"),
    ("app/prompts/resume_quality_retry.md", "简历质量重试提示词"),
    ("app/prompts/resume_suggestions.md", "简历改进建议提示词"),
    # 简历模板：三套版式加两段共用片段。缺了它们在生成简历时才会炸，而那时用户
    # 已经等了一轮模型调用；在这里拦住，报的是"包不完整"而不是一段渲染栈。
    ("app/templates/resume.html.j2", "经典简历模板"),
    ("app/templates/resume_modern.html.j2", "现代简历模板"),
    ("app/templates/resume_compact.html.j2", "精简简历模板"),
    ("app/templates/_resume_sections.j2", "简历正文片段（三套模板共用）"),
    ("app/templates/_resume_fit_script.j2", "简历放不下时的测量脚本"),
    ("alembic.ini", "数据库迁移配置"),
)

# 目录类资源：目录里至少要有一个 .py（空目录在 git 里根本存不下来）。
_REQUIRED_DIRECTORIES: Final[tuple[tuple[str, str], ...]] = (
    ("migrations/versions", "数据库迁移脚本"),
)

_SKILLS_PATH: Final = "app/data/skills.json"

_INCOMPLETE_HINT: Final = (
    "安装包不完整，后端无法启动：\n"
    "{problems}\n"
    "\n"
    "如果是解压安装：请重新下载完整压缩包（这一份少了文件，通常是打包时漏掉了目录），"
    "或者改从 Git 仓库获取。\n"
    "如果是从源码打包：请用仓库里的 scripts\\Build-Release.ps1，它会自检压缩包内容。"
)


def _skills_problem(path: Path) -> str | None:
    """技能词典的问题描述；正常时返回 ``None``。

    既检查读得出来，也检查结构：词典必须是 ``{"categories": {...}}``，每个分类下是非空
    列表。结构不对时 ``_build_skill_matchers`` 会抛 ``TypeError``/``AttributeError``，
    那种栈同样看不出"包不完整"。
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return f"不是合法 JSON（{exc.msg}）"
    except OSError as exc:
        return f"读不出来（{exc.strerror}）"
    if not isinstance(data, dict):
        return '结构不对：顶层应该是 {"categories": {...}} 这样的对象'
    categories = data.get("categories")
    if not isinstance(categories, dict) or not categories:
        return '"categories" 缺失或不是非空对象'
    if any(not isinstance(words, list) or not words for words in categories.values()):
        return '"categories" 里有空分类'
    return None


def ensure_runtime_resources() -> None:
    """缺失或不完整时抛 ``RuntimeError``，消息本身给出下一步。"""
    problems: list[str] = []
    for relative, purpose in _REQUIRED_FILES:
        path = _BACKEND_ROOT / relative
        if not path.is_file():
            problems.append(f"  · 缺少 backend/{relative}（{purpose}）")
        elif relative == _SKILLS_PATH:
            detail = _skills_problem(path)
            if detail is not None:
                problems.append(f"  · backend/{relative} 内容不可用：{detail}")
    for relative, purpose in _REQUIRED_DIRECTORIES:
        if not any((_BACKEND_ROOT / relative).glob("*.py")):
            problems.append(f"  · 缺少 backend/{relative}/*.py（{purpose}）")
    if not problems:
        return
    raise RuntimeError(_INCOMPLETE_HINT.format(problems="\n".join(problems)))

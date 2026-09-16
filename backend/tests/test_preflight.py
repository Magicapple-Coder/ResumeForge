"""启动完整性检查：包不完整时要说清缺什么，而不是抛一条导入栈。

背景（真机反馈）：手工打的压缩包漏了 `backend/app/data/`，后端在导入阶段就抛
`FileNotFoundError`，用户看到的是 "Backend exited ... See runtime\\backend.stderr.log"，
无从判断是包不完整还是环境问题。

单测用**裁剪过的清单**（见 ``focused_checklist``）：这些用例验证的是"某项资源出问题时
怎么报"，不需要造满整棵树，临时目录越干净越好。真实清单由下面两条一致性问题守住。
"""

import json
import re
from pathlib import Path

import pytest

from app import preflight

BACKEND_ROOT = Path(__file__).resolve().parent.parent
APP_ROOT = BACKEND_ROOT / "app"
PROMPTS_DIR = APP_ROOT / "prompts"

_GOOD_SKILLS = {"categories": {"编程语言": ["Python"], "前端技术": ["Vue"]}}
_SKILLS_ENTRY = ("app/data/skills.json", "内置技能词典，岗位解析与匹配要用")


def write_skills(root: Path, payload: object) -> Path:
    path = root / "app/data/skills.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def focused_checklist(monkeypatch):
    """只检查技能词典一项，且不检查目录类资源。"""
    monkeypatch.setattr(preflight, "_REQUIRED_FILES", (_SKILLS_ENTRY,))
    monkeypatch.setattr(preflight, "_REQUIRED_DIRECTORIES", ())


def test_current_repository_passes_without_complaint():
    # 仓库里文件齐全时不能有任何误报，否则开发者每次导入都会看到这条错误。
    preflight.ensure_runtime_resources()


def test_missing_dictionary_names_the_file_and_what_to_do(tmp_path, monkeypatch, focused_checklist):
    monkeypatch.setattr(preflight, "_BACKEND_ROOT", tmp_path)

    with pytest.raises(RuntimeError) as error:
        preflight.ensure_runtime_resources()

    message = str(error.value)
    assert "缺少 backend/app/data/skills.json" in message
    assert "scripts\\Build-Release.ps1" in message
    assert "重新下载完整压缩包" in message


def test_dictionary_that_parses_to_a_list_is_reported(tmp_path, monkeypatch, focused_checklist):
    """真实反馈的另一半：包里的 skills.json 被换成了数组。

    原样放行的话，`_build_skill_matchers` 会抛
    ``TypeError: list indices must be integers or slices, not str``——同样看不出是包的问题。
    """
    write_skills(tmp_path, [])
    monkeypatch.setattr(preflight, "_BACKEND_ROOT", tmp_path)

    with pytest.raises(RuntimeError) as error:
        preflight.ensure_runtime_resources()

    assert "内容不可用" in str(error.value)
    assert "categories" in str(error.value)


@pytest.mark.parametrize(
    "skills",
    [
        {"categories": {}},  # 一个分类都没有
        {"categories": {"编程语言": []}},  # 空分类
        {"categories": ["Python"]},  # categories 不是对象
        {},  # 没有 categories
        "}{ 这不是 JSON",  # 读不出来
    ],
)
def test_every_broken_dictionary_shape_is_reported(tmp_path, monkeypatch, focused_checklist, skills):
    write_skills(tmp_path, skills)
    monkeypatch.setattr(preflight, "_BACKEND_ROOT", tmp_path)

    with pytest.raises(RuntimeError) as error:
        preflight.ensure_runtime_resources()

    assert "app/data/skills.json" in str(error.value)


def test_a_readable_dictionary_passes(tmp_path, monkeypatch, focused_checklist):
    write_skills(tmp_path, _GOOD_SKILLS)
    monkeypatch.setattr(preflight, "_BACKEND_ROOT", tmp_path)

    preflight.ensure_runtime_resources()


def test_missing_prompt_and_missing_migrations_are_reported_together(tmp_path, monkeypatch):
    """一次报全，而不是修一个再发现下一个。"""
    monkeypatch.setattr(
        preflight,
        "_REQUIRED_FILES",
        (_SKILLS_ENTRY, ("app/prompts/resume_generate_user.md", "简历生成用户提示词")),
    )
    monkeypatch.setattr(preflight, "_REQUIRED_DIRECTORIES", (("migrations/versions", "数据库迁移脚本"),))
    write_skills(tmp_path, _GOOD_SKILLS)
    (tmp_path / "migrations/versions").mkdir(parents=True)
    monkeypatch.setattr(preflight, "_BACKEND_ROOT", tmp_path)

    with pytest.raises(RuntimeError) as error:
        preflight.ensure_runtime_resources()

    message = str(error.value)
    assert "resume_generate_user.md" in message
    assert "backend/migrations/versions/*.py" in message


def test_every_prompt_loaded_by_code_is_covered_by_the_checklist():
    """代码里按文件名加载的提示词都要在清单里。

    清单漏一个不会立刻出错，但改名或漏打包时就少了那道提示；这条断言让两者不能各自漂移。
    """
    referenced: set[str] = set()
    for path in APP_ROOT.rglob("*.py"):
        referenced.update(re.findall(r'"([a-z_0-9]+\.md)"', path.read_text(encoding="utf-8")))
    covered = {Path(relative).name for relative, _ in preflight._REQUIRED_FILES}
    # 只留下真实存在于 prompts 目录里的名字：`skill_archive` 里的 "skill.md" 是用户导入
    # 技能包时约定的成员名，不是随包发送的提示词。
    bundled = referenced & {path.name for path in PROMPTS_DIR.glob("*.md")}

    assert bundled, "没有在代码里找到任何提示词引用，说明这条断言本身失效了"
    assert bundled <= covered, f"未纳入完整性检查的提示词：{sorted(bundled - covered)}"


def test_every_listed_resource_exists_in_this_repository():
    for relative, _ in preflight._REQUIRED_FILES:
        assert (BACKEND_ROOT / relative).is_file(), f"清单里的路径在仓库里不存在：{relative}"
    for relative, _ in preflight._REQUIRED_DIRECTORIES:
        assert list((BACKEND_ROOT / relative).glob("*.py")), relative


def test_prompt_files_in_the_repository_are_all_listed():
    """反向断言：仓库里的提示词都要在清单里，避免新增提示词被忘掉。"""
    listed = {Path(relative).name for relative, _ in preflight._REQUIRED_FILES}
    on_disk = {path.name for path in PROMPTS_DIR.glob("*.md")}

    assert on_disk <= listed, f"仓库里这些提示词没进完整性清单：{sorted(on_disk - listed)}"

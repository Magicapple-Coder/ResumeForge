"""发版脚本的纯逻辑测试。

脚本在仓库根的 `scripts/`（它管的是整个仓库的版本，不是后端自己的），所以这里要
手动把那个目录加进 import 路径。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from bump_version import (  # noqa: E402
    BumpError,
    bump_version,
    decide_bump,
    format_version,
    parse_version,
    render_changelog,
    replace_exact,
)


def test_parse_and_format_round_trip():
    assert parse_version("0.2.0") == (0, 2, 0)
    assert format_version((1, 10, 3)) == "1.10.3"


def test_parse_rejects_non_semver():
    with pytest.raises(BumpError, match="无法解析"):
        parse_version("v0.2")


@pytest.mark.parametrize(
    ("current", "level", "expected"),
    [
        ((0, 2, 0), "major", (1, 0, 0)),
        ((0, 2, 0), "minor", (0, 3, 0)),
        ((0, 2, 0), "patch", (0, 2, 1)),
        ((1, 4, 9), "minor", (1, 5, 0)),
    ],
)
def test_bump_version_resets_lower_parts(current, level, expected):
    assert bump_version(current, level) == expected


def test_feat_pushes_minor_and_fix_only_pushes_patch():
    level, _ = decide_bump([("fix: 修一个 bug", "")])
    assert level == "patch"

    level, _ = decide_bump([("fix: 修一个 bug", ""), ("feat: 加一个功能", "")])
    assert level == "minor"


def test_docs_and_chores_do_not_move_the_version():
    level, _ = decide_bump(
        [("docs: 补文档", ""), ("chore: 整理", ""), ("test: 加测试", ""), ("refactor: 拆模块", "")]
    )
    assert level == "none"


def test_breaking_change_marker_wins():
    level, reasons = decide_bump([("feat: 加功能", ""), ("feat!: 改了接口", "")])
    assert level == "major"
    assert "破坏性变更" in reasons[0]

    # body 里的 BREAKING CHANGE 同样算数（有些项目不用感叹号）
    level, _ = decide_bump([("refactor: 重整", "BREAKING CHANGE: 配置项改名了")])
    assert level == "major"


def test_unconventional_subjects_are_ignored():
    """历史上有若干不符合规范的提交，不能因为它们而误判幅度。"""
    level, _ = decide_bump([("1", ""), ("修改适配启动器", ""), ("功能调整", "")])
    assert level == "none"


def test_no_commits_mean_no_bump():
    level, reasons = decide_bump([])
    assert level == "none" and reasons == []


def test_render_changelog_moves_unreleased_into_a_dated_entry():
    text = (
        "# 变更记录\n\n## Unreleased\n\n### Added\n\n- 新功能\n\n## 0.2.0 - 2026-08-21\n\n- 旧内容\n"
    )

    rendered = render_changelog(text, "0.3.0", "2026-09-15")

    assert "## 0.3.0 - 2026-09-15" in rendered
    assert "- 新功能" in rendered
    assert "## 0.2.0 - 2026-08-21" in rendered
    # 顶部重新留出空的 Unreleased，供下个版本继续累积
    assert rendered.index("## Unreleased") < rendered.index("## 0.3.0")
    assert "- 新功能" not in rendered[: rendered.index("## 0.3.0")]
    # 新条目与上一个版本之间必须留着空行：标题紧贴上一段正文会被 Markdown 并进那一段
    assert "\n\n## 0.2.0 - 2026-08-21" in rendered


def test_render_changelog_refuses_an_empty_unreleased_section():
    """没有记录就不该产出一个空版本号。"""
    with pytest.raises(BumpError, match="没有可发布的改动记录"):
        render_changelog("# 变更记录\n\n## Unreleased\n\n## 0.2.0 - 2026-08-21\n", "0.3.0", "2026-09-15")


def test_render_changelog_refuses_a_template_left_by_the_previous_release():
    """上一次发版留下的空小节标题不是"内容"。

    曾经就是这样切出了一个 0.6.0：Unreleased 里只剩 `### Added / ### Fixed / ### Changed`
    三行标题，脚本把它们当成正文，于是产出一个没有任何条目的版本。
    """
    text = (
        "# 变更记录\n\n## Unreleased\n\n### Added\n\n### Fixed\n\n### Changed\n"
        "\n## 0.2.0 - 2026-08-21\n\n- 旧内容\n"
    )

    with pytest.raises(BumpError, match="没有可发布的改动记录"):
        render_changelog(text, "0.3.0", "2026-09-15")


def test_replace_exact_requires_a_single_match():
    assert replace_exact('a = "1"', r'^a = "[^"]+"', 'a = "2"', "x") == 'a = "2"'

    with pytest.raises(BumpError, match="期望匹配 1 处，实际 0 处"):
        replace_exact("b = 1", r'^a = "[^"]+"', "x", "x")

    with pytest.raises(BumpError, match="期望匹配 1 处，实际 2 处"):
        replace_exact('a = "1"\na = "1"', r'^a = "[^"]+"', "x", "x")


def test_replace_exact_expands_backreferences():
    """回归闸门：替换串里的 \\1 必须展开。

    曾经用 lambda 包过替换串，结果 re.sub 不展开函数返回值里的反向引用，
    于是字面量 `\\1` 被写进了 config.py。
    """
    text = '    app_version: str = "0.2.0"\n'
    rendered = replace_exact(
        text,
        r'^(\s*app_version:\s*str\s*=\s*)"[^"]+"',
        '\\1"0.3.0"',
        "config.py",
    )

    assert rendered == '    app_version: str = "0.3.0"\n'
    assert "\\1" not in rendered


def test_replace_exact_expands_named_backreferences():
    rendered = replace_exact(
        "当前版本：`0.2.0` ·",
        r"(当前版本：`)[^`]+(`)",
        "\\g<1>0.3.0\\g<2>",
        "README.md",
    )

    assert rendered == "当前版本：`0.3.0` ·"
    assert "\\g<" not in rendered

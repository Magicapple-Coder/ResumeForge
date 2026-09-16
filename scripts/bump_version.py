"""按改动幅度更新版本号。

用法（在仓库根目录执行）：

    python scripts/bump_version.py --dry-run    # 只打印计划，不改任何文件
    python scripts/bump_version.py              # 按提交类型自动判定并写入
    python scripts/bump_version.py --bump major # 显式指定幅度

判定依据是**自最后一个 v* 标签以来**的提交，按 Conventional Commits 归类：
带 `!` 或 `BREAKING CHANGE` 的提交算 major，`feat` 算 minor，`fix` 算 patch，
其余（docs/chore/test/refactor/style/ci）不推动版本号。

**本仓库目前没有任何 BREAKING 标记**，所以自动判定实际只能产出 minor/patch。
需要 major 时请显式传 `--bump major`；脚本检测到新增的 Alembic migration 时会提示
你复核，但不会替你猜。

脚本只改文件，**不会 commit、不会打 tag**——项目规则要求提交与推送由用户发起，
所以结束时它会打印出你需要手动执行的命令。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# 中文 Windows 的控制台编码是 cp936，打印 "⚠" 这类符号会直接抛 UnicodeEncodeError：
# 幅度都判定完了却因为一行提示崩掉。保留控制台原有编码（中文在 cmd 里仍要能看），
# 只把无法编码的字符降级成问号。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PY = REPO_ROOT / "backend" / "app" / "config.py"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
PACKAGE_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
MIGRATIONS_DIR = REPO_ROOT / "backend" / "migrations" / "versions"

# 提交记录的分隔符：\x1e 分记录、\x1f 分字段，正文里的换行不会干扰解析。
_RECORD = "\x1e"
_FIELD = "\x1f"
# "feat(scope)!:" / "fix!:" —— 感叹号表示破坏性变更。
_BREAKING_SUBJECT = re.compile(r"^[a-zA-Z]+(\([^)]*\))?!:")

UNRELEASED_HEADING = "## Unreleased"
EMPTY_UNRELEASED = "## Unreleased\n\n### Added\n\n### Fixed\n\n### Changed\n"


class BumpError(Exception):
    """面向使用者的错误，消息可直接打印。"""


def parse_version(text: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    if match is None:
        raise BumpError(f"无法解析版本号：{text!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def format_version(parts: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in parts)


def bump_version(parts: tuple[int, int, int], level: str) -> tuple[int, int, int]:
    major, minor, patch = parts
    if level == "major":
        return (major + 1, 0, 0)
    if level == "minor":
        return (major, minor + 1, 0)
    if level == "patch":
        return (major, minor, patch + 1)
    raise BumpError(f"未知的幅度：{level}")


def _commit_kind(subject: str) -> str:
    match = re.match(r"^([a-zA-Z]+)(\([^)]*\))?!?:", subject)
    return match.group(1).lower() if match else ""


def decide_bump(commits: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """按提交类型判定幅度，返回 (级别, 推理说明)。

    级别为 "none" 表示这些提交都不推动版本号。
    """
    level = "none"
    reasons: list[str] = []
    for subject, body in commits:
        if _BREAKING_SUBJECT.match(subject) or "BREAKING CHANGE" in body:
            return "major", [f"{subject}（含破坏性变更标记）"]
        kind = _commit_kind(subject)
        if kind == "feat" and level != "minor":
            level = "minor"
            reasons.append(f"{subject}（feat → minor）")
        elif kind == "fix" and level == "none":
            level = "patch"
            reasons.append(f"{subject}（fix → patch）")
    return level, reasons


def render_changelog(text: str, version: str, released_on: str) -> str:
    """把 Unreleased 的内容转到新版本条目下，并留一个空的 Unreleased 给下次。"""
    start = text.find(UNRELEASED_HEADING)
    if start < 0:
        raise BumpError("CHANGELOG 里找不到 `## Unreleased` 段落")
    body_start = start + len(UNRELEASED_HEADING)
    next_heading = text.find("\n## ", body_start)
    body_end = len(text) if next_heading < 0 else next_heading + 1
    body = text[body_start:body_end].strip("\n")
    if not body.strip():
        raise BumpError("CHANGELOG 的 Unreleased 段落是空的，没有可发布的改动记录")
    released = f"## {version} - {released_on}\n\n{body}\n"
    return text[:start] + EMPTY_UNRELEASED + "\n" + released + text[body_end:]


def replace_exact(text: str, pattern: str, replacement: str, label: str) -> str:
    """精确替换恰好一处；匹配数不是 1 就报错（宁可停下，也不要改错地方）。

    replacement 直接交给 ``re.sub``，其中 ``\\1`` / ``\\g<1>`` 会照常展开。注意不能
    改成传函数——函数的返回值不会被展开，反向引用会被原样写进文件。
    """
    matches = re.findall(pattern, text, flags=re.MULTILINE)
    if len(matches) != 1:
        raise BumpError(f"{label}：期望匹配 1 处，实际 {len(matches)} 处")
    return re.sub(pattern, replacement, text, count=1, flags=re.MULTILINE)


def _run_git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise BumpError(f"git {' '.join(arguments)} 失败：{result.stderr.strip()}")
    return result.stdout


def latest_tag() -> str | None:
    tags = _run_git("tag", "--list", "v*", "--sort=-v:refname").splitlines()
    return tags[0].strip() if tags else None


def commits_since(tag: str | None) -> list[tuple[str, str]]:
    revision = f"{tag}..HEAD" if tag else "HEAD"
    raw = _run_git("log", f"--format=%s{_FIELD}%b{_RECORD}", revision)
    commits: list[tuple[str, str]] = []
    for record in raw.split(_RECORD):
        record = record.strip("\n")
        if not record:
            continue
        subject, _, body = record.partition(_FIELD)
        commits.append((subject.strip(), body.strip()))
    return commits


def read_versions() -> tuple[str, str, str]:
    """返回 (config.py 里的版本, package.json 里的版本, README 里声明的版本)。"""
    config_match = re.search(r'app_version:\s*str\s*=\s*"([^"]+)"', CONFIG_PY.read_text("utf-8"))
    package_version = json.loads(PACKAGE_JSON.read_text("utf-8"))["version"]
    readme_match = re.search(r"当前版本：`([^`]+)`", README.read_text("utf-8"))
    if config_match is None or readme_match is None:
        raise BumpError("找不到 config.py 或 README 里的版本号")
    return config_match.group(1), package_version, readme_match.group(1)


def new_migration_files(tag: str | None) -> list[str]:
    revision = f"{tag}..HEAD" if tag else "HEAD"
    try:
        changed = _run_git("diff", "--name-only", revision, "--", str(MIGRATIONS_DIR)).splitlines()
    except BumpError:
        return []
    return [name for name in changed if name.endswith(".py")]


def apply_version(new_version: str, released_on: str) -> list[str]:
    """写入全部版本号位置，返回被改动的文件清单（相对仓库根）。"""
    touched: list[str] = []

    config_text = CONFIG_PY.read_text("utf-8")
    updated = replace_exact(
        config_text,
        r'^(\s*app_version:\s*str\s*=\s*)"[^"]+"',
        f'\\1"{new_version}"',
        "backend/app/config.py",
    )
    CONFIG_PY.write_text(updated, encoding="utf-8", newline="\n")
    touched.append(str(CONFIG_PY.relative_to(REPO_ROOT)))

    package_text = PACKAGE_JSON.read_text("utf-8")
    updated = replace_exact(
        package_text,
        r'^(\s*"version":\s*)"[^"]+"',
        f'\\1"{new_version}"',
        "frontend/package.json",
    )
    PACKAGE_JSON.write_text(updated, encoding="utf-8", newline="\n")
    touched.append(str(PACKAGE_JSON.relative_to(REPO_ROOT)))

    # lockfile 里还有大量依赖自身的 "version" 字段，所以按结构改而不是按行改：
    # 只动根包与 packages[""] 两处。
    lock = json.loads(PACKAGE_LOCK.read_text("utf-8"))
    lock["version"] = new_version
    lock["packages"][""]["version"] = new_version
    PACKAGE_LOCK.write_text(
        json.dumps(lock, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    touched.append(str(PACKAGE_LOCK.relative_to(REPO_ROOT)))

    readme_text = README.read_text("utf-8")
    updated = replace_exact(
        readme_text,
        r"(当前版本：`)[^`]+(`)",
        f"\\g<1>{new_version}\\g<2>",
        "README.md",
    )
    README.write_text(updated, encoding="utf-8", newline="\n")
    touched.append(str(README.relative_to(REPO_ROOT)))

    changelog_text = CHANGELOG.read_text("utf-8")
    CHANGELOG.write_text(
        render_changelog(changelog_text, new_version, released_on),
        encoding="utf-8",
        newline="\n",
    )
    touched.append(str(CHANGELOG.relative_to(REPO_ROOT)))

    return touched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="按改动幅度更新版本号")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不写入文件")
    parser.add_argument(
        "--bump",
        choices=["auto", "major", "minor", "patch"],
        default="auto",
        help="显式指定幅度；默认按提交类型自动判定",
    )
    arguments = parser.parse_args(argv)

    try:
        tag = latest_tag()
        current, package_version, readme_version = read_versions()
        print(f"最后一个发布标签：{tag or '（无）'}")
        print(f"当前版本：config.py={current} package.json={package_version} README={readme_version}")
        if len({current, package_version, readme_version}) != 1:
            print("⚠ 三处版本号已经不一致，请先人工核对再继续。", file=sys.stderr)
            return 1

        commits = commits_since(tag)
        print(f"自该标签以来的提交：{len(commits)} 条")
        level, reasons = decide_bump(commits)
        if arguments.bump != "auto":
            print(f"幅度由 --bump 指定为 {arguments.bump}（自动判定为 {level}）")
            level = arguments.bump
        else:
            for reason in reasons:
                print(f"  · {reason}")

        if level == "none":
            print("没有需要推动版本号的提交（feat/fix/破坏性变更），未做任何改动。")
            return 0

        new_version = format_version(bump_version(parse_version(current), level))
        print(f"判定幅度：{level}  →  {current} → {new_version}")

        migrations = new_migration_files(tag)
        if migrations:
            print(
                f"⚠ 本次包含 {len(migrations)} 个新增数据库迁移：{', '.join(migrations)}\n"
                "  请复核是否属于破坏性变更；若是，请改用 --bump major 重新运行。"
            )

        if arguments.dry_run:
            print("\n--dry-run：以下文件会被改动，但本次没有写入。")
            for path in (
                CONFIG_PY,
                PACKAGE_JSON,
                PACKAGE_LOCK,
                README,
                CHANGELOG,
            ):
                print(f"  · {path.relative_to(REPO_ROOT)}")
            return 0

        touched = apply_version(new_version, date.today().isoformat())
        print("\n已更新：")
        for path in touched:
            print(f"  · {path}")
        print(
            "\n接下来请人工核对 diff 后自行提交与打标签（脚本不会替你 commit）：\n"
            f'  git add -A && git commit -m "release: prepare v{new_version}"\n'
            f'  git tag -a v{new_version} -m "ResumeForge v{new_version}"\n'
            f"  git push origin main --follow-tags"
        )
        return 0
    except BumpError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

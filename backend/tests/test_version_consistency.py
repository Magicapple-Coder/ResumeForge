"""版本号一致性：两处真实来源必须相同。

前端界面不显示版本，所以不一致不会在界面上暴露，只会出现在 README、Releases 页、
`/api/health` 和备份 manifest 四处。这条测试让"发版时改漏一处"在 CI 上立刻失败。
"""
import json
from pathlib import Path

from app.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
PACKAGE_LOCK = REPO_ROOT / "frontend" / "package-lock.json"
README = REPO_ROOT / "README.md"


def test_backend_and_frontend_versions_match():
    package_version = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]

    assert get_settings().app_version == package_version


def test_lockfile_root_version_matches_package_json():
    """lockfile 的根包版本由 npm 写入，发版时必须与 package.json 同步。"""
    package_version = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))

    assert lock["version"] == package_version
    assert lock["packages"][""]["version"] == package_version


def test_readme_states_the_current_version():
    package_version = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"]

    assert f"当前版本：`{package_version}`" in README.read_text(encoding="utf-8")

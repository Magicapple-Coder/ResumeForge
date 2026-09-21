"""守卫：`frontend/src` 下同一目录不允许出现**仅大小写不同**的文件名。

为什么值得一条测试守：Windows 文件系统大小写不敏感，于是"只差大小写"的两个模块会互相遮蔽，
而且失败方式极不一致、极难定位：

- TypeScript 报 `TS1149`（"只差大小写"），并声称找不到组件导出；
- Vite 解析 `./Foo` 时按 ``resolve.extensions`` 先试 ``.ts``，于是 ``Foo.tsx`` 被 ``foo.ts``
  顶掉；更糟的是它**会缓存这个解析结果**——把 ``foo.ts`` 改名或删除之后，正在运行的 dev server
  仍去请求那个已不存在的路径，懒加载的页面拿不到代码，用户看到的是与模块毫无关系的
  「页面暂时无法显示」，而且**刷新页面永远无效**（要重启 dev server）。

实测踩过：新建 ``components/common/recordDetail.ts`` 与既有 ``RecordDetail.tsx`` 只差大小写，
结果投递台、内推、面经、提醒、资料箱、知识库六个页面一起白屏。

放在后端测试里而不是前端：前端 tsconfig 不含 ``@types/node``，读不到 ``node:fs``；而本项目已有
"用后端测试守前端文件"的先例（``test_assistant_knowledge_audit.py`` 守 MENU_ITEMS 与
userGuideSteps 的一致性）。
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _duplicate_stems() -> list[str]:
    """返回所有"同一目录内归一小写后重名"的文件组，形如 ``组件目录/ 下的 A 与 B``。"""
    by_dir: dict[Path, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path in FRONTEND_SRC.rglob("*"):
        if not path.is_file():
            continue
        # 只比"文件名去掉最后一个扩展名"的部分：`RecordDetail.tsx` 与 `recordDetail.ts`
        # 正是靠扩展名不同才得以在 Windows 上共存，也正因如此才会互相遮蔽。
        by_dir[path.parent][path.stem.lower()].append(path.name)

    conflicts: list[str] = []
    for directory, groups in sorted(by_dir.items()):
        relative = directory.relative_to(FRONTEND_SRC)
        label = "src" if str(relative) == "." else f"src/{relative.as_posix()}"
        for stem, names in sorted(groups.items()):
            if len(names) > 1:
                conflicts.append(f"{label}/ 下的 {' 与 '.join(sorted(names))}（都归一为 {stem}）")
    return conflicts


def test_frontend_src_has_no_case_only_duplicate_file_names():
    assert FRONTEND_SRC.is_dir(), f"找不到前端源码目录：{FRONTEND_SRC}"

    conflicts = _duplicate_stems()

    assert conflicts == [], (
        "frontend/src 里出现了仅大小写不同的文件名，在 Windows 上它们会互相遮蔽："
        "TS 会报 TS1149，而 Vite 会先命中 .ts 并**缓存这个解析**——改名或删除之后，"
        "正在运行的 dev server 仍请求旧路径，页面会白屏成「页面暂时无法显示」，刷新无效。"
        "请把其中一个改成**不同的词**（例如 RowActions.tsx + rowActionMenu.ts）。"
        f"当前冲突：{conflicts}"
    )

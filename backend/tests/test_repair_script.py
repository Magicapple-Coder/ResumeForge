"""修复脚本的字段映射规则。

脚本本身是"就地改用户数据"的工具，所以它最容易犯的错不是解析错，而是**把用户已经改好的值
覆盖掉**（比如他自己补过的薪资、或者在详情页整理过的「任职要求」）。这里把"只在为空时补齐"
这条规则钉死。

脚本在 `scripts/` 下（不在 `backend` 包内），所以按文件路径加载。
"""
import importlib.util
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "repair_collected_job_text.py"


def _load():
    spec = importlib.util.spec_from_file_location("repair_collected_job_text", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _row(**overrides) -> dict:
    base = {
        "title": "全栈工程师\ue032\ue033-\ue032\ue036K",
        "company": "天津云际",
        "location": "天津·西青区·侯台",
        "salary": "",
        "description": (
            "教育背景：本boss科在校生。"
            "岗位职责：负责前后端开发与系统设计，参与需求评审并把方案落地。"
            "任职要求：1、三年以上全栈经验。"
        ),
        "requirements": "",
    }
    return {**base, **overrides}


def test_repair_restores_title_salary_and_split_sections():
    repaired = _load()._repair(_row())

    assert repaired["title"] == "全栈工程师"
    assert repaired["salary"] == "23-26K"
    assert "boss" not in repaired["description"]
    assert repaired["description"].startswith("教育背景：本科在校生")
    assert "任职要求" not in repaired["description"]
    assert repaired["requirements"].startswith("任职要求")


def test_repair_is_idempotent():
    repair = _load()._repair
    once = repair(_row())
    twice = repair({**_row(), **once})

    assert twice == once


def test_repair_never_overwrites_values_the_user_already_fixed():
    """原本非空的薪资 / 任职要求**一律保留**——那是用户的劳动成果。"""
    repaired = _load()._repair(
        _row(salary="23-26K", requirements="我手动整理过的要求")
    )

    assert repaired["salary"] == "23-26K"
    assert repaired["requirements"] == "我手动整理过的要求"


def test_repair_leaves_an_already_clean_row_untouched():
    clean = {
        "title": "全栈工程师",
        "company": "天津云际",
        "location": "天津·西青区·侯台",
        "salary": "23-26K",
        "description": "岗位职责：负责前后端开发与系统设计，参与需求评审并把方案落地执行。",
        "requirements": "",
    }
    assert _load()._changed(clean, _load()._repair(clean)) == []

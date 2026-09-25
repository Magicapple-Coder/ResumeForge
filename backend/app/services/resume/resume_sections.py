"""简历正文的分区（板块）定义与顺序。

**为什么要有这个模块**：正文的七个分区在四处独立渲染——HTML 模板（预览、HTML 导出、
浏览器打印）、服务端 PDF、Word、Markdown。顺序一旦被写死在四处，用户改了一处看到的效果
就只对那一处生效，另外三处会**悄悄地**保持旧顺序——而"导出的和预览的不一样"是那种
用户会怀疑整个工具的问题。所以顺序在这里定义一次，四个渲染器都从这里取。

存储位置：简历的 `format_config`（按简历的版式覆盖）里的 `section_order`。
放在版式配置里而不是新增数据库列，是因为它本来就是"内容怎么排"的一部分，而且
`format_config` 已经是按简历存的一份 JSON 覆盖，不需要迁移。

一条刻意的约束：**存下来的顺序永远是七个键的一个完整排列**（`normalized_section_order`
负责补齐）。这样渲染器不必处理"某个分区不在列表里"这种状态——那种状态只有一种解释
（忘记写了），而它的表现是"某个板块凭空消失"，是最难被发现的一类 bug。
"""

from __future__ import annotations

# 默认顺序 = 内置模板沿用至今的顺序。**不要**因为「我的资料」那边改了默认顺序就顺手改这里：
# 简历是有历史记录的产物，改默认顺序等于把用户已经导出过的简历悄悄换了一个样子。
DEFAULT_SECTION_ORDER: tuple[str, ...] = (
    "summary",
    "education",
    "experience",
    "campus_experience",
    "projects",
    "skills",
    "awards",
)

SECTION_LABELS: dict[str, str] = {
    "summary": "个人总结",
    "education": "教育经历",
    "experience": "实习/工作经历",
    "campus_experience": "校园经历",
    "projects": "项目经历",
    "skills": "专业技能",
    "awards": "荣誉奖项",
}

# 页眉（姓名 / 求职意向 / 联系方式 / 照片）不在可排序的七个分区里，它永远在最前面。
# 这里显式写下来，是为了让"为什么列表里没有它"这个问题有一个能搜到的答案。


def section_label(key: str) -> str:
    return SECTION_LABELS.get(key, key)


def normalized_section_order(raw: object) -> list[str]:
    """把任意输入归一化成"七个键齐全、无重复、只含已知键"的顺序。

    未出现在输入里的键按默认顺序补在后面：用户只调了前两项，不应该让其余五项消失。
    """
    if isinstance(raw, (list, tuple)):
        candidates = raw
    elif isinstance(raw, str):
        # 查询串里传过 "summary,education" 这种写法；按逗号拆开照样认。
        candidates = raw.split(",")
    else:
        return list(DEFAULT_SECTION_ORDER)

    ordered: list[str] = []
    for item in candidates:
        key = str(item).strip()
        if key in SECTION_LABELS and key not in ordered:
            ordered.append(key)
    for key in DEFAULT_SECTION_ORDER:
        if key not in ordered:
            ordered.append(key)
    return ordered


def resolved_section_order(format_config: dict | None) -> list[str]:
    """从版式覆盖里取分区顺序；没设过就用默认顺序。"""
    if not isinstance(format_config, dict):
        return list(DEFAULT_SECTION_ORDER)
    if "section_order" not in format_config:
        return list(DEFAULT_SECTION_ORDER)
    return normalized_section_order(format_config.get("section_order"))


__all__ = [
    "DEFAULT_SECTION_ORDER",
    "SECTION_LABELS",
    "normalized_section_order",
    "resolved_section_order",
    "section_label",
]

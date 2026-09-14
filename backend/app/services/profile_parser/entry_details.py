"""经历条目中的课程、描述、亮点等细节分组。"""

import re

from .normalization import _clean_line
from .skill_fields import _split_tokens


def _detail_groups(lines: list[str]) -> tuple[list[str], list[str], list[str], str, str, str]:
    description: list[str] = []
    highlights: list[str] = []
    tech_stack: list[str] = []
    courses: list[str] = []
    achievements: list[str] = []
    gpa = ""
    active = description
    for raw_line in lines:
        line = _clean_line(raw_line)
        if not line:
            continue
        match = re.match(r"^([^：:]{1,32})\s*[:：]\s*(.+)$", line)
        if match:
            label = match.group(1).strip().lower()
            value = match.group(2).strip()
            if any(
                term in label
                for term in (
                    "技术栈",
                    "技术",
                    "工具",
                    "技术方案",
                    "tech stack",
                    "technical stack",
                    "tech skills",
                    "technologies",
                    "tools",
                )
            ):
                tech_stack.extend(_split_tokens(value))
                continue
            if any(
                term in label
                for term in (
                    "亮点",
                    "成果",
                    "结果",
                    "业绩",
                    "highlights",
                    "achievements",
                    "results",
                )
            ):
                active = highlights
                highlights.append(value)
                continue
            if any(term in label for term in ("课程", "核心课", "courses", "coursework")):
                courses.extend(_split_tokens(value))
                continue
            if any(term in label for term in ("绩点", "排名", "成绩", "gpa", "rank", "grade")):
                gpa = value
                continue
            if any(term in label for term in ("奖项", "荣誉", "award", "honor")):
                achievements.append(value)
                continue
            if any(
                term in label
                for term in (
                    "描述",
                    "职责",
                    "工作内容",
                    "项目内容",
                    "description",
                    "responsibilities",
                    "duties",
                    "content",
                )
            ):
                active = description
                description.append(value)
                continue
        active.append(line)
    return description, highlights, tech_stack, "、".join(courses), "\n".join(achievements), gpa

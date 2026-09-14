"""资料分区切换和连续无标题条目的推断。"""

import re

from .entry_blocks import _is_header_metadata_line
from .entry_constants import (
    _BASIC_ENGLISH_NAME_RE,
    _BASIC_NAME_RE,
    _DATE_RANGE_RE,
    _ENGLISH_COMPANY_HINT_RE,
)
from .entry_inference import _looks_like_profile_role_line
from .normalization import _clean_line, _starts_with_field


def _infer_section_from_unlabeled_sequence(
    lines: list[str], index: int
) -> tuple[str, tuple[int, int]] | None:
    """从“组织/公司 + 角色 + 独立日期”三行结构补齐缺失分区标题。"""
    date_line = _clean_line(lines[index])
    if _DATE_RANGE_RE.fullmatch(date_line) is None:
        return None

    previous_indices = [
        previous_index
        for previous_index in range(index - 1, -1, -1)
        if _clean_line(lines[previous_index])
    ][:2]
    if len(previous_indices) != 2:
        return None
    role_index, subject_index = previous_indices
    role = _clean_line(lines[role_index])
    subject = _clean_line(lines[subject_index])
    if not _looks_like_profile_role_line(role):
        return None
    if (
        len(subject) > 96
        or (
            _BASIC_NAME_RE.fullmatch(subject)
            and not re.search(r"公司|集团|科技|工作室|银行|研究院|事务所|企业", subject)
        )
        # 两词英文公司名（如 ``Example Technology``）与英文人名形态相同。
        # 仅在缺少公司后缀/行业词时继续按人名处理，避免无标题英文经历整体丢失。
        or (
            _BASIC_ENGLISH_NAME_RE.fullmatch(subject)
            and _ENGLISH_COMPANY_HINT_RE.search(subject) is None
        )
        or _is_header_metadata_line(subject)
        or re.search(r"[。！？!?]", subject)
    ):
        return None

    context = f"{subject}\n{role}"
    if re.search(
        r"学生会|团委|团支部|团支书|社团|Student\s+Union|Campus|Club|"
        r"Student\s+Association|校内",
        context,
        re.IGNORECASE,
    ):
        return "campus_experiences", (subject_index, role_index)
    if re.search(r"项目|平台|系统|应用|小程序|Project|App|Platform|System", subject, re.IGNORECASE):
        return "projects", (subject_index, role_index)
    if re.search(
        r"大学|学院|University|College|本科|硕士|博士|Bachelor|Master", context, re.IGNORECASE
    ):
        return "educations", (subject_index, role_index)
    return "experiences", (subject_index, role_index)


def _starts_explicit_section_transition(line: str, section: str) -> bool:
    """判断显式分区后的强字段是否足以开始另一个分区。

    已有分区标题时，普通日期、角色和技能词的证据不足以切换分区；但
    ``项目名称：``、``公司：`` 这类唯一字段通常表示用户省略了下一个
    标题，应该优先恢复为新的结构化记录。
    """
    labels_by_section = {
        "educations": (
            "学校",
            "院校",
            "学校名称",
            "school",
            "university",
            "college",
        ),
        "experiences": (
            "公司",
            "公司名称",
            "企业",
            "企业名称",
            "就职公司",
            "所在公司",
            "单位",
            "雇主",
            "company",
            "enterprise",
            "employer",
        ),
        "campus_experiences": (
            "组织",
            "组织名称",
            "社团",
            "社团名称",
            "学生组织",
            "所在组织",
            "学生会",
            "团委",
            "organization",
            "organization name",
            "student union",
            "club",
        ),
        "projects": ("项目名称", "项目标题", "project name"),
        "skills": (
            "专业技能",
            "技能清单",
            "技能特长",
            "skills",
            "technical skills",
            "programming languages",
        ),
    }
    return _starts_with_field(line, labels_by_section.get(section, ()))


def _is_context_detail_field(line: str, section: str) -> bool:
    """判断无标题分区中仍属于当前条目的通用字段。"""
    shared_entry_labels = (
        "角色",
        "担任角色",
        "职位",
        "岗位",
        "职务",
        "role",
        "position",
        "position name",
        "work position",
        "job position",
        "job title",
        "period",
        "时间",
        "周期",
        "duration",
        "description",
        "描述",
        "responsibilities",
        "职责",
        "工作内容",
        "工作描述",
        "work content",
        "employment",
        "employment dates",
        "employment date",
        "work dates",
        "work date",
        "job dates",
        "study period",
        "study dates",
        "入职时间",
        "入职日期",
        "就业时间",
        "就职时间",
        "参与时间",
        "参与日期",
        "任职日期",
    )
    labels_by_section = {
        "educations": (
            "专业",
            "所学专业",
            "学历",
            "学位",
            "核心课程",
            "课程",
            "major",
            "degree",
            "courses",
            "time",
            "period",
        ),
        "experiences": shared_entry_labels + ("任职时间", "任职期间", "工作内容"),
        "campus_experiences": shared_entry_labels
        + ("校园活动", "活动内容", "参与时间", "参与日期"),
        "projects": shared_entry_labels
        + ("项目周期", "项目时间", "项目描述", "项目内容", "项目成果", "亮点"),
    }
    return _starts_with_field(line, labels_by_section.get(section, ()))

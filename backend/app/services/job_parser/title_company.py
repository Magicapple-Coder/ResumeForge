"""岗位标题与公司名称的组合识别。"""

from .candidates import (
    _discard_location_as_company,
    _looks_like_company_candidate,
    _looks_like_title,
    _prepare_title_candidate,
    _split_title_company,
)
from .section_constants import _ADDITIONAL_HEADING_RE, _JOB_ID_RE


def _extract_title_and_company(
    lines: list[str], values: dict[str, str], consumed: set[int], preamble_end: int
) -> tuple[str, str]:
    title_value, leading_location = _prepare_title_candidate(values.get("title", ""))
    if leading_location:
        values.setdefault("location", leading_location)
    company = values.get("company", "")
    if title_value:
        # 明确标注的职位与公司比标题分隔符启发式更可靠。岗位方向常写成
        # ``工程师 - 数据平台``，此时再拆分会把方向误当成公司名称。
        if company:
            return title_value, company
        title, inline_company = _split_title_company(title_value)
        return title, company or _discard_location_as_company(inline_company)

    for index, line in enumerate(lines[:preamble_end]):
        if index in consumed or _JOB_ID_RE.match(line) or _ADDITIONAL_HEADING_RE.match(line):
            continue
        title_candidate, leading_location = _prepare_title_candidate(line)
        if _looks_like_title(title_candidate):
            if leading_location:
                values.setdefault("location", leading_location)
            consumed.add(index)
            title, inline_company = _split_title_company(title_candidate)
            if not company and not inline_company:
                # 不同官网会把公司放在职位上方、下方，甚至使用没有“科技/有限公司”
                # 后缀的品牌名（如 Acme）。只检查紧邻行并排除地点、部门和元信息，
                # 避免把正文中的任意短句提升为公司。
                neighboring_indices = (index - 1, index + 1)
                for neighbor_index in neighboring_indices:
                    if neighbor_index < 0 or neighbor_index >= preamble_end:
                        continue
                    if neighbor_index in consumed:
                        continue
                    neighbor = lines[neighbor_index]
                    if _looks_like_company_candidate(neighbor):
                        company = neighbor.strip()
                        consumed.add(neighbor_index)
                        break
            return title, company or _discard_location_as_company(inline_company)
    return "", company

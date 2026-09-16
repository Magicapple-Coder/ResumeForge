"""简历生成兼容门面与流式生成编排。

模型输出解析、事实回填、一致性检查和质量门槛分别位于职责模块；本文件只
保留原有公共入口，并负责把各步骤编排为 API 使用的异步事件流。
"""

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..schemas.job import JobOut
from ..schemas.profile import ProfileOut
from ..schemas.resume import GenerateOptions, ResumeContent
from .llm.base import BaseLLMProvider, LLMError
from .profile_relevance import (
    build_general_profile_context,
    build_job_prompt_text,
    build_profile_prompt_data,
    build_targeted_profile_context,
    split_commas,
    split_lines,
)
from .resume_consistency import check_consistency
from .resume_content import _LIST_FIELDS
from .resume_content import coerce_resume, extract_json
from .resume_grounding import (
    _REFERENCE_FALLBACK_LIMITS,
    _build_grounded_summary,
    _enhance_or_restore_list,
    _find_source,
    _ground_list,
    _ground_or_restore_list,
    _normalize_fact,
    _selected_data_with_reference_fallbacks,
    _similar,
    _similar_skill,
    _source_evidence_text,
    _source_list,
    _source_value,
    _unsupported_quantified_values,
    ground_resume_facts,
    restore_selected_sections,
)
from .resume_quality import (
    _quality_generated_points,
    _quality_reference_points,
    _quality_shortfalls,
)
from .resume_templates import font_scale_spec
from .resume_wording import cliche_shortfalls, find_cliches

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
logger = logging.getLogger(__name__)

# 控制总输入体积：先筛选资料，再为 JD 保留独立预算，避免超长资料/JD 挤掉彼此。
MAX_JD_CHARS = 5_000
MAX_PROFILE_CHARS = 9_000

# 三档只控制对描述性字段的改写幅度；结构化事实始终由代码强制锚定。
ENHANCEMENT_LEVEL_GUIDES = {
    "light": (
        "轻度美化：只优化语序、动词和专业表达，保持原有要点数量与职责边界；"
        "每条内容应能直接对应原资料或参考事实。原描述为空但存在 reference_facts 时，"
        "提炼 1-2 条最相关事实，不能继续留空。"
    ),
    "balanced": (
        "均衡美化：可围绕 JD 重组原有事实，补足动作、方法和业务目的，使表达更扎实；"
        "允许合并同一条目内的相关证据，但不得推导未明确提供的结果。含 reference_facts "
        "的相关条目在可用事实达到 2 条时，应将 description/highlights 合计写成 2-4 条。"
    ),
    "strong": (
        "深度美化：充分挖掘同一条目及 reference_facts/reference_excerpt 中的岗位相关证据，"
        "以专业简历语言展开技术决策、实施过程和价值，可以增加描述要点。存在至少 3 条 "
        "reference_facts 时，必须将 description/highlights 合计写成 3-5 条；不足 3 条时全部"
        "使用，不得为凑数虚构。每个事实都必须能追溯到该条目来源。"
    ),
}

_ENHANCEMENT_DISABLED_GUIDE = (
    "美化拓展已关闭：只能选择、排序并精确回填候选资料中的原文要点；"
    "不得合并、改写或扩充 description、highlights 和 summary。"
)

# 单页 A4 在不同字号下的汉字预算（含标题、联系方式等全部版面文字）。
# 数字是经验值，只用来给模型一个明确的篇幅目标，不参与任何校验。
_PAGE_CHAR_BUDGET = {
    "small": (850, 1100),
    "standard": (650, 880),
    "large": (550, 720),
}


def build_layout_guide(page_limit: int, font_scale: str) -> str:
    """把「页数 + 字号」翻译成模型可执行的篇幅要求。"""
    spec = font_scale_spec(font_scale)
    low, high = _PAGE_CHAR_BUDGET.get(spec["name"], _PAGE_CHAR_BUDGET["standard"])
    if page_limit <= 1:
        return (
            f"目标篇幅：1 页 A4、{spec['label']}。整份简历（含联系方式与全部文字）"
            f"控制在 {low}-{high} 个汉字以内：每段经历保留 2-3 条最相关的要点，"
            "每条要点 25-35 字，个人总结不超过 100 字。宁可少写，也不要为了完整而超出篇幅。"
        )
    total_low = low * page_limit
    total_high = high * page_limit
    return (
        f"目标篇幅：最多 {page_limit} 页 A4、{spec['label']}。整份简历控制在 "
        f"{total_low}-{total_high} 个汉字以内：优先写满第一页，确有必要再用第二页；"
        "不要为了填满页数而堆砌次要内容，也不要留下大半页空白。"
    )


class ResumeGenerator:
    """简历生成器：一次生成 = 一条事件流。"""

    def __init__(self, provider: BaseLLMProvider):
        self.provider = provider
        # StrictUndefined：模板变量缺失时立即报错，而不是静默渲染成空。
        self._env = Environment(
            loader=FileSystemLoader(PROMPTS_DIR),
            undefined=StrictUndefined,
            autoescape=False,
        )

    async def generate(
        self, profile: ProfileOut, job: JobOut | None, options: GenerateOptions
    ) -> AsyncIterator[dict]:
        """执行生成流程，依次产出进度、增量、完成或错误事件。

        ``job is None`` 表示**通用简历**：不针对任何岗位，候选资料是完整资料库，
        筛选层换成 ``build_general_profile_context``（见那里的说明——不能靠"传空岗位"
        让岗位路径自己退化，那条路径会丢掉校园经历、奖项、技能与总结）。
        """
        general = job is None
        enhancement_guide = (
            ENHANCEMENT_LEVEL_GUIDES[options.enhancement_level]
            if options.enhance
            else _ENHANCEMENT_DISABLED_GUIDE
        )

        yield {
            "type": "progress",
            "message": "正在整理完整资料…" if general else "正在分析岗位要求与资料匹配度…",
        }
        selection = (
            build_general_profile_context(
                profile, max_chars=MAX_PROFILE_CHARS, include_references=options.enhance
            )
            if general
            else build_targeted_profile_context(
                profile,
                job,
                max_chars=MAX_PROFILE_CHARS,
                include_references=options.enhance,
            )
        )
        counts = selection.selected_counts
        reference_count = sum(
            1
            for section in ("educations", "experiences", "campus_experiences", "projects")
            for item in selection.data.get(section, [])
            if item.get("reference_facts") or item.get("reference_excerpt")
        )
        if general:
            reference_message = (
                f"；已从 {reference_count} 份总结文件中提取可用事实"
                if options.enhance and reference_count
                else ""
            )
            yield {
                "type": "progress",
                "message": (
                    "已整理 "
                    f"{counts['experiences']} 段实习/工作、{counts['projects']} 个项目、"
                    f"{counts['campus_experiences']} 段校园经历和 {counts['skills']} 项技能"
                    f"{reference_message}"
                ),
            }
        else:
            reference_message = (
                f"；已提取 {reference_count} 份总结文件中的岗位相关事实"
                if options.enhance and reference_count
                else ""
            )
            yield {
                "type": "progress",
                "message": (
                    "已从完整资料中筛选 "
                    f"{counts['experiences']} 段实习/工作、{counts['projects']} 个项目、"
                    f"{counts['campus_experiences']} 段校园经历和 {counts['skills']} 项技能"
                    f"{reference_message}"
                ),
            }
        # 渲染会吃掉模板文件末尾的换行；补回来，让岗位模式的系统提示与改动前逐字节一致。
        system_prompt = self._env.get_template("resume_generate_system.md").render(job=job) + "\n"
        user_prompt = self._env.get_template("resume_generate_user.md").render(
            profile_json=selection.serialized,
            job=job,
            jd=build_job_prompt_text(job, MAX_JD_CHARS) if job else "",
            enhancement_guide=enhancement_guide,
            enhancement_enabled=options.enhance,
            focus_skills="、".join(selection.focus.skills) or "未识别到明确技能，请以 JD 原文为准",
            focus_domains="、".join(selection.focus.domains) or "通用岗位",
            omitted_count=sum(selection.omitted_counts.values()),
            layout_guide=build_layout_guide(options.page_limit, options.font_scale),
            custom_instruction=options.custom_instruction.strip(),
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        yield {"type": "progress", "message": f"正在调用模型 {self.provider.config.model} 生成简历…"}
        parts: list[str] = []
        async for delta in self.provider.stream_chat(messages):
            parts.append(delta)
            yield {"type": "delta", "text": delta}

        raw = "".join(parts)
        resume = self._parse(raw)

        # 输出不是合法 JSON：用修复 Prompt 重试一次，仍然失败则降级报错。
        if resume is None:
            yield {"type": "progress", "message": "输出格式不符合要求，正在自动修复…"}
            fix_prompt = self._env.get_template("resume_fix_json.md").render(raw=raw[:6000])
            try:
                fixed = await self.provider.chat([{"role": "user", "content": fix_prompt}])
            except LLMError as exc:
                yield {"type": "error", "message": f"自动修复调用失败：{exc}"}
                return
            resume = self._parse(fixed)

        if resume is None:
            yield {"type": "error", "message": "模型输出未能解析为有效 JSON，请更换模型或重试"}
            return

        # strong 美化且带附件事实时，先检查模型是否真正完成了岗位化改写。
        has_reference_facts = any(
            _source_list(item, "reference_facts")
            for section in ("educations", "experiences", "campus_experiences", "projects")
            for item in selection.data.get(section, [])
        )
        quality_enabled = (
            options.enhance
            and options.enhancement_level == "strong"
            and has_reference_facts
        )
        content_shortfalls = (
            _quality_shortfalls(resume, selection.data, job) if quality_enabled else []
        )
        # 措辞门槛与美化档位无关，但只在允许改写时生效：关闭美化时正文是用户资料原文。
        wording_enabled = options.enhance
        wording_shortfalls = cliche_shortfalls(resume) if wording_enabled else []
        if content_shortfalls or wording_shortfalls:
            yield {
                "type": "progress",
                "message": "生成内容较简略，正在重新生成…"
                if content_shortfalls
                else "生成结果里有空话或套话，正在改写…",
            }
            reference_facts = [
                {
                    "name": _source_value(source, "name"),
                    "facts": _quality_reference_points(source),
                }
                for source in selection.data.get("projects", [])
                if _quality_reference_points(source)
            ]
            retry_prompt = self._env.get_template("resume_quality_retry.md").render(
                shortfalls="\n".join(
                    f"- {item}" for item in [*content_shortfalls, *wording_shortfalls]
                ),
                reference_facts=json.dumps(reference_facts, ensure_ascii=False),
            )
            retry_messages = [*messages, {"role": "user", "content": retry_prompt}]
            retry_resume: ResumeContent | None = None
            try:
                retry_raw = await self.provider.chat(retry_messages)
                retry_resume = self._parse(retry_raw)
            except Exception as exc:  # noqa: BLE001 - 质量重试失败应保留首轮结果
                logger.warning("简历质量重试失败，将沿用首轮结果：%s", exc)

            retry_content_shortfalls = (
                _quality_shortfalls(retry_resume, selection.data, job)
                if retry_resume is not None and quality_enabled
                else []
            )
            retry_wording_shortfalls = (
                cliche_shortfalls(retry_resume)
                if retry_resume is not None and wording_enabled
                else []
            )
            if retry_resume is not None and not retry_content_shortfalls and not retry_wording_shortfalls:
                resume = retry_resume

        warnings = check_consistency(
            resume, profile, selection.data, source_label="完整资料" if general else None
        )
        if wording_enabled:
            # 重试用过之后仍然命中（或重试失败沿用首轮）时如实告知，不静默留下黑话。
            remaining_cliches = find_cliches(resume)
            if remaining_cliches:
                warnings.append(
                    "生成结果里仍有空话或黑话（"
                    + "、".join(remaining_cliches)
                    + "）：可以在「微调内容」里改掉，或重新生成一次。"
                )
        if general:
            omitted_total = sum(selection.omitted_counts.values())
            if omitted_total:
                # 措辞要同时成立于两种丢弃来源：栏目上限与序列化时的预算压缩，
                # 代码目前分不出是哪一种，所以只说"超出篇幅预算"。
                warnings.append(
                    f"这是通用简历（不按岗位筛选）：完整资料中有 {omitted_total} 条内容"
                    "超出单份简历的篇幅预算，已按资料顺序优先保留靠前的条目；"
                    "需要补充的内容可以在「微调内容」里手动加上。"
                )
        resume = ground_resume_facts(
            resume,
            profile,
            job,
            selection.data,
            enhance=options.enhance,
            enhancement_level=options.enhancement_level,
        ).model_copy(update={"photo": profile.photo})
        resume = restore_selected_sections(
            resume,
            selection.data,
            enhance=options.enhance,
            enhancement_level=options.enhancement_level,
        )
        yield {"type": "done", "resume": resume.model_dump(), "warnings": warnings}

    def _parse(self, raw: str) -> ResumeContent | None:
        data = extract_json(raw)
        return coerce_resume(data) if data is not None else None

__all__ = [
    "ResumeGenerator",
    "extract_json",
    "coerce_resume",
    "check_consistency",
    "ground_resume_facts",
    "restore_selected_sections",
    "build_profile_prompt_data",
    "build_job_prompt_text",
    "build_general_profile_context",
    "build_targeted_profile_context",
    "split_commas",
    "split_lines",
    "MAX_JD_CHARS",
    "MAX_PROFILE_CHARS",
    "ENHANCEMENT_LEVEL_GUIDES",
    "_ENHANCEMENT_DISABLED_GUIDE",
    "_LIST_FIELDS",
    "_REFERENCE_FALLBACK_LIMITS",
    "_similar",
    "_similar_skill",
    "_source_value",
    "_find_source",
    "_normalize_fact",
    "_ground_list",
    "_unsupported_quantified_values",
    "_source_list",
    "_ground_or_restore_list",
    "_source_evidence_text",
    "_enhance_or_restore_list",
    "_build_grounded_summary",
    "_selected_data_with_reference_fallbacks",
    "_quality_shortfalls",
    "_quality_reference_points",
    "_quality_generated_points",
]

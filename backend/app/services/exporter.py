"""简历导出：JSON / Markdown / HTML。

PDF 有两条路：浏览器打印（前端打开导出 HTML 后调用 print，零字体依赖、版式与预览
完全一致），以及服务端直接生成（``pdf_exporter``，可以直接下载，但需要系统中文字体）。
HTML 渲染在这里，同时负责把模板、页数与字号档位写进版式。
"""
import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from jinja2.sandbox import SandboxedEnvironment

from ..schemas.resume import MAX_RESUME_PAGES, ResumeContent
from .resume.resume_sections import DEFAULT_SECTION_ORDER, resolved_section_order
from .resume.resume_templates import (
    DEFAULT_FONT_SCALE,
    DEFAULT_TEMPLATE,
    font_scale_spec,
    format_css,
    template_spec,
    validated_format_config,
)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# 简历内容来自大模型输出，HTML 模板必须开启自动转义防止 XSS。
# 注意模板文件名是 resume.html.j2，后缀匹配需同时覆盖 .html 与 .j2
_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)

# 用户自制模板专用：沙箱环境（禁止访问以 _ 开头的属性与任意 Python 对象），
# 但仍保留同一个文件加载器，好让自制模板能 include 共用正文片段。
_sandbox_env = SandboxedEnvironment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)

_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]+')


def sanitize_filename(name: str) -> str:
    """去除文件名中的非法字符，同时避免 Content-Disposition 注入。"""
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", name).strip(" ._")
    return cleaned or "resume"


def build_filename(resume: ResumeContent, suffix: str) -> str:
    parts = [resume.name or "简历", resume.job_intent or "求职简历"]
    date = datetime.now().strftime("%Y%m%d")
    return f"{sanitize_filename('-'.join(parts))}-{date}.{suffix}"


def export_json(resume: ResumeContent) -> str:
    # 照片是内嵌 data URL，放进 JSON 会产生无意义的大字段；其他资料保持完整。
    return json.dumps(resume.model_dump(exclude={"photo"}), ensure_ascii=False, indent=2)


def _join_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def export_markdown(
    resume: ResumeContent,
    *,
    section_order: list[str] | None = None,
) -> str:
    """导出不包含照片的 Markdown 文本。

    照片是**唯一**的例外（内嵌 data URL，放进文本导出没有意义）。除此之外，凡是预览里会
    出现的内容这里都要有——以前漏掉了性别与出生年：预览页眉显示它们、md 里却查无此项，
    属于"同一份简历两个输出说得不一样"（用户报告的正是这类差异，只是发生在别的输出上）。
    """
    lines: list[str] = []
    header = resume.name
    # 性别在预览里是姓名后缀（与 `_resume_sections.j2` 的位置一致）。
    if resume.gender:
        header += f"（{resume.gender}）"
    if resume.job_intent:
        header += f" · {resume.job_intent}"
    lines.append(f"# {header}")
    contacts = " | ".join(
        item
        for item in [resume.phone, resume.email, resume.city, resume.birth_year]
        if item
    )
    if contacts:
        lines.append(f"{contacts}\n")

    def write_summary() -> None:
        if resume.summary:
            lines.append("## 个人总结\n")
            lines.append(f"{resume.summary}\n")

    def write_education() -> None:
        if resume.education:
            lines.append("## 教育经历\n")
            for edu in resume.education:
                lines.append(
                    f"### {edu.school} · {edu.major} · {edu.degree}（{edu.start_date} - {edu.end_date}）\n"
                )
                if edu.gpa:
                    lines.append(f"- 绩点/排名：{edu.gpa}")
                if edu.courses:
                    lines.append(f"- 核心课程：{'、'.join(edu.courses)}")
                lines.append(_join_bullets(edu.achievements))
                lines.append("")

    def write_experience() -> None:
        if resume.experience:
            lines.append("## 实习/工作经历\n")
            for exp in resume.experience:
                lines.append(f"### {exp.company} · {exp.role}（{exp.start_date} - {exp.end_date}）\n")
                lines.append(_join_bullets(exp.description))
                lines.append("")

    def write_campus_experience() -> None:
        if resume.campus_experience:
            lines.append("## 校园经历\n")
            for item in resume.campus_experience:
                lines.append(
                    f"### {item.organization} · {item.role}（{item.start_date} - {item.end_date}）\n"
                )
                lines.append(_join_bullets(item.description))
                lines.append("")

    def write_projects() -> None:
        if resume.projects:
            lines.append("## 项目经历\n")
            for project in resume.projects:
                lines.append(
                    f"### {project.name} · {project.role}（{project.start_date} - {project.end_date}）\n"
                )
                if project.tech_stack:
                    lines.append(f"**技术栈/工具**：{'、'.join(project.tech_stack)}")
                lines.append(_join_bullets(project.description))
                lines.append(_join_bullets(project.highlights))
                lines.append("")

    def write_skills() -> None:
        if resume.skills:
            lines.append("## 专业技能\n")
            lines.append(_join_bullets(f"{skill.name}（{skill.level}）" if skill.level else skill.name for skill in resume.skills))
            lines.append("")

    def write_awards() -> None:
        if resume.awards:
            lines.append("## 荣誉奖项\n")
            lines.append(
                _join_bullets(
                    f"{award.name} · {award.date}" + (f" · {award.description}" if award.description else "")
                    for award in resume.awards
                )
            )
            lines.append("")

    writers = {
        "summary": write_summary,
        "education": write_education,
        "experience": write_experience,
        "campus_experience": write_campus_experience,
        "projects": write_projects,
        "skills": write_skills,
        "awards": write_awards,
    }

    # 分区顺序与预览 / PDF / Word 共用同一份定义（见 services/resume/resume_sections.py）。
    # Markdown 与 txt 都从这里出，所以两者的顺序天然一致。
    for section_key in section_order or DEFAULT_SECTION_ORDER:
        writers[section_key]()

    return "\n".join(lines).strip() + "\n"


def normalize_page_limit(value: int) -> int:
    return max(1, min(int(value or 1), MAX_RESUME_PAGES))


def _inject_before(html: str, block: str, marker: str) -> str:
    """把一段内容插到标记之前；标记缺失时追加到末尾（宁可少一层样式，也不要报错）。"""
    if marker in html:
        return html.replace(marker, f"{block}\n{marker}", 1)
    return f"{html}\n{block}"


def render_html(
    resume: ResumeContent,
    *,
    template: str = DEFAULT_TEMPLATE,
    page_limit: int = 1,
    font_scale: str = DEFAULT_FONT_SCALE,
    format_config: dict | None = None,
    template_html: str = "",
) -> str:
    """渲染简历 HTML。

    ``page_limit`` 决定 body 高度（N × A4），超过时由模板内脚本整体缩小；
    ``font_scale`` 只改变一个基准像素变量，所有尺寸都由它推算；
    ``format_config`` 是一组受校验的 CSS 覆盖（格式模板）；
    ``template_html`` 非空时用它渲染——那是用户自制的样式模板，走沙箱环境。
    """
    # A per-document nonce authorizes only the fixed A4 fitting script.
    csp_nonce = secrets.token_hex(16)
    spec = template_spec(template)
    scale = font_scale_spec(font_scale)
    overrides = validated_format_config(format_config)
    base_px = float(scale["base_px"])
    adjust = overrides.get("font_scale_adjust")
    if isinstance(adjust, (int, float)):
        base_px = round(base_px * float(adjust), 2)

    context = {
        "resume": resume,
        "csp_nonce": csp_nonce,
        "page_limit": normalize_page_limit(page_limit),
        "base_px": base_px,
        # 正文分区顺序（页眉不参与）。模板里有页码、A4 适配脚本等同样读这个上下文。
        "resume_section_order": resolved_section_order(overrides),
    }

    if template_html:
        # 用户模板走沙箱环境；它的 `{% include "_resume_sections.j2" %}` 仍能命中内置
        # 目录（沙箱环境带同一个文件加载器），所以自制模板复用全部正文片段。
        html = _sandbox_env.from_string(template_html).render(**context)
        # 导入时已剥离 <script>，这里补回页数自适应脚本：自制模板同样需要它。
        fit_script = _env.get_template("_resume_fit_script.j2").render(**context)
        html = _inject_before(html, fit_script, "</body>")
    else:
        html = _env.get_template(spec["file"]).render(**context)

    css = format_css(overrides)
    if css:
        html = _inject_before(html, f"<style>\n{css}\n</style>", "</head>")
    return html

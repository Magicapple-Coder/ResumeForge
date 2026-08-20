"""简历导出：JSON / Markdown / HTML。

PDF 的实现方式：由前端打开导出 HTML 并调用浏览器打印（另存为 PDF）。
选择该方案的原因：服务端 PDF 库（weasyprint 等）在中文环境下依赖
系统字体，跨平台部署极易踩坑；浏览器打印零依赖且中文排版最稳定。
"""
import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..schemas.resume import ResumeContent

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"

# 简历内容来自大模型输出，HTML 模板必须开启自动转义防止 XSS。
# 注意模板文件名是 resume.html.j2，后缀匹配需同时覆盖 .html 与 .j2
_env = Environment(
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


def export_markdown(resume: ResumeContent) -> str:
    """导出不包含照片的 Markdown 文本。"""
    lines: list[str] = []
    header = resume.name
    if resume.job_intent:
        header += f" · {resume.job_intent}"
    lines.append(f"# {header}")
    contacts = " | ".join(item for item in [resume.phone, resume.email, resume.city] if item)
    if contacts:
        lines.append(f"{contacts}\n")

    if resume.summary:
        lines.append("## 个人总结\n")
        lines.append(f"{resume.summary}\n")

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

    if resume.experience:
        lines.append("## 实习/工作经历\n")
        for exp in resume.experience:
            lines.append(f"### {exp.company} · {exp.role}（{exp.start_date} - {exp.end_date}）\n")
            lines.append(_join_bullets(exp.description))
            lines.append("")

    if resume.campus_experience:
        lines.append("## 校园经历\n")
        for item in resume.campus_experience:
            lines.append(
                f"### {item.organization} · {item.role}（{item.start_date} - {item.end_date}）\n"
            )
            lines.append(_join_bullets(item.description))
            lines.append("")

    if resume.projects:
        lines.append("## 项目经历\n")
        for project in resume.projects:
            lines.append(
                f"### {project.name} · {project.role}（{project.start_date} - {project.end_date}）\n"
            )
            if project.tech_stack:
                lines.append(f"**技术栈**：{'、'.join(project.tech_stack)}")
            lines.append(_join_bullets(project.description))
            lines.append(_join_bullets(project.highlights))
            lines.append("")

    if resume.skills:
        lines.append("## 专业技能\n")
        lines.append(_join_bullets(f"{skill.name}（{skill.level}）" if skill.level else skill.name for skill in resume.skills))
        lines.append("")

    if resume.awards:
        lines.append("## 荣誉奖项\n")
        lines.append(
            _join_bullets(
                f"{award.name} · {award.date}" + (f" · {award.description}" if award.description else "")
                for award in resume.awards
            )
        )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def render_html(resume: ResumeContent) -> str:
    # A per-document nonce authorizes only the fixed A4 fitting script.
    csp_nonce = secrets.token_hex(16)
    return _env.get_template("resume.html.j2").render(resume=resume, csp_nonce=csp_nonce)

"""服务端直接生成 PDF（fpdf2 + 系统中文字体）。

为什么自己排版而不是复用 HTML：浏览器打印要用户再点一次「另存为 PDF」，且分页
由浏览器决定；服务端生成可以直接下载，版式稳定。代价是需要一个中文字体——从
系统字体目录里找（Windows 微软雅黑/黑体、macOS PingFang、Linux Noto CJK），
找不到时抛出明确错误，让用户改用浏览器打印，而不是产出一份乱码 PDF。

版式与 HTML 模板不追求像素级一致：三个模板共用一套排版，只在强调色上区分。

**页数上限不在这里强制**：内容超出时宁可多出一页，也不把文字裁掉或缩到看不清。
这与预览的做法一致——预览遇到放不下也是提示用户去加页/缩小字号，而不是默默压缩。
所以这里把实际页数**报出去**（`build_resume_pdf` 返回它），由调用方告诉用户，
替换掉此前"只写一行日志、界面上完全看不出来"的做法。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

from ..schemas.resume import MAX_RESUME_PAGES, ResumeContent

logger = logging.getLogger(__name__)

FONT_FAMILY = "resume-cjk"
# 允许用户用环境变量指定字体（Linux 发行版字体路径五花八门时的兜底）。
FONT_ENV_VAR = "RESUMEFORGE_PDF_FONT"

# (常规, 粗体)；粗体缺失时退回常规。
_FONT_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/msyhbd.ttc"),
    ("C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/simhei.ttf"),
    ("C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/simsun.ttc"),
    ("C:/Windows/Fonts/Deng.ttf", "C:/Windows/Fonts/Dengb.ttf"),
    ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/PingFang.ttc"),
    ("/System/Library/Fonts/Supplemental/Songti.ttc", "/System/Library/Fonts/Supplemental/Songti.ttc"),
    ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf"),
    (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    ),
    (
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    ),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    ("/usr/share/fonts/truetype/arphic/uming.ttc", "/usr/share/fonts/truetype/arphic/uming.ttc"),
)

_TEMPLATE_COLORS: dict[str, tuple[int, int, int]] = {
    "classic": (22, 54, 92),
    "modern": (15, 118, 110),
    "compact": (48, 54, 63),
}

# 1 px = 0.75 pt = 0.2646 mm；正文行高按字号的 1.55 倍留白。
_PX_TO_PT = 0.75
_PX_TO_MM = 0.264_583

MARGIN_X = 14.0
MARGIN_TOP = 12.0
MARGIN_BOTTOM = 13.0
PHOTO_WIDTH = 22.0
PHOTO_HEIGHT = 28.0


class ResumePDFError(Exception):
    """对外暴露的 PDF 生成错误，message 可直接展示给用户。"""


def _resolve_font_paths() -> tuple[str, str] | None:
    override = os.environ.get(FONT_ENV_VAR, "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return str(path), str(path)
        logger.warning("环境变量 %s 指向的字体不存在：%s", FONT_ENV_VAR, override)
    for regular, bold in _FONT_CANDIDATES:
        if Path(regular).is_file():
            return regular, bold if Path(bold).is_file() else regular
    return None


def font_available() -> bool:
    """前端据此决定是否展示「下载 PDF」主按钮。"""
    return _resolve_font_paths() is not None


class _ResumePDF(FPDF):
    def __init__(self, accent: tuple[int, int, int]) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self.accent = accent
        self.set_auto_page_break(auto=True, margin=MARGIN_BOTTOM)
        self.set_margins(MARGIN_X, MARGIN_TOP, MARGIN_X)
        self.set_title("简历")
        self.alias_nb_pages()

    def ensure_space(self, height: float) -> None:
        """剩余空间不足时换页，避免条目被从中间截断。"""
        if self.get_y() + height > self.page_break_trigger:
            self.add_page()

    def section_title(self, text: str, font_size: float) -> None:
        size = font_size * 1.14
        self.ensure_space(size * _PX_TO_MM * 3)
        self.ln(font_size * _PX_TO_MM * 0.5)
        self.set_font(FONT_FAMILY, "B", size * _PX_TO_PT)
        self.set_text_color(*self.accent)
        self.set_x(MARGIN_X)
        self.cell(0, size * _PX_TO_MM * 1.6, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*self.accent)
        self.set_line_width(0.3)
        line_y = self.get_y()
        self.line(MARGIN_X, line_y, 210 - MARGIN_X, line_y)
        self.ln(font_size * _PX_TO_MM * 0.5)
        self.set_text_color(31, 41, 55)

    def bullets(self, items: list[str], font_size: float, indent: float = 3.0) -> None:
        line_height = font_size * _PX_TO_MM * 1.6
        self.set_font(FONT_FAMILY, "", font_size * _PX_TO_PT)
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            self.ensure_space(line_height * 2)
            self.set_x(MARGIN_X + indent)
            self.multi_cell(
                210 - 2 * MARGIN_X - indent,
                line_height,
                f"· {text}",
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
            )

    def entry_head(self, left: str, right: str, font_size: float) -> None:
        line_height = font_size * _PX_TO_MM * 1.7
        self.ensure_space(line_height * 2)
        available = 210 - 2 * MARGIN_X
        left_width = available * 0.68
        right_width = available - left_width
        self.set_font(FONT_FAMILY, "B", font_size * _PX_TO_PT * 1.05)
        self.set_x(MARGIN_X)
        self.cell(left_width, line_height, left, new_x=XPos.RIGHT, new_y=YPos.TOP)
        if right:
            self.set_font(FONT_FAMILY, "", font_size * _PX_TO_PT * 0.92)
            self.set_text_color(107, 114, 128)
            self.cell(right_width, line_height, right, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.set_text_color(31, 41, 55)
        else:
            self.ln(line_height)

    def meta_line(self, text: str, font_size: float) -> None:
        if not text.strip():
            return
        line_height = font_size * _PX_TO_MM * 1.6
        self.ensure_space(line_height)
        self.set_font(FONT_FAMILY, "", font_size * _PX_TO_PT * 0.92)
        self.set_text_color(107, 114, 128)
        self.set_x(MARGIN_X)
        self.multi_cell(
            210 - 2 * MARGIN_X,
            line_height,
            text,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        self.set_text_color(31, 41, 55)


def _join(values: list[str], separator: str = " · ") -> str:
    return separator.join(str(item).strip() for item in values if str(item).strip())


def _photo_bytes(data_url: str) -> bytes | None:
    import base64
    import binascii

    _, separator, encoded = data_url.partition(",")
    if not separator:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


@dataclass(frozen=True)
class ResumePDF:
    """生成好的 PDF，连同它的实际页数——调用方要拿页数去提示用户。"""

    content: bytes
    pages: int


def build_resume_pdf(
    resume: ResumeContent,
    *,
    template: str = "classic",
    page_limit: int = 1,
    font_scale: str = "standard",
) -> ResumePDF:
    """把结构化简历渲染成 PDF。"""
    from .resume_templates import FONT_SCALES, template_spec

    fonts = _resolve_font_paths()
    if fonts is None:
        raise ResumePDFError(
            "未找到可用的中文字体，无法在服务端生成 PDF；请用「打印 / 另存为 PDF」导出，"
            f"或设置环境变量 {FONT_ENV_VAR} 指向一个中文 TTF/TTC 字体文件"
        )
    regular, bold = fonts
    spec = template_spec(template)
    scale = FONT_SCALES.get(font_scale) or FONT_SCALES["standard"]
    base = float(scale["base_px"])

    pdf = _ResumePDF(_TEMPLATE_COLORS.get(spec["name"], _TEMPLATE_COLORS["classic"]))
    try:
        pdf.add_font(FONT_FAMILY, "", regular)
        pdf.add_font(FONT_FAMILY, "B", bold)
    except Exception as exc:  # noqa: BLE001 - 字体解析失败要变成可读提示
        raise ResumePDFError(f"加载中文字体失败（{Path(regular).name}）：{exc}") from exc

    pdf.add_page()
    pdf.set_font(FONT_FAMILY, "", base * _PX_TO_PT)

    # ===== 页头 =====
    header_top = pdf.get_y()
    photo = _photo_bytes(resume.photo) if resume.photo else None
    if photo:
        try:
            from io import BytesIO

            pdf.image(BytesIO(photo), x=210 - MARGIN_X - PHOTO_WIDTH, y=header_top, w=PHOTO_WIDTH, h=PHOTO_HEIGHT)
        except Exception:  # noqa: BLE001 - 照片坏了不能阻断导出
            logger.warning("简历照片无法写入 PDF，已跳过")

    text_width = 210 - 2 * MARGIN_X - (PHOTO_WIDTH + 6 if photo else 0)
    pdf.set_font(FONT_FAMILY, "B", base * 1.86 * _PX_TO_PT)
    pdf.set_text_color(*pdf.accent)
    pdf.set_x(MARGIN_X)
    name_line = resume.name + (f"  {resume.gender}" if resume.gender else "")
    pdf.multi_cell(text_width, base * _PX_TO_MM * 2.4, name_line, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(31, 41, 55)
    if resume.job_intent:
        pdf.set_font(FONT_FAMILY, "", base * 1.05 * _PX_TO_PT)
        pdf.set_text_color(107, 114, 128)
        pdf.set_x(MARGIN_X)
        pdf.multi_cell(
            text_width,
            base * _PX_TO_MM * 1.5,
            f"求职意向：{resume.job_intent}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
    contact = _join([resume.phone, resume.email, resume.city, resume.birth_year], "    ")
    if contact:
        pdf.set_font(FONT_FAMILY, "", base * 0.92 * _PX_TO_PT)
        pdf.set_text_color(107, 114, 128)
        pdf.set_x(MARGIN_X)
        pdf.multi_cell(text_width, base * _PX_TO_MM * 1.5, contact, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_text_color(31, 41, 55)
    pdf.set_y(max(pdf.get_y(), header_top + (PHOTO_HEIGHT if photo else 0)))
    pdf.ln(base * _PX_TO_MM * 0.6)

    # ===== 各分区 =====
    if resume.summary.strip():
        pdf.section_title("个人总结", base)
        pdf.set_font(FONT_FAMILY, "", base * _PX_TO_PT)
        pdf.set_x(MARGIN_X)
        pdf.multi_cell(
            210 - 2 * MARGIN_X,
            base * _PX_TO_MM * 1.65,
            resume.summary.strip(),
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    if resume.education:
        pdf.section_title("教育经历", base)
        for edu in resume.education:
            pdf.entry_head(
                _join([edu.school, edu.major], " · "),
                _join([edu.degree, f"{edu.start_date} - {edu.end_date}"], " · "),
                base,
            )
            if edu.gpa:
                pdf.meta_line(f"绩点/排名：{edu.gpa}", base)
            if edu.courses:
                pdf.meta_line(f"核心课程：{'、'.join(edu.courses)}", base)
            pdf.bullets(edu.achievements, base)

    if resume.experience:
        pdf.section_title("实习/工作经历", base)
        for exp in resume.experience:
            pdf.entry_head(
                _join([exp.company, exp.role], " · "),
                f"{exp.start_date} - {exp.end_date}",
                base,
            )
            pdf.bullets(exp.description, base)

    if resume.campus_experience:
        pdf.section_title("校园经历", base)
        for item in resume.campus_experience:
            pdf.entry_head(
                _join([item.organization, item.role], " · "),
                f"{item.start_date} - {item.end_date}",
                base,
            )
            pdf.bullets(item.description, base)

    if resume.projects:
        pdf.section_title("项目经历", base)
        for project in resume.projects:
            pdf.entry_head(
                _join([project.name, project.role], " · "),
                f"{project.start_date} - {project.end_date}",
                base,
            )
            if project.tech_stack:
                pdf.meta_line(f"技术栈：{'、'.join(project.tech_stack)}", base)
            pdf.bullets(project.description, base)
            pdf.bullets(project.highlights, base)

    if resume.skills:
        pdf.section_title("专业技能", base)
        pdf.set_font(FONT_FAMILY, "", base * _PX_TO_PT)
        text = "、".join(
            f"{skill.name}（{skill.level}）" if skill.level else skill.name for skill in resume.skills
        )
        pdf.set_x(MARGIN_X)
        pdf.multi_cell(
            210 - 2 * MARGIN_X,
            base * _PX_TO_MM * 1.6,
            text,
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )

    if resume.awards:
        pdf.section_title("荣誉奖项", base)
        pdf.bullets(
            [
                _join([award.name, award.date, award.description])
                for award in resume.awards
            ],
            base,
        )

    pages = pdf.pages_count
    limit = max(1, min(int(page_limit), MAX_RESUME_PAGES))
    if pages > limit:
        # 页数超了不裁内容，但必须让用户知道：日志只有开发者能看到。
        logger.info("PDF 页数 %s 超过用户选择的上限 %s", pages, limit)
    return ResumePDF(content=bytes(pdf.output()), pages=pages)


__all__ = ["ResumePDF", "ResumePDFError", "build_resume_pdf", "font_available"]

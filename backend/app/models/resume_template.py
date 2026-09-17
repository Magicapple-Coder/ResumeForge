"""用户自制的简历模板。

模板分两类，这是本模块最重要的约定：

- ``style``：一份 HTML 模板（Jinja 语法），决定简历长什么样。渲染时注入与内置模板
  相同的正文片段（``_resume_sections.j2``）与样式变量，所以自制模板能复用全部字段
  标注（点击纸面字段定位编辑照旧可用）。用户模板里的 ``<script>`` 会被剥离：
  预览与导出都在浏览器里执行，模板不需要脚本，而脚本是最容易被写坏的一环。
- ``format``：一组版式参数（字号基准、页边距、行高、区块间距……），可以叠加在任意
  样式模板之上。

内置模板（classic / modern / compact）不在这个表里——它们是随包发送的 Jinja 文件，
放在表里会让"升级应用"变成"覆盖用户数据"。表里只存用户自己导入或制作的模板。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

TEMPLATE_KIND_STYLE = "style"
TEMPLATE_KIND_FORMAT = "format"
TEMPLATE_KINDS = (TEMPLATE_KIND_STYLE, TEMPLATE_KIND_FORMAT)


class ResumeTemplate(Base):
    __tablename__ = "resume_template"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 用户可见的模板名；同名视为改同一份模板（由服务层做 upsert 判断）。
    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), default=TEMPLATE_KIND_STYLE)
    description: Mapped[str] = mapped_column(String(255), default="")
    # style 模板：完整的 HTML（Jinja）。format 模板留空。
    html: Mapped[str] = mapped_column(Text, default="")
    # format 模板：字号/边距/行高等参数。style 模板也可带一份（可选覆盖）。
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 从 .html/.j2 文件导入时记下原始文件名，便于用户认出是哪一版。
    source_name: Mapped[str] = mapped_column(String(255), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

"""简历生成记录模型：每次生成都落库，支持历史查看与导出。"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow


class ResumeRecord(Base):
    __tablename__ = "resume_record"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    # 目标岗位（快照保存，岗位被删除后记录仍完整可用）
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # 结构化简历
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)  # 一致性校验提醒
    # 历史记录没有该字段时由 SQLite 迁移默认标记为 AI 生成。
    source: Mapped[str] = mapped_column(String(16), default="ai", nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="")
    # 旧数据库中的 tone 列为 NOT NULL 且没有服务端默认值。继续写入默认值仅为
    # 兼容历史表结构；API 和前端均不再暴露定制风格功能。
    tone: Mapped[str] = mapped_column(String(32), default="standard")
    enhancement_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    enhancement_level: Mapped[str] = mapped_column(String(16), default="balanced")
    # 生成时选择的版式参数：重新预览/导出时按同一套参数渲染，改参数不必重新生成。
    template: Mapped[str] = mapped_column(String(32), default="classic", server_default="classic")
    # 格式模板：一组版式覆盖的名字（内置预设名或用户自制格式模板名）；空串表示用样式
    # 模板自带的版式。
    format_name: Mapped[str] = mapped_column(String(64), default="", server_default="")
    # 只属于这份简历的版式覆盖，叠加在 format_name 解析出来的配置之上。
    #
    # 存在的理由：`format_name` 指向的是**具名**格式模板，改了它所有引用它的简历一起变。
    # 而「自动一页」试出来的方案只对当前这份内容成立（换一份内容就不一样了），不该
    # 反过来去污染用户的模板清单，所以按简历单独存一份。
    format_config: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default="{}"
    )
    page_limit: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    font_scale: Mapped[str] = mapped_column(
        String(16), default="standard", server_default="standard"
    )
    # 用户补充的生成要求原文，留痕以便查看和重新生成。
    custom_instruction: Mapped[str] = mapped_column(Text, default="", server_default="")
    # 用户给这份简历写的备注（列表默认可见、详情可编辑）。
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    parse_error: Mapped[str] = mapped_column(Text, default="")  # JSON 解析失败时留痕
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    # 软删除时间戳：NULL 表示「没删」。列表查询一律加 `deleted_at IS NULL`，
    # 回收站里则只看非 NULL 的行（见 ``services/trash.py``）。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ===== 简历生成后台任务状态机 =====
# 「后台继续」= 真后台：关掉弹窗后生成继续跑，用户回来能看到结果。为此把生成从
# 「一次 SSE 请求」改成「一条可轮询的任务」：状态落库、后台线程执行、完成才回填
# resume_id。状态取值与前端 types/resume.ts 镜像的字符串**逐字一致**。
GENERATE_STATUS_PENDING = "pending"
GENERATE_STATUS_RUNNING = "running"
GENERATE_STATUS_COMPLETED = "completed"
GENERATE_STATUS_CANCELLED = "cancelled"
GENERATE_STATUS_FAILED = "failed"
GENERATE_STATUSES = (
    GENERATE_STATUS_PENDING,
    GENERATE_STATUS_RUNNING,
    GENERATE_STATUS_COMPLETED,
    GENERATE_STATUS_CANCELLED,
    GENERATE_STATUS_FAILED,
)

# 仍在推进、需要前端继续轮询的状态。
GENERATE_ACTIVE_STATUSES = (GENERATE_STATUS_PENDING, GENERATE_STATUS_RUNNING)


class ResumeGenerateTask(Base):
    """一次简历生成后台任务。

    为什么单独一张表而不是复用 ``apply_task``：``apply_task`` 深度耦合采集/投递的
    CDP 内核（``current_step`` 是打开页面/填表/上传，``config`` 是限速/熔断阈值），
    简历生成没有这些概念，硬塞进去只会让两种任务的字段互相迁就。这里只保留生成真正
    需要的：状态、完成后回填的 resume_id、错误信息、以及重跑所需的请求快照。
    """

    __tablename__ = "resume_generate_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    # pending/running/completed/cancelled/failed（取值见模块顶部常量）。
    status: Mapped[str] = mapped_column(String(16), default=GENERATE_STATUS_PENDING, index=True)
    # 完成后回填；取消/失败时保持 NULL（**绝不写半成品简历**）。
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    # 失败/取消原因，可直接展示给用户。
    error: Mapped[str] = mapped_column(Text, default="")
    # 最近一条 progress 文案：前端用它映射阶段条、也用于展示"正在做什么"。
    message: Mapped[str] = mapped_column(Text, default="")
    # 已接收的模型原始输出字符数（**只做字数计数，不做百分比**——总长未知）。
    received_chars: Mapped[int] = mapped_column(Integer, default=0)
    # 重跑所需的请求快照：岗位、自定义标题、生成选项。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="")
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

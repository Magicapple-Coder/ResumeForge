"""自动投递中心的数据模型：匹配结论、投递队列与执行批次。

本模块把"采集进来 → 判断够不够 → 显式点头 → 自动投出去"这条链路里需要**持久化**
的部分沉淀成 4 张表：

- ``job_match_analysis``：一个岗位**保留最近一次**匹配结论（重复分析即覆盖），供准入
  判断与界面展示；不建到资料/简历的外键——分析只读资料，证据以文本形式存在结果里。
- ``apply_queue_item``：用户显式勾选的待投递队列。同一岗位在队列里只能有一条。
- ``apply_task``：一次执行批次（采集与投递共用同一张表，靠 ``kind`` 区分）。
- ``apply_task_item``：批次内每个岗位的执行条目，也就是投递记录。

时间戳统一用 ``.profile.utcnow``（无时区 UTC）；岗位/简历被删除后记录仍要可读，所以
对它们用 ``SET NULL`` + 快照字段；批次内的条目随批次 ``CASCADE`` 删除。

本模块同时定义前后端共用的**状态/枚举常量**与唯一的准入闸门映射 ``admission_of``。
只在这里写一次，前端镜像同一份取值，避免"两处各判一次、判得不一样"。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .profile import utcnow

# ===== ① 匹配状态（五类，前后端共用一份取值）=====
MATCH_STATUS_MATCHED = "matched"
MATCH_STATUS_EXPRESSION_GAP = "expression_gap"
MATCH_STATUS_EVIDENCE_INSUFFICIENT = "evidence_insufficient"
MATCH_STATUS_REAL_GAP = "real_gap"
MATCH_STATUS_TO_CONFIRM = "to_confirm"
MATCH_STATUSES = (
    MATCH_STATUS_MATCHED,
    MATCH_STATUS_EXPRESSION_GAP,
    MATCH_STATUS_EVIDENCE_INSUFFICIENT,
    MATCH_STATUS_REAL_GAP,
    MATCH_STATUS_TO_CONFIRM,
)

# ===== ② 准入闸门（唯一权威：只在这里映射一次）=====
ADMISSION_ALLOW = "allow"
ADMISSION_BLOCK = "block"
ADMISSION_NEEDS_CONFIRM = "needs_confirm"
ADMISSIONS = (ADMISSION_ALLOW, ADMISSION_BLOCK, ADMISSION_NEEDS_CONFIRM)

# 硬性门槛结论（冗余在 job_match_analysis.hard_gate，便于查询与展示）。
HARD_GATE_MET = "met"
HARD_GATE_UNMET = "unmet"
HARD_GATE_UNKNOWN = "unknown"
HARD_GATES = (HARD_GATE_MET, HARD_GATE_UNMET, HARD_GATE_UNKNOWN)

_ALLOW_STATUSES = frozenset({MATCH_STATUS_MATCHED, MATCH_STATUS_EXPRESSION_GAP})
_BLOCK_STATUSES = frozenset({MATCH_STATUS_REAL_GAP})
_NEEDS_CONFIRM_STATUSES = frozenset(
    {MATCH_STATUS_EVIDENCE_INSUFFICIENT, MATCH_STATUS_TO_CONFIRM}
)


def admission_of(status: str) -> str:
    """把单条匹配状态映射到投递准入结论。

    ``已匹配`` / ``表达缺口`` → 允许自动投；``真实缺口`` → 不投；
    ``证据不足`` / ``待确认`` → 需用户逐条确认。未知取值按"需确认"处理（保守兜底，
    绝不因为读到一个没见过的状态就放行自动投递）。
    """
    if status in _ALLOW_STATUSES:
        return ADMISSION_ALLOW
    if status in _BLOCK_STATUSES:
        return ADMISSION_BLOCK
    if status in _NEEDS_CONFIRM_STATUSES:
        return ADMISSION_NEEDS_CONFIRM
    return ADMISSION_NEEDS_CONFIRM


def requires_confirmation(status: str) -> bool:
    """该匹配状态是否属于"需用户逐条确认"一类。"""
    return admission_of(status) == ADMISSION_NEEDS_CONFIRM


# ===== ③ 队列条目状态 =====
QUEUE_STATUS_PENDING = "pending"
QUEUE_STATUS_SKIPPED = "skipped"
QUEUE_STATUS_DONE = "done"
QUEUE_STATUSES = (QUEUE_STATUS_PENDING, QUEUE_STATUS_SKIPPED, QUEUE_STATUS_DONE)

# ===== ④ 批次种类 =====
TASK_KIND_COLLECT = "collect"
TASK_KIND_APPLY = "apply"
TASK_KINDS = (TASK_KIND_COLLECT, TASK_KIND_APPLY)

# ===== ⑤ 批次状态机 =====
TASK_STATUS_PENDING = "pending"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_PAUSED = "paused"
TASK_STATUS_BREAKER_PAUSED = "breaker_paused"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_STOPPED = "stopped"
TASK_STATUS_FAILED = "failed"
TASK_STATUSES = (
    TASK_STATUS_PENDING,
    TASK_STATUS_RUNNING,
    TASK_STATUS_PAUSED,
    TASK_STATUS_BREAKER_PAUSED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_STOPPED,
    TASK_STATUS_FAILED,
)

# ===== ⑥ 批次条目状态机 =====
ITEM_STATUS_PENDING = "pending"
ITEM_STATUS_RUNNING = "running"
ITEM_STATUS_SUCCESS = "success"
ITEM_STATUS_FAILED = "failed"
ITEM_STATUS_SKIPPED = "skipped"
ITEM_STATUSES = (
    ITEM_STATUS_PENDING,
    ITEM_STATUS_RUNNING,
    ITEM_STATUS_SUCCESS,
    ITEM_STATUS_FAILED,
    ITEM_STATUS_SKIPPED,
)

# ===== ⑦ 失败分类（一等的可识别类型）=====
FAILURE_SELECTOR_INVALID = "selector_invalid"
FAILURE_LOGIN_REQUIRED = "login_required"
FAILURE_CAPTCHA_REQUIRED = "captcha_required"
FAILURE_GREETING_MISSING = "greeting_missing"
FAILURE_NETWORK_TIMEOUT = "network_timeout"
FAILURE_FILE_UPLOAD_FAILED = "file_upload_failed"
# 岗位不属于任何已注册的招聘网站（例如纯手动录入、来源与投递链接都指不到站点）。
# 它**不是**运行时故障，而是"这个岗位本来就不该走到投递这一步"——所以单列一类，
# 否则记录里只会写「未知失败」，用户与我们都看不出真正的原因。
FAILURE_SITE_UNSUPPORTED = "site_unsupported"
FAILURE_UNKNOWN = "unknown"
FAILURE_CATEGORIES = (
    FAILURE_SELECTOR_INVALID,
    FAILURE_LOGIN_REQUIRED,
    FAILURE_CAPTCHA_REQUIRED,
    FAILURE_GREETING_MISSING,
    FAILURE_NETWORK_TIMEOUT,
    FAILURE_FILE_UPLOAD_FAILED,
    FAILURE_SITE_UNSUPPORTED,
    FAILURE_UNKNOWN,
)

# 面向用户的失败分类说明：诊断信息会直接展示给用户，用户再反馈给我们修，所以要写清楚。
FAILURE_CATEGORY_LABELS = {
    FAILURE_SELECTOR_INVALID: "页面结构变化 / 选择器失效",
    FAILURE_LOGIN_REQUIRED: "需要登录",
    FAILURE_CAPTCHA_REQUIRED: "需要验证码或安全验证",
    FAILURE_GREETING_MISSING: "招呼语缺失",
    FAILURE_NETWORK_TIMEOUT: "网络超时",
    FAILURE_FILE_UPLOAD_FAILED: "简历上传失败",
    FAILURE_SITE_UNSUPPORTED: "岗位来源不支持自动投递",
    FAILURE_UNKNOWN: "未知失败",
}

# ===== ⑧ 执行步骤（apply_task.current_step）=====
STEP_OPENING = "opening"
STEP_FILLING = "filling"
STEP_GREETING = "greeting"
STEP_UPLOADING = "uploading"
STEP_SUBMITTING = "submitting"
STEP_VERIFYING = "verifying"
STEP_WAITING = "waiting"
STEP_IDLE = "idle"
TASK_STEPS = (
    STEP_OPENING,
    STEP_FILLING,
    STEP_GREETING,
    STEP_UPLOADING,
    STEP_SUBMITTING,
    STEP_VERIFYING,
    STEP_WAITING,
    STEP_IDLE,
)

# ===== ⑨ 停止原因 =====
STOP_REASON_USER = "user"
STOP_REASON_BREAKER = "breaker"
STOP_REASON_DONE = "done"
STOP_REASON_ERROR = "error"
STOP_REASONS = (STOP_REASON_USER, STOP_REASON_BREAKER, STOP_REASON_DONE, STOP_REASON_ERROR)


class JobMatchAnalysis(Base):
    """岗位匹配度分析结果：一个岗位保留最近一次，供准入与展示。"""

    __tablename__ = "job_match_analysis"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 一个岗位只保留最近一次分析（job_id 唯一）：重复分析即覆盖。岗位删除后置空，
    # 但 job_title / company 快照与结果仍在，历史结论不会凭空消失。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True, unique=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    # 完整匹配结果（结构见设计 §3.4）：硬性条件、核心能力、加分项、结论、建议、口径说明。
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 硬性门槛结论：met / unmet / unknown（准入闸门字段，单独冗余便于查询）。
    hard_gate: Mapped[str] = mapped_column(String(16), default=HARD_GATE_UNKNOWN, index=True)
    # 是否含需逐条确认项（待确认 / 证据不足）。
    requires_confirm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    model: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ApplyQueueItem(Base):
    """投递队列条目：用户显式勾选、按顺序待投递的岗位。"""

    __tablename__ = "apply_queue_item"
    __table_args__ = (UniqueConstraint("job_id", name="uq_apply_queue_item_job_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # 队列条目只来自"岗位广场里已存在的岗位"；岗位被删除后条目仍可读（快照 + SET NULL）。
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    # 用户指定用哪份简历；空 = 运行时按默认规则解析。
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    # 本岗位的招呼语（用户可编辑 / 按岗位生成后落此）；空 = 用默认招呼语。
    greeting: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # pending(待投递) / skipped(用户移出前保留) / done(已投递)。
    status: Mapped[str] = mapped_column(String(16), default=QUEUE_STATUS_PENDING, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ApplyTask(Base):
    """一次执行批次：采集与投递共用，靠 kind 区分。"""

    __tablename__ = "apply_task"

    id: Mapped[int] = mapped_column(primary_key=True)
    # collect(采集) / apply(投递)。
    kind: Mapped[str] = mapped_column(String(16), index=True)
    # 状态机取值见模块顶部常量（pending/running/paused/breaker_paused/completed/...）。
    status: Mapped[str] = mapped_column(String(16), default=TASK_STATUS_PENDING, index=True)
    # 数量化进度（**不用百分比**）：总数与各状态计数。
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    # 当前步骤（opening/filling/greeting/submitting/waiting/...）。
    current_step: Mapped[str] = mapped_column(String(32), default="")
    # 停止原因：user/breaker/done/error。
    stop_reason: Mapped[str] = mapped_column(String(32), default="")
    # 本次运行生效的配置快照（间隔/上限/熔断阈值…），留痕便于复现。
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # 醒目提示文案（熔断、需登录等）。
    message: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ApplyTaskItem(Base):
    """批次内每岗位执行条目，也就是一条投递记录。"""

    __tablename__ = "apply_task_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 条目随批次删除（CASCADE）。
    task_id: Mapped[int] = mapped_column(
        ForeignKey("apply_task.id", ondelete="CASCADE"), index=True
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_title: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(128), default="")
    # 快照：记录当时用的简历，简历被删除后仍可读。
    resume_id: Mapped[int | None] = mapped_column(
        ForeignKey("resume_record.id", ondelete="SET NULL"), nullable=True
    )
    resume_title: Mapped[str] = mapped_column(String(256), default="")
    # 实际发送的招呼语（脱敏按"记全文但截断到合理上限"处理）。
    greeting: Mapped[str] = mapped_column(Text, default="")
    # pending / running / success / failed / skipped。
    status: Mapped[str] = mapped_column(String(16), default=ITEM_STATUS_PENDING, index=True)
    # 失败分类（selector_invalid / captcha_required / ...），空串表示未失败。
    failure_category: Mapped[str] = mapped_column(String(32), default="")
    # 可操作诊断（当前 URL / 页面标题 / 匹配控件数 / 期望控件描述）。
    failure_detail: Mapped[str] = mapped_column(Text, default="")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

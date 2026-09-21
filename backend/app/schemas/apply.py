"""自动投递中心的请求/响应结构：配置、浏览器状态、队列、批次与记录。

状态/失败分类等字符串取值与 ``models/apply`` 里的常量**逐字一致**（前端再镜像一份），
改一处必须同步另一处。
"""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import DEFAULT_BROWSER_PORT
from ..models.apply import FAILURE_CATEGORIES
from .job_match import AdmissionResult, HardGateResult

# ===== 配置默认值（出厂默认，键与 app_setting 一致）=====
DEFAULT_INTERVAL_SECONDS = 25
DEFAULT_INTERVAL_JITTER_SECONDS = 8
DEFAULT_DAILY_LIMIT = 60
DEFAULT_PER_TASK_LIMIT = 20
DEFAULT_BREAKER_THRESHOLD = 3
DEFAULT_GREETING = "您好，我对该岗位很感兴趣，期待进一步沟通。"

DEFAULT_COLLECT_KEYWORDS: list[str] = []
DEFAULT_COLLECT_PER_TASK_LIMIT = 20
DEFAULT_COLLECT_INTERVAL_SECONDS = 6
DEFAULT_COLLECT_INTERVAL_JITTER_SECONDS = 3

# 投递专用浏览器的选择方式与自定义路径长度上限。
DEFAULT_BROWSER_CHOICE = "auto"
BROWSER_PATH_MAX_CHARS = 512


def default_site_key() -> str:
    """当前站点的出厂默认值：注册表里第一个站点的标识。

    延迟导入注册表，避免"schemas ← services.sites ← ..."在导入期形成不必要的耦合；
    注册表本身缓存且轻量，这里按需取即可。取不到（注册表为空）时返回空串，由业务层兜底。
    """
    from ..services.sites.registry import get_registry

    try:
        return get_registry().default_key()
    except Exception:  # noqa: BLE001 - 默认值计算失败不该让配置模型无法实例化
        return ""

# 招呼语落库时的截断上限：记用户写给 HR 的全文，但不让单条无限增长。
GREETING_RECORD_MAX_CHARS = 500
GREETING_INPUT_MAX_CHARS = 1000

MAX_QUEUE_BATCH = 200
MAX_TASK_TARGETS = 500
MAX_COLLECT_KEYWORDS = 10
# 站点侧筛选项的规模上限。选项是站点提供的、数量有限（BOSS 一共 7 组），给一个宽松但
# 明确的上界挡住畸形请求体即可；真正"这个编码能不能用"由适配器在采集前逐个校验。
MAX_COLLECT_FILTERS = 16
COLLECT_FILTER_KEY_MAX_CHARS = 32
COLLECT_FILTER_CODE_MAX_CHARS = 32

# 「补齐详情」的单批上限。补详情要逐个打开岗位页面（详情页是整个采集里最慢的一步），几百条一批
# 会让一次任务跑很久、也更容易被风控盯上，所以超过就让用户分批。这个上限由**业务层**给出可操作的
# 中文说明；schema 这层只用一个更大的硬上限挡住明显异常的请求体——阈值若设成一样，友好提示会被
# 校验挡在外面，用户只会拿到一条 Pydantic 报错，看不到"要分批"的理由。
MAX_BACKFILL_JOBS = 200
MAX_BACKFILL_REQUEST_ITEMS = 1000

BrowserState = Literal["stopped", "starting", "running", "unknown"]
# 浏览器选择：auto=自动（优先 Chrome，未装回退 Edge）/ chrome / edge / custom=自定义路径。
BrowserChoice = Literal["auto", "chrome", "edge", "custom"]
QueueStatus = Literal["pending", "skipped", "done"]
TaskStatus = Literal[
    "pending",
    "running",
    "paused",
    "breaker_paused",
    "completed",
    "stopped",
    "failed",
]
TaskKind = Literal["collect", "apply"]
TaskItemStatus = Literal["pending", "running", "success", "failed", "skipped"]
FailureCategory = Literal[
    "selector_invalid",
    "login_required",
    "captcha_required",
    "greeting_missing",
    "network_timeout",
    "file_upload_failed",
    "unknown",
]


def _check_failure_category(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned and cleaned not in FAILURE_CATEGORIES:
        raise ValueError(f"无效的失败分类，可选值：{'、'.join(FAILURE_CATEGORIES)}")
    return cleaned


# ===== 投递配置 =====


class ApplyConfigIn(BaseModel):
    """投递配置（覆盖写）。范围校验不合法由 FastAPI 返回 422。"""

    model_config = ConfigDict(extra="forbid")

    interval_seconds: int = Field(default=DEFAULT_INTERVAL_SECONDS, ge=1, le=600)
    interval_jitter_seconds: int = Field(default=DEFAULT_INTERVAL_JITTER_SECONDS, ge=0, le=300)
    daily_limit: int = Field(default=DEFAULT_DAILY_LIMIT, ge=1, le=1000)
    per_task_limit: int = Field(default=DEFAULT_PER_TASK_LIMIT, ge=1, le=200)
    breaker_threshold: int = Field(default=DEFAULT_BREAKER_THRESHOLD, ge=1, le=20)
    default_greeting: str = Field(default=DEFAULT_GREETING, max_length=GREETING_INPUT_MAX_CHARS)
    skip_same_company: bool = True
    confirm_real_gap: bool = False
    browser_port: int = Field(default=DEFAULT_BROWSER_PORT, ge=1024, le=65535)
    # 用户可自由选择投递台使用的浏览器：auto（优先 Chrome）/ chrome / edge / custom（自定义路径）。
    browser_choice: BrowserChoice = DEFAULT_BROWSER_CHOICE
    # 自定义浏览器可执行文件的绝对路径；仅当 browser_choice == "custom" 时生效。
    browser_path: str = Field(default="", max_length=BROWSER_PATH_MAX_CHARS)
    # 当前对接的招聘网站（站点适配器 key）；默认取注册表里第一个站点。
    site_key: str = Field(default_factory=default_site_key, max_length=32)


class ApplyConfigOut(ApplyConfigIn):
    """当前生效的投递配置 + 出厂默认值回显。"""

    defaults: ApplyConfigIn = Field(default_factory=ApplyConfigIn)


# ===== 采集配置 =====


class CollectConfigIn(BaseModel):
    """采集配置。关键词 + 城市 + 翻页是首期确定生效的；薪资/经验/学历依赖站点映射，

    映射失败时由界面显示「未生效」，绝不静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    keywords: list[str] = Field(default_factory=list, max_length=MAX_COLLECT_KEYWORDS)
    city: str = Field(default="", max_length=64)
    salary_min: int | None = Field(default=None, ge=0, le=1000)
    experience: str = Field(default="", max_length=32)
    education: str = Field(default="", max_length=32)
    # 采集结果的岗位类型标注（校招/实习/社招）；空串 = 不限。**仅入库标注**：
    # 不入去重判据、不参与站点筛选（与薪资/经验/学历"采集后本地筛选"口径一致）。
    job_type: str = Field(default="", max_length=32)
    # **站点侧筛选项**：``{分组 key: 选项编码}``（如 ``{"degree": "203"}``）。选项清单由适配器
    # 从站点自己那里读（见 ``services/sites/boss_filters``），界面渲染成下拉框，用户选什么就存
    # 什么；编码在**采集开始前**由适配器对着当次读到的清单校验，不通过的如实上报、绝不发出去。
    #
    # 与上面三个字段的分工：``salary_min`` / ``experience`` / ``education`` 筛的是
    # **"你的条件 vs 岗位要求"**（"我是本科"），``filters`` 是**站点筛选栏本身**
    # （"岗位要求本科"）。两者语义不同，可以同时用。
    filters: dict[str, str] = Field(default_factory=dict)
    per_task_limit: int = Field(default=DEFAULT_COLLECT_PER_TASK_LIMIT, ge=1, le=200)
    interval_seconds: int = Field(default=DEFAULT_COLLECT_INTERVAL_SECONDS, ge=1, le=600)
    interval_jitter_seconds: int = Field(default=DEFAULT_COLLECT_INTERVAL_JITTER_SECONDS, ge=0, le=300)

    @field_validator("filters")
    @classmethod
    def filters_must_be_bounded(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_COLLECT_FILTERS:
            raise ValueError(f"站点筛选项最多 {MAX_COLLECT_FILTERS} 个")
        cleaned: dict[str, str] = {}
        for key, code in value.items():
            clean_key = (key or "").strip()
            clean_code = (code or "").strip()
            if not clean_key or not clean_code:
                continue
            if len(clean_key) > COLLECT_FILTER_KEY_MAX_CHARS:
                raise ValueError("筛选项名称过长")
            if len(clean_code) > COLLECT_FILTER_CODE_MAX_CHARS:
                raise ValueError("筛选项编码过长")
            cleaned[clean_key] = clean_code
        return cleaned

    @field_validator("keywords")
    @classmethod
    def keywords_must_be_clean(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in value:
            text = (item or "").strip()
            if not text:
                continue
            if len(text) > 50:
                raise ValueError("单个关键词不能超过 50 个字")
            if text not in cleaned:
                cleaned.append(text)
        return cleaned


class CollectConfigOut(CollectConfigIn):
    """当前生效的采集配置 + 出厂默认值回显。"""

    defaults: CollectConfigIn = Field(default_factory=CollectConfigIn)


class CollectFilterOptionOut(BaseModel):
    """一个可选项。``group`` 只用于界面分组（行业有 15 个一级分组），其余为空。"""

    code: str
    label: str
    group: str = ""


class CollectFilterGroupOut(BaseModel):
    """站点筛选栏里的一格，对应界面上的一个下拉框。"""

    key: str
    param: str
    label: str
    options: list[CollectFilterOptionOut] = Field(default_factory=list)
    # 这份清单是从哪儿读来的：session（你的登录会话）/ public（全网通用）/ snapshot（内置快照）
    # / unavailable（这次读不到）。**必须展示给用户**——不同来源可信度不同，用户有权知道
    # 自己选的那一项是"这个账号真实可见的"还是"退回的公共清单"。
    source: str = "unavailable"
    note: str = ""


class CollectFilterOptionsOut(BaseModel):
    """当前站点的站点侧筛选项清单。"""

    site_key: str = ""
    display_name: str = ""
    groups: list[CollectFilterGroupOut] = Field(default_factory=list)
    # 是否读到了登录态清单（false = 浏览器没启动或读失败，用的是公共清单）。
    session_read: bool = False


class CollectTaskCreateIn(BaseModel):
    """开始一次采集的请求体。

    只有一个可选开关：是否保存本次抓到的站点原文（用于排查解析问题）。**默认关闭**——往磁盘
    写站点数据必须由用户每次显式勾选，绝不默认记录。
    """

    model_config = ConfigDict(extra="forbid")

    save_site_samples: bool = False


class CollectBackfillIn(BaseModel):
    """「补齐详情」请求体：按岗位 id 只补抓详情。

    用于修**历史遗留**的空 JD——当年采集时详情没抓到（该成因已修好），但已经落库的那几条修不了，
    因为采集按 URL 去重、重新采集会直接跳过它们。这里改由用户点名补齐。
    """

    model_config = ConfigDict(extra="forbid")

    # 空列表不在 schema 层拦：交给业务层给出「请先选择要补齐详情的岗位」这类可操作的中文提示。
    job_ids: list[int] = Field(default_factory=list, max_length=MAX_BACKFILL_REQUEST_ITEMS)


# ===== 投递专用浏览器 =====


class BrowserStatusOut(BaseModel):
    """投递专用浏览器的状态。"""

    state: BrowserState = "stopped"
    port: int = DEFAULT_BROWSER_PORT
    profile_dir: str = ""
    browser_path: str = ""
    # 人类可读的浏览器名（Google Chrome / Microsoft Edge / 自定义浏览器），别只给路径。
    browser_name: str = ""
    # 启动浏览器时要打开的站点入口地址，同时用于界面上的"打开招聘网站"按钮。
    entry_url: str = ""
    # 给用户看的登录提示（例如"请在弹出的窗口里扫码登录一次"），不读取也不解析登录态。
    logged_in_hint: str = ""
    # 这个浏览器是不是**本次运行**启动的。为 False 表示它是上一次运行时打开的窗口：
    # state 照样是 running（调试端口在答，采集投递都能用），但「关闭浏览器」关不掉它——
    # 进程句柄随后端重启丢了，而应用只关自己拉起的进程，绝不按 PID 去猜。
    owned: bool = False


# ===== 招聘网站（站点适配器）=====


class SiteOptionOut(BaseModel):
    """一个已注册的招聘网站（供界面展示当前站点、也为将来加站点预留）。"""

    key: str
    display_name: str
    host: str = ""
    entry_url: str = ""
    supports_collect: bool = True
    supports_apply: bool = True


class SiteListOut(BaseModel):
    """已注册站点列表 + 当前选中项。

    前端**只**从这里读取站点清单与名称，绝不把站点名写死在组件里——这样以后新增一个
    招聘网站，只要在后端注册表里 ``register`` 一行，界面自动跟着变。
    """

    current: str = ""
    sites: list[SiteOptionOut] = Field(default_factory=list)


# ===== ⑪ 站点健康度（把"采集悄悄抓不到东西"变成看得见的 degraded 标记）=====


class CollectRunSummaryOut(BaseModel):
    """一次采集运行的摘要——站点健康度判据的输入之一。"""

    status: str = ""
    failure_category: str = ""
    succeeded: int = 0
    detail_missing: int = 0
    created_at: str = ""


class SiteHealthOut(BaseModel):
    """一个招聘网站的采集健康度：``ok``（正常）或 ``degraded``（疑似改版）。"""

    site_key: str = ""
    display_name: str = ""
    status: Literal["ok", "degraded"] = "ok"
    # 人类可读、可操作的中文原因。前端**只展示**，绝不自行再判一次（判断的权威只有后端一处）。
    reasons: list[str] = Field(default_factory=list)
    # 统计明细：样本数、结构失败次数、详情漂移次数，供界面 / 诊断核对。
    sampled: int = 0
    selector_failures: int = 0
    detail_drift_runs: int = 0
    # 最近几次运行的摘要（与判据同一份输入），便于用户对照「采集记录」。
    recent: list[CollectRunSummaryOut] = Field(default_factory=list)


class SiteHealthListOut(BaseModel):
    """所有已注册站点的健康度。前端据 ``site_key`` 找到当前站点的状态。"""

    sites: list[SiteHealthOut] = Field(default_factory=list)


# ===== 投递队列 =====


class ApplyQueueAddItem(BaseModel):
    """加入队列的一项：岗位必填，简历与招呼语可选。"""

    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(ge=1)
    resume_id: int | None = Field(default=None, ge=1)
    greeting: str = Field(default="", max_length=GREETING_INPUT_MAX_CHARS)
    # 命中"真实缺口"时，用户需要显式确认为真才会入队。
    confirm_real_gap: bool = False
    # 尚未分析过的岗位，用户需要显式确认"我知道它没分析过"。
    confirm_unanalyzed: bool = False


class ApplyQueueAddRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ApplyQueueAddItem] = Field(min_length=1, max_length=MAX_QUEUE_BATCH)


class ApplyQueueItemUpdate(BaseModel):
    """PATCH 语义：只更新提交了的字段（None = 不改）。"""

    model_config = ConfigDict(extra="forbid")

    greeting: str | None = Field(default=None, max_length=GREETING_INPUT_MAX_CHARS)
    resume_id: int | None = Field(default=None, ge=1)


class ApplyQueueReorderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: list[int] = Field(default_factory=list, max_length=MAX_TASK_TARGETS)


class ApplyQueueItemOut(BaseModel):
    """队列条目，附带该岗位最近一次匹配结论的摘要，供界面展示准入。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    resume_id: int | None = None
    resume_title: str = ""
    greeting: str = ""
    sort_order: int = 0
    status: QueueStatus = "pending"
    # 最近一次匹配结论摘要：未分析时 admission / hard_gate 为 None。
    admission: AdmissionResult | None = None
    hard_gate: HardGateResult | None = None
    requires_confirm: bool = False
    # 这个岗位能不能自动投递：取决于**来源**是否落在已注册招聘网站上，与匹配结论无关。
    # 默认 True 是刻意的兜底方向——万一某处没算，结果是"界面允许、后端拒绝并说明原因"，
    # 而不是把能投的岗位误标成不能投。
    apply_supported: bool = True
    created_at: datetime
    updated_at: datetime


# ===== 批次（执行）=====


class ApplyTaskCreate(BaseModel):
    """显式开始投递：默认取整队列；给了 job_ids 就只投这几个已勾选的。

    两个都不给（空体且 use_queue=False）必须由 API 层返回 400——绝无"无参数即全网海投"。
    """

    model_config = ConfigDict(extra="forbid")

    job_ids: list[int] | None = Field(default=None, max_length=MAX_TASK_TARGETS)
    use_queue: bool = False


class ApplyTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: TaskKind
    status: TaskStatus
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    current_step: str = ""
    stop_reason: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ApplyTaskItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    resume_id: int | None = None
    resume_title: str = ""
    greeting: str = ""
    status: TaskItemStatus = "pending"
    failure_category: str = ""
    failure_detail: str = ""
    attempt: int = 0
    sort_order: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime

    @field_validator("failure_category")
    @classmethod
    def failure_category_must_be_known(cls, value: str) -> str:
        return _check_failure_category(value)


class ApplyTaskDetailOut(ApplyTaskOut):
    items: list[ApplyTaskItemOut] = Field(default_factory=list)


# ===== 记录 =====


class ApplyRecordOut(BaseModel):
    """投递记录（已脱敏：只含岗位/简历的展示快照，不含任何完整个人资料）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    job_id: int | None = None
    job_title: str = ""
    company: str = ""
    resume_title: str = ""
    greeting: str = ""
    status: TaskItemStatus = "pending"
    failure_category: str = ""
    # 失败分类的中文说明（由服务层按 FAILURE_CATEGORY_LABELS 填充）。
    failure_label: str = ""
    failure_detail: str = ""
    attempt: int = 0
    created_at: datetime
    finished_at: datetime | None = None

    @field_validator("failure_category")
    @classmethod
    def failure_category_must_be_known(cls, value: str) -> str:
        return _check_failure_category(value)


class ApplyRecordBatchOut(BaseModel):
    """一个投递批次及其全部记录（投递记录按批次分组展示的载体）。

    一次「开始投递」建一个批次（``ApplyTask``，kind=apply），批次里的每个岗位是一条
    记录（``ApplyTaskItem``）。用户一次性投了好几个岗位时，这几条记录同属一个批次，
    界面把它们折叠成一组、点击展开看明细——分组键就是批次 id。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    status: TaskStatus
    total: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    message: str = ""
    created_at: datetime
    finished_at: datetime | None = None
    items: list[ApplyRecordOut] = Field(default_factory=list)


# ===== 招呼语预览 =====


class GreetingPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: int = Field(ge=1)
    # 给了 item_id 就基于队列里该条目当前的简历与招呼语来生成。
    item_id: int | None = Field(default=None, ge=1)


class GreetingPreviewOut(BaseModel):
    greeting: str = ""
    # 来源：generated（模型生成）/ queue（队列已有值）/ default（默认招呼语）。
    source: str = "default"


__all__ = [
    "ApplyConfigIn",
    "ApplyConfigOut",
    "ApplyQueueAddItem",
    "ApplyQueueAddRequest",
    "ApplyQueueItemOut",
    "ApplyQueueItemUpdate",
    "ApplyQueueReorderRequest",
    "ApplyRecordBatchOut",
    "ApplyRecordOut",
    "ApplyTaskCreate",
    "ApplyTaskDetailOut",
    "ApplyTaskItemOut",
    "ApplyTaskOut",
    "BrowserChoice",
    "BrowserState",
    "BrowserStatusOut",
    "CollectBackfillIn",
    "CollectConfigIn",
    "CollectConfigOut",
    "CollectFilterGroupOut",
    "CollectFilterOptionOut",
    "CollectFilterOptionsOut",
    "CollectRunSummaryOut",
    "CollectTaskCreateIn",
    "DEFAULT_BROWSER_CHOICE",
    "DEFAULT_BROWSER_PORT",
    "DEFAULT_GREETING",
    "FailureCategory",
    "GREETING_INPUT_MAX_CHARS",
    "GREETING_RECORD_MAX_CHARS",
    "GreetingPreviewOut",
    "GreetingPreviewRequest",
    "MAX_BACKFILL_JOBS",
    "MAX_BACKFILL_REQUEST_ITEMS",
    "QueueStatus",
    "SiteHealthListOut",
    "SiteHealthOut",
    "SiteListOut",
    "SiteOptionOut",
    "TaskItemStatus",
    "TaskKind",
    "TaskStatus",
    "_check_failure_category",
    "default_site_key",
]

"""搜索与统计 Schema。"""
from pydantic import BaseModel

from .job import JobOut
from .resume import ResumeBrief


class SearchResult(BaseModel):
    jobs: list[JobOut] = []
    resumes: list[ResumeBrief] = []


class PendingClaimBrief(BaseModel):
    """待确认的台账条目：首页只报数，点进去才看详情。"""

    id: int
    title: str


class Stats(BaseModel):
    job_count: int
    open_job_count: int
    resume_count: int
    week_resume_count: int
    latest_jobs: list[JobOut] = []
    latest_resumes: list[ResumeBrief] = []
    # 首页"接下来做什么"需要的几个数。全部只报**待办**，不报"你做了多少"——
    # 概览页上真正能推动用户的只有"还有什么没做完"。
    favorite_job_count: int = 0
    pending_claim_count: int = 0
    pending_claims: list[PendingClaimBrief] = []
    stalled_application_count: int = 0
    apply_queue_count: int = 0
    # 最近投递结果：给首页一条"投出去之后怎么样了"的线索。
    latest_applications: list[dict] = []

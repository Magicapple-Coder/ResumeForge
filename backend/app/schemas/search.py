"""搜索与统计 Schema。"""
from pydantic import BaseModel

from .job import JobOut
from .resume import ResumeBrief


class SearchResult(BaseModel):
    jobs: list[JobOut] = []
    resumes: list[ResumeBrief] = []


class Stats(BaseModel):
    job_count: int
    open_job_count: int
    resume_count: int
    week_resume_count: int
    latest_jobs: list[JobOut] = []
    latest_resumes: list[ResumeBrief] = []

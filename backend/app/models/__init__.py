"""集中导入全部模型，保证 Base.metadata 注册完整（create_all 依赖此注册）。"""
from .job import Job
from .profile import Award, CampusExperience, Education, Experience, Project, Skill, UserProfile
from .resume import ResumeRecord
from .setting import AppSetting, LLMConfigRecord

__all__ = [
    "Job",
    "UserProfile",
    "Education",
    "Experience",
    "CampusExperience",
    "Project",
    "Skill",
    "Award",
    "ResumeRecord",
    "AppSetting",
    "LLMConfigRecord",
]

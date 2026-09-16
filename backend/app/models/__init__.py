"""集中导入全部模型，保证 Base.metadata 注册完整（create_all 依赖此注册）。"""

from .assistant import AssistantSkill, AssistantSkillFile, ChatConversation, ChatMessage
from .job import Job
from .material import MATERIAL_CATEGORIES, CandidateJob, Material
from .profile import (
    Award,
    CampusExperience,
    Education,
    Experience,
    ProfilePhoto,
    Project,
    Skill,
    UserProfile,
)
from .resume import ResumeRecord
from .setting import AppSetting, LLMConfigRecord

__all__ = [
    "Job",
    "ChatConversation",
    "ChatMessage",
    "AssistantSkill",
    "AssistantSkillFile",
    "UserProfile",
    "ProfilePhoto",
    "Education",
    "Experience",
    "CampusExperience",
    "Project",
    "Skill",
    "Award",
    "ResumeRecord",
    "AppSetting",
    "LLMConfigRecord",
    "Material",
    "MATERIAL_CATEGORIES",
    "CandidateJob",
]

"""集中导入全部模型，保证 Base.metadata 注册完整（create_all 依赖此注册）。"""

from .assistant import AssistantSkill, AssistantSkillFile, ChatConversation, ChatMessage
from .interview import (
    INTERVIEW_DIFFICULTIES,
    INTERVIEW_STATUS_ACTIVE,
    INTERVIEW_STATUS_FINISHED,
    INTERVIEW_TYPES,
    INTERVIEWER_STYLES,
    InterviewMessage,
    InterviewSession,
)
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
from .resume_template import TEMPLATE_KIND_FORMAT, TEMPLATE_KIND_STYLE, TEMPLATE_KINDS, ResumeTemplate
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
    "ResumeTemplate",
    "TEMPLATE_KINDS",
    "TEMPLATE_KIND_STYLE",
    "TEMPLATE_KIND_FORMAT",
    "InterviewSession",
    "InterviewMessage",
    "INTERVIEW_TYPES",
    "INTERVIEW_DIFFICULTIES",
    "INTERVIEWER_STYLES",
    "INTERVIEW_STATUS_ACTIVE",
    "INTERVIEW_STATUS_FINISHED",
]

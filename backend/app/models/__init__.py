"""集中导入全部模型，保证 Base.metadata 注册完整（create_all 依赖此注册）。"""

from .apply import (
    ADMISSIONS,
    FAILURE_CATEGORIES,
    FAILURE_CATEGORY_LABELS,
    HARD_GATES,
    ITEM_STATUSES,
    MATCH_STATUSES,
    QUEUE_STATUSES,
    STOP_REASONS,
    TASK_KINDS,
    TASK_STEPS,
    TASK_STATUSES,
    ApplyQueueItem,
    ApplyTask,
    ApplyTaskItem,
    JobMatchAnalysis,
)
from .assistant import AssistantSkill, AssistantSkillFile, ChatConversation, ChatMessage
from .drill import (
    DRILL_STATUS_ACTIVE,
    DRILL_STATUS_FINISHED,
    EVIDENCE_STATUSES,
    REHEARSE_KINDS,
    DrillContract,
    DrillSession,
    DrillTurn,
)
from .claim import (
    CLAIM_CATEGORIES,
    RESPONSIBILITY_LEVELS,
    VERIFICATION_STATUSES,
    ClaimRecord,
)
from .interview import (
    INTERVIEW_DIFFICULTIES,
    INTERVIEW_STATUS_ACTIVE,
    INTERVIEW_STATUS_FINISHED,
    INTERVIEW_TYPES,
    INTERVIEWER_STYLES,
    InterviewMessage,
    InterviewSession,
)
from .interview_experience import (
    EXPERIENCE_ROUND_TYPES,
    EXPERIENCE_SOURCES,
    InterviewExperience,
)
from .interview_review_record import InterviewReviewRecord
from .job import Job
from .knowledge_entry import KnowledgeEntry
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
from .question_bank_record import QuestionBankRecord
from .referral import REFERRAL_STATUSES, Referral
from .reminder import REMINDER_KINDS, REMINDER_STATUSES, Reminder
from .resume import (
    GENERATE_ACTIVE_STATUSES,
    GENERATE_STATUSES,
    ResumeGenerateTask,
    ResumeRecord,
)
from .tracker import (
    SOURCES,
    STATUSES,
    ApplicationTrack,
)
from .resume_template import TEMPLATE_KIND_FORMAT, TEMPLATE_KIND_STYLE, TEMPLATE_KINDS, ResumeTemplate
from .setting import AppSetting, LLMConfigRecord
from .share_package import SHARE_PERMISSIONS, SharePackage

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
    "ResumeGenerateTask",
    "GENERATE_STATUSES",
    "GENERATE_ACTIVE_STATUSES",
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
    "JobMatchAnalysis",
    "ApplyQueueItem",
    "ApplyTask",
    "ApplyTaskItem",
    "MATCH_STATUSES",
    "ADMISSIONS",
    "HARD_GATES",
    "QUEUE_STATUSES",
    "TASK_KINDS",
    "TASK_STATUSES",
    "ITEM_STATUSES",
    "FAILURE_CATEGORIES",
    "FAILURE_CATEGORY_LABELS",
    "TASK_STEPS",
    "STOP_REASONS",
    "ClaimRecord",
    "CLAIM_CATEGORIES",
    "RESPONSIBILITY_LEVELS",
    "VERIFICATION_STATUSES",
    "ApplicationTrack",
    "STATUSES",
    "SOURCES",
    "DrillSession",
    "DrillContract",
    "DrillTurn",
    "EVIDENCE_STATUSES",
    "REHEARSE_KINDS",
    "DRILL_STATUS_ACTIVE",
    "DRILL_STATUS_FINISHED",
    "InterviewExperience",
    "EXPERIENCE_SOURCES",
    "EXPERIENCE_ROUND_TYPES",
    "InterviewReviewRecord",
    "KnowledgeEntry",
    "QuestionBankRecord",
    "Referral",
    "REFERRAL_STATUSES",
    "Reminder",
    "REMINDER_KINDS",
    "REMINDER_STATUSES",
    "SharePackage",
    "SHARE_PERMISSIONS",
]

"""个人资料相关模型：主表 + 各子表（教育/实习/校园/项目/技能/荣誉）。

日期统一用字符串（如 "2022.09"）：简历中的时间本就是展示文本，
避免日期解析带来的兼容性问题。多行文本（经历描述、项目亮点等）
以换行分隔存储，输入模型时再拆成列表。
"""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


def utcnow() -> datetime:
    """统一时间戳（无时区的 UTC），避免 SQLite 中带时区比较的坑。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    gender: Mapped[str] = mapped_column(String(16), default="")
    birth_year: Mapped[str] = mapped_column(String(16), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    city: Mapped[str] = mapped_column(String(64), default="")
    target_city: Mapped[str] = mapped_column(String(64), default="")
    job_intent: Mapped[str] = mapped_column(String(128), default="")  # 求职意向
    personal_website: Mapped[str] = mapped_column(String(256), default="")
    github: Mapped[str] = mapped_column(String(256), default="")
    photo: Mapped[str] = mapped_column(Text, default="")  # 受限的 base64 图片 data URL
    summary: Mapped[str] = mapped_column(Text, default="")  # 个人总结/自我评价
    section_order: Mapped[list[str]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    educations: Mapped[list["Education"]] = relationship(
        cascade="all, delete-orphan", order_by="Education.id"
    )
    experiences: Mapped[list["Experience"]] = relationship(
        cascade="all, delete-orphan", order_by="Experience.id"
    )
    campus_experiences: Mapped[list["CampusExperience"]] = relationship(
        cascade="all, delete-orphan", order_by="CampusExperience.id"
    )
    projects: Mapped[list["Project"]] = relationship(
        cascade="all, delete-orphan", order_by="Project.id"
    )
    skills: Mapped[list["Skill"]] = relationship(cascade="all, delete-orphan", order_by="Skill.id")
    awards: Mapped[list["Award"]] = relationship(cascade="all, delete-orphan", order_by="Award.id")
    photos: Mapped[list["ProfilePhoto"]] = relationship(
        cascade="all, delete-orphan", order_by="ProfilePhoto.id"
    )


class ProfilePhoto(Base):
    """可选择的多张个人照片。

    ``UserProfile.photo`` 仍然是"当前使用的那一张"的镜像：简历生成、预览与导出
    全部读它，因此切换照片时同步写回主表，老链路一行都不用改。
    """

    __tablename__ = "profile_photo"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("user_profile.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(128), default="")
    # 受限的 base64 图片 data URL，校验规则与资料照片完全一致。
    image: Mapped[str] = mapped_column(Text, default="")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Education(Base):
    __tablename__ = "education"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"))
    school: Mapped[str] = mapped_column(String(128), default="")
    major: Mapped[str] = mapped_column(String(128), default="")
    degree: Mapped[str] = mapped_column(String(32), default="")  # 本科/硕士/博士
    start_date: Mapped[str] = mapped_column(String(16), default="")
    end_date: Mapped[str] = mapped_column(String(16), default="")
    gpa: Mapped[str] = mapped_column(String(32), default="")  # 绩点/排名，如 "3.8/4.0"
    courses: Mapped[str] = mapped_column(Text, default="")  # 核心课程，换行分隔
    achievements: Mapped[str] = mapped_column(Text, default="")  # 在校成果，换行分隔
    reference_file_name: Mapped[str] = mapped_column(String(255), default="")
    reference_content: Mapped[str] = mapped_column(Text, default="")


class Experience(Base):
    __tablename__ = "experience"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"))
    company: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(128), default="")
    start_date: Mapped[str] = mapped_column(String(16), default="")
    end_date: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")  # 工作内容，换行分隔
    reference_file_name: Mapped[str] = mapped_column(String(255), default="")
    reference_content: Mapped[str] = mapped_column(Text, default="")


class CampusExperience(Base):
    __tablename__ = "campus_experience"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"))
    organization: Mapped[str] = mapped_column(String(128), default="")  # 学生会/班级/社团等
    role: Mapped[str] = mapped_column(String(128), default="")  # 职务或担任角色
    start_date: Mapped[str] = mapped_column(String(16), default="")
    end_date: Mapped[str] = mapped_column(String(16), default="")
    description: Mapped[str] = mapped_column(Text, default="")  # 经历描述，换行分隔
    reference_file_name: Mapped[str] = mapped_column(String(255), default="")
    reference_content: Mapped[str] = mapped_column(Text, default="")


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), default="")
    role: Mapped[str] = mapped_column(String(64), default="")
    start_date: Mapped[str] = mapped_column(String(16), default="")
    end_date: Mapped[str] = mapped_column(String(16), default="")
    tech_stack: Mapped[str] = mapped_column(String(256), default="")  # 逗号分隔
    description: Mapped[str] = mapped_column(Text, default="")  # 项目描述，换行分隔
    highlights: Mapped[str] = mapped_column(Text, default="")  # 亮点/成果，换行分隔
    reference_file_name: Mapped[str] = mapped_column(String(255), default="")
    reference_content: Mapped[str] = mapped_column(Text, default="")


class Skill(Base):
    __tablename__ = "skill"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(32), default="")  # 熟练/掌握/了解


class Award(Base):
    __tablename__ = "award"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("user_profile.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(128), default="")
    date: Mapped[str] = mapped_column(String(32), default="")
    description: Mapped[str] = mapped_column(String(256), default="")

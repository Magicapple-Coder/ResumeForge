"""个人资料业务逻辑：读取与整体更新（子表先删后插）。"""
from sqlalchemy.orm import Session, selectinload

from ...models.profile import (
    Award,
    CampusExperience,
    Education,
    Experience,
    Project,
    Skill,
    UserProfile,
)
from ...schemas.profile import ProfileOut, ProfileUpdate

# 子表名称 -> 模型类，用于统一处理列表替换
_SECTION_MODELS = {
    "educations": Education,
    "experiences": Experience,
    "campus_experiences": CampusExperience,
    "projects": Project,
    "skills": Skill,
    "awards": Award,
}


def get_or_create_profile(db: Session) -> UserProfile:
    """单用户应用：保证主表始终有一条记录。"""
    profile = db.query(UserProfile).first()
    if profile is None:
        profile = UserProfile()
        db.add(profile)
        db.flush()
    return profile


def get_profile_detail(db: Session) -> UserProfile:
    """读取带全部子表的资料。

    必须 selectinload：生成接口在异步上下文中使用该对象，
    懒加载会在事件循环线程里触发 MissingGreenlet 错误。
    """
    profile = get_or_create_profile(db)
    options = [selectinload(getattr(UserProfile, name)) for name in _SECTION_MODELS]
    return db.get(UserProfile, profile.id, options=options)


def update_profile(db: Session, payload: ProfileUpdate) -> UserProfile:
    """整体替换资料：基础字段逐个赋值，子表列表先删后插。"""
    profile = get_or_create_profile(db)
    section_payloads = {name: getattr(payload, name) for name in _SECTION_MODELS}
    basic_fields = payload.model_dump(exclude=set(_SECTION_MODELS))
    for field, value in basic_fields.items():
        setattr(profile, field, value)
    db.flush()  # 保证新记录先拿到 id，子表才能挂外键

    for name, model in _SECTION_MODELS.items():
        setattr(
            profile,
            name,
            [model(profile_id=profile.id, **item.model_dump()) for item in section_payloads[name]],
        )
    db.commit()
    return get_profile_detail(db)


def to_profile_out(profile: UserProfile) -> ProfileOut:
    return ProfileOut.model_validate(profile)

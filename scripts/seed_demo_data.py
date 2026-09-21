"""生成一份**纯虚构**的演示数据集，可选地把全部只读接口跑一遍做自检。

为什么需要它：README 与文档要放真实运行截图（不是示意图），而截图不能出现任何真实用户资料。
这个脚本负责造出那份"看起来像真在用、但没有一个字节是真的"的数据，并在写完之后**用应用自己的
接口逐个读一遍**——演示数据写坏 schema 的后果在真实用户那里表现为"某个页面打不开"，
所以这里宁可自己先撞一次墙。

用法（在仓库根目录执行）：

    backend\\.venv\\Scripts\\python.exe scripts\\seed_demo_data.py --check

默认写到 ``runtime/demo/demo.db``（``runtime/`` 已被 .gitignore 忽略）。
演示库请**用 DATABASE_URL 指向它单独启动一份后端**，不要覆盖 ``backend/data/resume_forge.db``：

    $env:DATABASE_URL = "sqlite:///D:/ResumeForge/runtime/demo/demo.db"
    backend\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --port 8123  # 在 backend 目录执行

``--check`` 需要 ``fastapi.testclient``（dev 依赖里已有）。不带它时只写数据、不起应用。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

DEFAULT_OUT = REPO_ROOT / "runtime" / "demo" / "demo.db"

# 演示数据里的日期以它为"现在"，让提醒有逾期/今天/未来的分布。固定值而不是 now()：
# 否则同一份脚本每天跑出来的截图都不一样，diff 里全是不该有的变化。
NOW = datetime(2026, 9, 21, 8, 30, 0)


def _preparse_out() -> Path:
    """在导入 app 之前把 ``--out`` 读出来。

    ``app.config`` 在**导入时**就通过 ``get_settings()`` 定下 ``database_url``（进程内缓存），
    所以环境变量必须先设好、后导入——顺序反了就还是会写到默认库上。
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    known, _ = parser.parse_known_args()
    return Path(known.out).expanduser().resolve()


DB_PATH = _preparse_out()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.as_posix()

from sqlalchemy import create_engine, insert  # noqa: E402

from app.database import Base  # noqa: E402
from app.models import __init__ as _models  # noqa: E402,F401
from app.services.jd_parser import parse_jd  # noqa: E402
from app.services.resume_sample import sample_resume_content  # noqa: E402


def keywords_of(job: dict) -> list[dict]:
    """用应用自己的 JD 解析器生成技能标签，避免手写一份和词表不一致的。"""
    text = "\n".join([job["description"], job["requirements"], job["additional_info"]])
    return [tag.model_dump() for tag in parse_jd(text)["skills"]]


T = Base.metadata.tables
engine = create_engine("sqlite:///" + DB_PATH.as_posix())

# 先 drop 再 create，而不是先删文件：删文件在开发机上会撞"文件被运行中的后端占用"，
# 也会在某些环境里被删除守卫拦下，而 drop_all 对同一个文件同样能得到一份干净的库。
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


def row(**kw):
    return kw


def ins(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    with engine.begin() as conn:
        conn.execute(insert(T[table]), rows)


# ── 个人资料 ────────────────────────────────────────────────────────────────
ins(
    "user_profile",
    [
        row(
            id=1,
            name="张示例",
            gender="女",
            birth_year="2001",
            phone="138-0000-0000",
            email="zhang.example@example.com",
            city="上海",
            target_city="上海",
            job_intent="市场运营专员",
            personal_website="https://example.com/zhang",
            github="",
            photo="",
            summary=(
                "3 年市场与运营经验，主导过从 0 到 1 的会员增长项目，"
                "擅长把一次性的活动经验沉淀成可复用的流程。"
            ),
            section_order=["education", "experience", "projects", "campus", "skills", "awards"],
            updated_at=NOW,
        )
    ],
)

ins(
    "education",
    [
        row(
            profile_id=1,
            school="示例大学",
            major="市场营销",
            degree="本科",
            start_date="2019.09",
            end_date="2023.06",
            gpa="3.7/4.0",
            courses="市场调研；消费者行为；应用统计",
            achievements="连续两年获得校级奖学金",
            reference_file_name="",
            reference_content="",
        )
    ],
)

ins(
    "experience",
    [
        row(
            profile_id=1,
            company="示例科技有限公司",
            role="市场运营专员",
            start_date="2023.07",
            end_date="至今",
            description=(
                "- 主导季度主题营销活动，参与人数 1.2 万，活动转化率环比提升 18%。\n"
                "- 把活动复盘模板沉淀成 SOP，团队复用后单场筹备时间从 10 天压缩到 4 天。\n"
                "- 对接 12 家外部渠道并建立效果台账，年度渠道成本下降 15%。"
            ),
            reference_file_name="市场运营工作小结.md",
            reference_content="# 季度活动复盘\n\n- 参与人数：12,400\n- 转化率：7.2%（环比 +18%）\n",
        ),
        row(
            profile_id=1,
            company="示例文化传播有限公司",
            role="市场部实习生",
            start_date="2022.06",
            end_date="2022.12",
            description="- 负责社群日常维护与内容排期，月均产出 20 篇内容，粉丝净增 3000。",
            reference_file_name="",
            reference_content="",
        ),
    ],
)

ins(
    "project",
    [
        row(
            profile_id=1,
            name="校园招聘会策划",
            role="项目负责人",
            start_date="2024.03",
            end_date="2024.06",
            tech_stack="活动策划,渠道对接,预算管理",
            description="- 从 0 到 1 策划校园招聘会，到会企业 40 家、学生 1200 人。",
            highlights="- 用分时段报名数据调度入场，把现场排队时间控制在 10 分钟以内。",
            reference_file_name="",
            reference_content="",
        )
    ],
)

ins(
    "skill",
    [
        row(profile_id=1, name="活动策划", level="熟练"),
        row(profile_id=1, name="Excel", level="熟练"),
        row(profile_id=1, name="数据复盘", level="掌握"),
        row(profile_id=1, name="沟通协作", level="熟练"),
        row(profile_id=1, name="商务英语", level="了解"),
    ],
)

ins(
    "award",
    [
        row(profile_id=1, name="示例大学一等奖学金", date="2021.10", description=""),
        row(profile_id=1, name="校级优秀学生干部", date="2021.05", description=""),
    ],
)

# ── 岗位 ────────────────────────────────────────────────────────────────────
JOBS = [
    dict(
        title="市场运营专员",
        company="示例科技（上海）有限公司",
        location="上海·徐汇区",
        salary="15-25K·13薪",
        job_type="全职",
        source="BOSS直聘",
        source_url="https://www.zhipin.com/job_detail/demo0001.html",
        posted_at="2026-09-18",
        favorite=True,
        keywords=["活动策划", "用户增长", "数据分析", "跨部门协作"],
        description=(
            "1. 负责品牌营销活动的策划与执行，对活动参与人数与转化率负责；\n"
            "2. 搭建活动复盘机制，把有效做法沉淀为可复用 SOP；\n"
            "3. 对接外部渠道并维护渠道效果台账。"
        ),
        requirements=(
            "1. 本科及以上，市场营销、新闻传播等相关专业优先；\n"
            "2. 2 年以上市场活动或用户运营经验；\n"
            "3. 熟练使用 Excel，能做基础数据复盘；\n"
            "4. 有跨部门协作与供应商管理经验。"
        ),
        additional_info="五险一金、补充医疗、年度调薪、弹性上班",
        note="猎头推荐，先聊了岗位方向",
    ),
    dict(
        title="新媒体运营",
        company="示例文化传媒有限公司",
        location="杭州·西湖区",
        salary="12-18K",
        job_type="全职",
        source="BOSS直聘",
        source_url="https://www.zhipin.com/job_detail/demo0002.html",
        posted_at="2026-09-17",
        favorite=False,
        keywords=["内容运营", "短视频", "社群运营"],
        description="负责官方新媒体账号的内容排期与日常运营，跟踪内容数据并优化选题。",
        requirements="1. 1 年以上新媒体运营经验；\n2. 有短视频脚本与剪辑经验优先；\n3. 对数据敏感，能用数据解释选题结果。",
        additional_info="双休",
        note="",
    ),
    dict(
        title="品牌营销专员",
        company="示例日化有限公司",
        location="广州·天河区",
        salary="14-20K",
        job_type="全职",
        source="招聘网站",
        source_url="",
        posted_at="2026-09-15",
        favorite=False,
        keywords=["品牌传播", "媒介投放", "预算管理"],
        description="参与年度品牌传播计划，负责媒介投放的排期、执行与效果复盘。",
        requirements="1. 本科及以上；\n2. 熟悉主流社交平台投放逻辑；\n3. 有预算管理经验。",
        additional_info="",
        note="来源是朋友转发的招聘信息",
    ),
    dict(
        title="用户增长运营",
        company="示例网络科技有限公司",
        location="北京·海淀区",
        salary="20-30K",
        job_type="全职",
        source="BOSS直聘",
        source_url="https://www.zhipin.com/job_detail/demo0004.html",
        posted_at="2026-09-19",
        favorite=True,
        keywords=["用户增长", "A/B 测试", "数据分析", "会员体系"],
        description="负责会员体系的拉新与留存，设计并落地增长实验。",
        requirements="1. 3 年以上用户运营或增长经验；\n2. 能独立设计并复盘 A/B 实验；\n3. 熟悉 SQL 优先。",
        additional_info="股票期权",
        note="",
    ),
    dict(
        title="内容运营（校招）",
        company="示例在线教育有限公司",
        location="上海·浦东新区",
        salary="10-15K",
        job_type="校招",
        source="BOSS直聘",
        source_url="https://www.zhipin.com/job_detail/demo0005.html",
        posted_at="2026-09-12",
        favorite=False,
        keywords=["内容运营", "文案", "用户调研"],
        description="参与课程内容的选题与生产，配合活动做内容排期。",
        requirements="1. 2027 届本科及以上；\n2. 有校园媒体或自媒体运营经历；\n3. 文字表达清晰。",
        additional_info="",
        note="",
    ),
    dict(
        title="活动策划专员",
        company="示例文创发展有限公司",
        location="成都·武侯区",
        salary="10-16K",
        job_type="全职",
        source="手动录入",
        source_url="",
        posted_at="2026-09-10",
        favorite=False,
        keywords=["线下活动", "供应商管理", "预算管理"],
        description="负责线下文创活动的策划、执行与现场统筹。",
        requirements="1. 2 年以上线下活动执行经验；\n2. 能接受项目期出差。",
        additional_info="",
        note="",
    ),
]

job_ids: list[int] = []
ins(
    "job",
    [
        row(
            id=i + 1,
            title=j["title"],
            company=j["company"],
            location=j["location"],
            salary=j["salary"],
            job_type=j["job_type"],
            description=j["description"],
            requirements=j["requirements"],
            additional_info=j["additional_info"],
            keywords=keywords_of(j),
            source=j["source"],
            source_url=j["source_url"],
            posted_at=j["posted_at"],
            status="active",
            note=j["note"],
            note_images=[],
            favorite=j["favorite"],
            recognition_source="text",
            created_at=NOW - timedelta(days=6 - i),
            updated_at=NOW - timedelta(days=6 - i),
        )
        for i, j in enumerate(JOBS)
    ],
)
job_ids = [i + 1 for i in range(len(JOBS))]

# ── 备选岗位 ────────────────────────────────────────────────────────────────
ins(
    "candidate_job",
    [
        row(
            id=1,
            title="市场专员",
            company="示例供应链有限公司",
            raw_text="市场专员 / 示例供应链有限公司 / 上海 / 13-18K",
            images=[],
            note="从招聘信息里复制的，还没核对",
            source="manual",
            job_type="全职",
            location="上海",
            salary="13-18K",
            source_url="",
            description="",
            requirements="",
            additional_info="",
            collect_task_id=None,
            status="pending",
            imported_job_id=None,
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=2),
        ),
        row(
            id=2,
            title="运营助理",
            company="示例贸易有限公司",
            raw_text="运营助理 / 示例贸易有限公司 / 苏州 / 8-12K",
            images=[],
            note="招聘会现场拍的展板，待整理",
            source="manual",
            job_type="全职",
            location="苏州",
            salary="8-12K",
            source_url="",
            description="",
            requirements="",
            additional_info="",
            collect_task_id=None,
            status="pending",
            imported_job_id=None,
            created_at=NOW - timedelta(days=5),
            updated_at=NOW - timedelta(days=5),
        ),
    ],
)

# ── 简历 ────────────────────────────────────────────────────────────────────
base_content = sample_resume_content().model_dump()


def resume_content(intent: str, summary: str) -> dict:
    data = dict(base_content)
    data["job_intent"] = intent
    data["summary"] = summary
    return data


RESUMES = [
    dict(
        id=1,
        title="市场运营专员 - 示例科技（上海）有限公司",
        job_id=1,
        job_title=JOBS[0]["title"],
        company=JOBS[0]["company"],
        content=resume_content(
            "市场运营专员",
            "3 年市场与运营经验，主导季度主题营销活动，参与人数 1.2 万、转化率环比提升 18%；"
            "擅长把活动经验沉淀为可复用 SOP。",
        ),
        source="ai",
        favorite=True,
        tone="",
        enhancement_enabled=True,
        enhancement_level="strong",
        template="modern",
        format_name="compact",
        format_config={},
        page_limit=1,
        font_scale="standard",
        custom_instruction="突出活动转化率与流程沉淀",
        note="投递示例科技用，重点写转化率",
        created_at=NOW - timedelta(days=3),
    ),
    dict(
        id=2,
        title="用户增长运营 - 示例网络科技有限公司",
        job_id=4,
        job_title=JOBS[3]["title"],
        company=JOBS[3]["company"],
        content=resume_content(
            "用户增长运营",
            "3 年运营经验，做过会员拉新与留存实验，习惯用数据解释结论。",
        ),
        source="manual",
        favorite=False,
        tone="",
        enhancement_enabled=False,
        enhancement_level="balanced",
        template="classic",
        format_name="standard",
        format_config={},
        page_limit=2,
        font_scale="standard",
        custom_instruction="",
        note="",
        created_at=NOW - timedelta(days=1),
    ),
    dict(
        id=3,
        title="通用简历（市场 / 运营方向）",
        job_id=None,
        job_title="",
        company="",
        content=resume_content("市场 / 运营方向", "跨行业的通用版本，方向未定时使用。"),
        source="manual",
        favorite=True,
        tone="",
        enhancement_enabled=False,
        enhancement_level="balanced",
        template="elegant",
        format_name="spacious",
        format_config={},
        page_limit=1,
        font_scale="standard",
        custom_instruction="",
        note="通用版，先投不明确方向的岗位",
        created_at=NOW - timedelta(days=8),
    ),
]
ins(
    "resume_record",
    [
        row(
            **r,
            warnings=[],
            model="" if r["source"] == "manual" else "deepseek-chat",
            parse_error="",
            deleted_at=None,
        )
        for r in RESUMES
    ],
)

# ── 事实台账 ────────────────────────────────────────────────────────────────
ins(
    "claim_record",
    [
        row(
            id=1,
            title="季度主题营销活动参与人数 1.2 万",
            category="实习/工作",
            subject="示例科技有限公司 / 市场运营专员",
            source_fact="活动后台报名数据：12,400 人，活动结案报告里有截图。",
            candidate_wording="主导季度主题营销活动，参与人数 1.2 万。",
            sources=[],
            responsibility_level="主导方案或交付",
            verification_status="已确认",
            allowed_uses=["resume", "interview"],
            interview_details={
                "decisions": ["报名口径包含重复报名吗", "1.2 万是报名数还是到场数"],
                "difficulties": ["增长主要来自哪一波渠道"],
                "verification": ["活动后台导出数据", "结案报告截图"],
                "result": None,
            },
            boundary="不含线下到场人数，到场约 6,000。",
            risk_notes=[],
            last_verified="2026-09-18",
            created_at=NOW - timedelta(days=12),
            updated_at=NOW - timedelta(days=3),
        ),
        row(
            id=2,
            title="活动转化率环比提升 18%",
            category="实习/工作",
            subject="示例科技有限公司 / 市场运营专员",
            source_fact="结案报告对比上一季度：7.2% vs 6.1%。",
            candidate_wording="活动转化率环比提升 18%。",
            sources=[],
            responsibility_level="负责模块",
            verification_status="已确认",
            allowed_uses=["resume", "interview"],
            interview_details={
                "decisions": ["环比基数为什么低", "增长来自哪一步"],
                "difficulties": [],
                "verification": ["结案报告对比数据"],
                "result": None,
            },
            boundary="单一渠道口径，不含付费投放。",
            risk_notes=[],
            last_verified="2026-09-18",
            created_at=NOW - timedelta(days=12),
            updated_at=NOW - timedelta(days=3),
        ),
        row(
            id=3,
            title="渠道成本下降 15%",
            category="实习/工作",
            subject="示例科技有限公司 / 市场运营专员",
            source_fact="渠道台账里单条线索成本从 42 元降到 35 元。",
            candidate_wording="对接 12 家外部渠道，年度渠道成本下降 15%。",
            sources=[],
            responsibility_level="参与",
            verification_status="待确认",
            allowed_uses=["resume"],
            interview_details={
                "decisions": ["降本靠砍量还是压价"],
                "difficulties": ["口径还没和财务对齐"],
                "verification": [],
                "result": None,
            },
            boundary="尚未与财务口径对齐，先不写进简历。",
            risk_notes=["口径未对齐"],
            last_verified="",
            created_at=NOW - timedelta(days=9),
            updated_at=NOW - timedelta(days=9),
        ),
    ],
)

# ── 资料箱 ──────────────────────────────────────────────────────────────────
ins(
    "material",
    [
        row(
            id=1,
            title="新媒体运营结业证书",
            category="证书",
            content="2024 年 3 月取得，课程包含内容选题、数据复盘与投放基础。",
            url="",
            files=[],
            note="扫描件放在本地网盘",
            created_at=NOW - timedelta(days=20),
            updated_at=NOW - timedelta(days=20),
            deleted_at=None,
        ),
        row(
            id=2,
            title="季度活动结案报告（脱敏版）",
            category="作品",
            content="3 场主题活动的目标、执行路径与结果对比，已去掉内部数据。",
            url="https://example.com/portfolio/campaign-review",
            files=[],
            note="面试时可现场讲",
            created_at=NOW - timedelta(days=14),
            updated_at=NOW - timedelta(days=14),
            deleted_at=None,
        ),
        row(
            id=3,
            title="面试常用链接",
            category="链接",
            content="作品集、行业报告与常用数据源，面试前会过一遍。",
            url="https://example.com/links",
            files=[],
            note="",
            created_at=NOW - timedelta(days=6),
            updated_at=NOW - timedelta(days=6),
            deleted_at=None,
        ),
    ],
)

# ── 知识库 ──────────────────────────────────────────────────────────────────
ins(
    "knowledge_entry",
    [
        row(
            id=1,
            title="运营岗面试常被追问的三件事",
            category="面试问答",
            tags=["面试", "运营"],
            content=(
                "1. **数据口径**：只要说了数字，一定会被问「这个数怎么统计的」。\n"
                "2. **你的贡献**：团队做的事情里，哪一部分是你独立完成的。\n"
                "3. **失败经历**：讲一次效果不好的活动，重点在你后来改了什么。\n"
            ),
            source="",
            created_at=NOW - timedelta(days=10),
            updated_at=NOW - timedelta(days=10),
            deleted_at=None,
        ),
        row(
            id=2,
            title="简历里数字怎么写才站得住",
            category="简历技巧",
            tags=["简历", "量化"],
            content=(
                "写数字之前先确认三件事：口径、来源、你的角色。\n\n"
                "口径不清的数字不如不写——面试时第一个被追问的就是它。\n"
            ),
            source="",
            created_at=NOW - timedelta(days=7),
            updated_at=NOW - timedelta(days=7),
            deleted_at=None,
        ),
        row(
            id=3,
            title="求职节奏：每周固定复盘一次",
            category="求职策略",
            tags=["节奏", "复盘"],
            content=(
                "- 周一：更新岗位池，把上周的备选岗位核对进正式岗位。\n"
                "- 周三：投递 + 跟进未回复的岗位。\n"
                "- 周五：复盘本周投递转化，调整下一周的目标公司名单。\n"
            ),
            source="",
            created_at=NOW - timedelta(days=4),
            updated_at=NOW - timedelta(days=4),
            deleted_at=None,
        ),
    ],
)

# ── 面试经验 ────────────────────────────────────────────────────────────────
ins(
    "interview_experience",
    [
        row(
            id=1,
            title="示例科技 市场运营专员 一面",
            company="示例科技（上海）有限公司",
            position="市场运营专员",
            job_id=1,
            content="整体偏行为面，重点问活动数据和跨部门协作方式。面试官很关注口径。",
            questions=[
                "介绍一下你主导过的一次活动，目标是什么？",
                "1.2 万这个报名数是怎么统计的，含重复报名吗？",
                "活动里你和设计、研发怎么分工？",
                "如果预算砍一半，你会怎么安排？",
            ],
            tags=["行为面", "数据"],
            source="self",
            difficulty="中级",
            round_type="一面",
            interview_date="2026-09-16",
            created_at=NOW - timedelta(days=5),
            updated_at=NOW - timedelta(days=5),
            deleted_at=None,
        ),
        row(
            id=2,
            title="示例网络科技 用户增长运营 二面",
            company="示例网络科技有限公司",
            position="用户增长运营",
            job_id=4,
            content="偏案例，现场给了一个留存下跌的场景，要求说出排查顺序。",
            questions=[
                "留存突然跌了 5 个百分点，你的排查顺序是什么？",
                "怎么设计一次 A/B 实验验证你的假设？",
                "过去做过哪次实验是失败的？",
            ],
            tags=["案例面", "增长"],
            source="peer",
            difficulty="高级",
            round_type="二面",
            interview_date="2026-09-19",
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=2),
            deleted_at=None,
        ),
    ],
)

# ── 求职进度 ────────────────────────────────────────────────────────────────
ins(
    "application_track",
    [
        row(
            id=1,
            company=JOBS[0]["company"],
            title=JOBS[0]["title"],
            company_key="示例科技",
            title_key="市场运营专员",
            status="interview",
            stage_note="一面已过，等二面通知",
            applied_at="2026-09-15",
            status_date="2026-09-19",
            next_action="准备二面的案例题",
            next_action_date="2026-09-23",
            note="猎头推荐的岗位",
            evidence="9/19 收到一面反馈邮件",
            job_id=1,
            resume_id=1,
            source="manual",
            created_at=NOW - timedelta(days=6),
            updated_at=NOW - timedelta(days=2),
            deleted_at=None,
        ),
        row(
            id=2,
            company=JOBS[3]["company"],
            title=JOBS[3]["title"],
            company_key="示例网络",
            title_key="用户增长运营",
            status="screening",
            stage_note="简历已过初筛",
            applied_at="2026-09-18",
            status_date="2026-09-20",
            next_action="等 HR 约面",
            next_action_date="2026-09-22",
            note="",
            evidence="9/20 收到测评邀请",
            job_id=4,
            resume_id=2,
            source="manual",
            created_at=NOW - timedelta(days=3),
            updated_at=NOW - timedelta(days=1),
            deleted_at=None,
        ),
        row(
            id=3,
            company=JOBS[1]["company"],
            title=JOBS[1]["title"],
            company_key="示例文化",
            title_key="新媒体运营",
            status="rejected",
            stage_note="岗位暂停招聘",
            applied_at="2026-09-10",
            status_date="2026-09-14",
            next_action="",
            next_action_date="",
            note="",
            evidence="9/14 收到婉拒邮件",
            job_id=2,
            resume_id=None,
            source="manual",
            created_at=NOW - timedelta(days=11),
            updated_at=NOW - timedelta(days=7),
            deleted_at=None,
        ),
    ],
)

# ── 内推 ────────────────────────────────────────────────────────────────────
ins(
    "referral",
    [
        row(
            id=1,
            job_id=4,
            job_title=JOBS[3]["title"],
            company=JOBS[3]["company"],
            referrer_name="李示例",
            referrer_contact="li.example@example.com",
            relation="前同事",
            position="运营经理",
            channel="同事",
            status="submitted",
            track_id=2,
            converted=False,
            submitted_at="2026-09-18",
            note="说可以帮忙看简历",
            referral_code="REF-DEMO-01",
            note_images=[],
            created_at=NOW - timedelta(days=5),
            updated_at=NOW - timedelta(days=3),
            deleted_at=None,
        ),
        row(
            id=2,
            job_id=None,
            job_title="品牌营销专员",
            company="示例日化有限公司",
            referrer_name="王示例",
            referrer_contact="wang.example@example.com",
            relation="校友",
            position="市场主管",
            channel="校友",
            status="active",
            track_id=None,
            converted=False,
            submitted_at="",
            note="还在确认有没有岗位名额",
            referral_code="",
            note_images=[],
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=2),
            deleted_at=None,
        ),
    ],
)

# ── 提醒 ────────────────────────────────────────────────────────────────────
reminders = [
    ("示例科技 二面", 1, "interview", 1, "明天 14:00 线上面试，提前 15 分钟进会议室"),
    ("用户增长运营 测评截止", 2, "assessment_deadline", 2, "测评链接有效期 48 小时"),
    ("给李示例回消息", 1, "hr_reply", 2, "确认内推进度"),
    ("准备案例题", 3, "other", 1, "复习留存下跌的排查顺序"),
]
ins(
    "reminder",
    [
        row(
            id=i + 1,
            title=title,
            remind_at=NOW + timedelta(days=delta),
            kind=kind,
            status="pending",
            track_id=track,
            job_id=None,
            resume_id=None,
            note=note,
            created_at=NOW - timedelta(days=1),
            updated_at=NOW - timedelta(days=1),
            deleted_at=None,
        )
        for i, (title, delta, kind, track, note) in enumerate(reminders)
    ],
)

# ── 投递队列 + 批次历史 ─────────────────────────────────────────────────────
queue_rows = []
for i, jid in enumerate([1, 4, 5]):
    job = JOBS[jid - 1]
    queue_rows.append(
        row(
            id=i + 1,
            job_id=jid,
            job_title=job["title"],
            company=job["company"],
            resume_id=1 if jid != 4 else 2,
            greeting=f"您好，我在{job['title']}方向有 3 年经验，方便聊聊这个岗位吗？",
            sort_order=i,
            status="pending",
            created_at=NOW - timedelta(hours=6),
            updated_at=NOW - timedelta(hours=6),
        )
    )
ins("apply_queue_item", queue_rows)

ins(
    "apply_task",
    [
        row(
            id=1,
            kind="apply",
            status="completed",
            total=2,
            processed=2,
            succeeded=1,
            failed=0,
            skipped=1,
            current_step="idle",
            stop_reason="done",
            config={"limit_per_task": 5, "interval_seconds": 45},
            message="已完成",
            started_at=NOW - timedelta(days=2, hours=1),
            finished_at=NOW - timedelta(days=2),
            created_at=NOW - timedelta(days=2, hours=1),
        ),
        row(
            id=2,
            kind="collect",
            status="completed",
            total=1,
            processed=1,
            succeeded=1,
            failed=0,
            skipped=0,
            current_step="idle",
            stop_reason="done",
            config={"query": "市场运营", "city": "上海", "pages": 3},
            message="已完成",
            started_at=NOW - timedelta(days=4),
            finished_at=NOW - timedelta(days=4),
            created_at=NOW - timedelta(days=4),
        ),
    ],
)

ins(
    "apply_task_item",
    [
        row(
            id=1,
            task_id=1,
            job_id=1,
            job_title=JOBS[0]["title"],
            company=JOBS[0]["company"],
            resume_id=1,
            resume_title=RESUMES[0]["title"],
            greeting="您好，我在市场运营方向有 3 年经验，方便聊聊这个岗位吗？",
            status="success",
            failure_category="",
            failure_detail="",
            attempt=1,
            sort_order=0,
            started_at=NOW - timedelta(days=2, minutes=50),
            finished_at=NOW - timedelta(days=2, minutes=48),
            created_at=NOW - timedelta(days=2, hours=1),
        ),
        row(
            id=2,
            task_id=1,
            job_id=4,
            job_title=JOBS[3]["title"],
            company=JOBS[3]["company"],
            resume_id=2,
            resume_title=RESUMES[1]["title"],
            greeting="",
            status="skipped",
            failure_category="",
            failure_detail="按「同公司只投一个岗位」跳过：本批次已经投过「示例网络科技有限公司」的岗位。",
            attempt=0,
            sort_order=1,
            started_at=NOW - timedelta(days=2, minutes=47),
            finished_at=NOW - timedelta(days=2, minutes=47),
            created_at=NOW - timedelta(days=2, hours=1),
        ),
    ],
)

# ── 模型配置（演示用占位，密钥是假的） ──────────────────────────────────────
import json  # noqa: E402

ins(
    "app_setting",
    [
        row(
            key="llm_config",
            value=json.dumps(
                {
                    "provider": "deepseek",
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "",
                    "model": "deepseek-chat",
                    "temperature": 0.1,
                    "timeout_seconds": 120,
                    "max_tokens": 0,
                    "api_style": "openai",
                    "top_p": None,
                    "frequency_penalty": None,
                    "presence_penalty": None,
                    "seed": None,
                    "top_k": None,
                    "repetition_penalty": None,
                    "stop": [],
                    "thinking_budget": None,
                    "extra_body": {},
                },
                ensure_ascii=False,
            ),
        ),
        row(key="reminder_popup_on_start", value=json.dumps(False)),
    ],
)

# ── 求职助手会话 ────────────────────────────────────────────────────────────
ins(
    "chat_conversation",
    [
        row(
            id=1,
            title="市场运营岗的简历重点怎么放",
            pinned=True,
            favorite=True,
            archived=False,
            group_name="简历",
            created_at=NOW - timedelta(days=2),
            updated_at=NOW - timedelta(days=2),
            deleted_at=None,
        )
    ],
)
ins(
    "chat_message",
    [
        row(
            conversation_id=1,
            role="user",
            content="我现在有 3 个市场运营方向的岗位在谈，简历里最该突出什么？",
            quoted_message_id=None,
            attachments=[],
            context={"job_ids": [1]},
            status="complete",
            error="",
            model="",
            created_at=NOW - timedelta(days=2, minutes=10),
        ),
        row(
            conversation_id=1,
            role="assistant",
            content=(
                "按你的台账，可核对的只有「活动参与人数 1.2 万」和「转化率环比 +18%」，"
                "这两条应该放在第一段经历的最前面，并写清口径。\n\n"
                "至于「渠道成本下降 15%」，台账里还是「待确认」，建议先不写——"
                "面试官一定会问统计口径。"
            ),
            quoted_message_id=None,
            attachments=[],
            context={},
            status="complete",
            error="",
            model="deepseek-chat",
            created_at=NOW - timedelta(days=2, minutes=9),
        ),
    ],
)

# ── 助手技能 ────────────────────────────────────────────────────────────────
ins(
    "assistant_skill",
    [
        row(
            id=1,
            name="面试官视角挑刺",
            description="用面试官视角逐条质疑简历里的说法，指出可能被追问的点",
            prompt=(
                "你现在是一位严格的面试官。请针对我给出的简历内容逐条提问，"
                "优先追问数字口径、我的个人贡献与失败经历。不要给我鼓励。"
            ),
            enabled=True,
            source_name="",
            created_at=NOW - timedelta(days=15),
            updated_at=NOW - timedelta(days=15),
        ),
        row(
            id=2,
            name="JD 关键词对齐",
            description="把岗位 JD 的关键词和我的资料逐条对齐，标出缺口",
            prompt="请读取岗位 JD 与我的个人资料，逐条列出：已覆盖、表达缺口、真实缺口。",
            enabled=True,
            source_name="",
            created_at=NOW - timedelta(days=8),
            updated_at=NOW - timedelta(days=8),
        ),
    ],
)

CHECKS = [
    "/api/health",
    "/api/profile",
    "/api/profile/photos",
    "/api/jobs?page=1&page_size=10",
    "/api/jobs/1",
    "/api/jobs/1/match-analysis",
    "/api/candidate-jobs",
    "/api/candidate-jobs/1",
    "/api/resumes?page=1&page_size=10",
    "/api/resumes/1",
    "/api/resumes/1/export?format=html",
    "/api/resumes/templates",
    "/api/resume-templates",
    "/api/resume-templates/builtin",
    "/api/claims",
    "/api/claims/baseline",
    "/api/claims/1",
    "/api/materials",
    "/api/materials/categories",
    "/api/materials/1",
    "/api/knowledge",
    "/api/knowledge/categories",
    "/api/knowledge/1",
    "/api/tracker",
    "/api/tracker/export?format=csv",
    "/api/reminders",
    "/api/reminders/upcoming?limit=8",
    "/api/referrals",
    "/api/referrals/stats",
    "/api/interview",
    "/api/interview-experiences",
    "/api/interview-experiences/sources",
    "/api/interview/question-banks",
    "/api/interview/reviews",
    "/api/drill",
    "/api/assistant/conversations?limit=100",
    "/api/assistant/conversations/1",
    "/api/assistant/skills",
    "/api/apply/queue",
    "/api/apply/records?page=1&page_size=10",
    "/api/apply/records/grouped?page=1&page_size=10",
    "/api/apply/tasks",
    "/api/apply/tasks/current",
    "/api/apply/sites",
    "/api/apply/config",
    "/api/apply/browser/status",
    "/api/collect/config",
    # 刻意不查 /api/collect/filters 与 /api/collect/site-health：前者会去站点取筛选选项
    # （读登录会话 → 全网通用清单 → 内置快照），跑一次十几秒；后者探测站点可达性。
    # 这个自检要抓的是"演示数据不符合 schema"，不需要联网，跑得快才有人愿意跑。
    "/api/share-packages",
    "/api/trash",
    "/api/settings/llm",
    "/api/settings/llm/records",
    "/api/settings/search",
    "/api/settings/reminder-popup",
    "/api/stats",
    "/api/analytics/dashboard?trend_months=6",
    "/api/search?q=运营",
]


def run_checks() -> int:
    """把只读接口挨个读一遍，返回失败条数。

    这里换成一个真正的 HTTP 客户端不合适（要么起服务、要么暴露端口），TestClient 走的是同一套
    路由与同一个序列化层，schema 不匹配一样会 500——而"演示数据不符合 schema"正是要抓的东西。
    """
    from fastapi.testclient import TestClient  # noqa: PLC0415

    from app.main import app  # noqa: PLC0415

    client = TestClient(app, raise_server_exceptions=False)
    failures: list[str] = []
    for path in CHECKS:
        response = client.get(path)
        if response.status_code >= 400:
            failures.append(f"{response.status_code} {path} :: {response.text[:200]}")
    if failures:
        print("演示数据自检未通过：")
        for item in failures:
            print("  " + item.replace("\n", " "))
        return len(failures)
    print(f"演示数据自检通过：{len(CHECKS)} 个只读接口全部正常。")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成纯虚构的演示数据集")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="演示库的输出路径")
    parser.add_argument("--check", action="store_true", help="写完后把只读接口跑一遍自检")
    arguments = parser.parse_args()

    print(f"演示数据集已写入 {DB_PATH}")
    if DB_PATH != Path(arguments.out).expanduser().resolve():
        # --out 与 DB_PATH 理应一致；不一致说明"先解析再导入"的顺序被改坏了。
        print(
            f"警告：实际写入路径 {DB_PATH} 与 --out {arguments.out} 不一致。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if arguments.check:
        raise SystemExit(run_checks())

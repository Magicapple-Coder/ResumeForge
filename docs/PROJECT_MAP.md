# 项目导航图（Code Map）

> 一份"从功能倒查代码"的地图。想改某个功能、某个界面，或想搞清楚一段逻辑时，从这里出发。
> 深层的设计决策、数据流与踩坑记录见 [architecture.md](architecture.md)，本文件只回答**"该去哪找"**。

## 三条导航原则

项目是严格的三层结构，任何功能都按同一条路走。记住这三条，就不会迷路：

1. **界面在前端 `pages/`，路由在 `App.tsx` 的 `MENU_ITEMS`。** 想改页面外观 → 先找对应的 `pages/XxxPage.tsx`。
2. **HTTP 契约在后端 `api/`。** 想改接口返回 → 找 `backend/app/api/xxx.py`，它只做"校验参数 → 调服务 → 组装响应"。
3. **真正的逻辑在 `services/`。** 想改算法、规则、业务判断 → 都在这里，与 FastAPI 框架解耦，可离线测试。

一句话总结请求的流转：

```
页面组件 ──前端封装 api/*.ts──▶ FastAPI 路由 api/*.py ──▶ 业务逻辑 services/*.py ──▶ ORM models/*.py ──▶ SQLite
```

前端从不直接拼 URL（都经 `frontend/src/api/` 统一封装），后端路由从不写业务（都下沉到 `services/`）。这是整个项目最重要的约定。

## 功能 → 代码 倒查表

按侧栏菜单顺序排列。每个功能一行，横向就是它"从前到后"的完整链路。

| 功能 | 前端页面 | 前端 API 封装 | 后端路由前缀 | 核心业务逻辑 | 数据表（models/） |
| ---- | ---- | ---- | ---- | ---- | ---- |
| 首页 | `pages/HomePage.tsx` | `analytics.ts` `reminders.ts` | `/api/stats` `/api/analytics` `/api/reminders` | `analytics.py` `reminder_service.py` | 只读派生 |
| 岗位广场 | `pages/JobsPage.tsx` | `jobs.ts` | `/api/jobs` | `job/job_service.py` `jd/jd_parser*.py` `job/job_analysis.py` `text_extraction.py` | `job.py` |
| 官网采集 | `pages/OfficialPage.tsx` | `official.ts` | `/api/official` | `services/sites/official/*`（probe 探测 / feeds 适配器 / generic 通用抽取与配方 / reconcile 对账 / collector 编排 / discovery 公司发现） | `official.py` |
| 收藏夹 | `pages/FavoritesPage.tsx` | `jobs.ts` `resumes.ts` | `/api/jobs` `/api/resumes` | 复用 `job/job_service.py` / 简历服务 | `job.py` `resume.py` |
| 简历中心 | `pages/ResumesPage.tsx` | `resumes.ts` `resumeTemplates.ts` `resumeWriting.ts` `resumeRisk.ts` | `/api/resumes` `/api/resume-templates` | `resume/resume_generator.py` `resume/resume_content.py` `resume/resume_grounding.py` `resume/resume_layout.py` `pdf_exporter.py` `docx_exporter.py` `export_pipeline.py` | `resume.py` `resume_template.py` |
| 投递台 | `pages/ApplyPage.tsx` | `apply.ts` `candidateJob.ts` | `/api/apply` `/api/collect` `/api/candidate-jobs` | `services/apply/*` `services/sites/*` `services/browser/*` | `apply.py` `material.py`(CandidateJob) |
| 求职进度 | `pages/TrackerPage.tsx` | `tracker.ts` | `/api/tracker` | `tracker.py` `tracker_extract.py` | `tracker.py` |
| 求职统计 | `pages/AnalyticsPage.tsx` | `analytics.ts` | `/api/analytics` | `analytics.py` `ratios.py` `resume/resume_health.py` | 只读派生 |
| 模拟面试 | `pages/InterviewPage.tsx` | `interview.ts` `interviewExperiences.ts` | `/api/interview` `/api/interview-experiences` | `interview/interview.py` `interview/interview_questions.py` `interview/interview_experience_service.py` | `interview.py` `interview_experience.py` `question_bank_record.py` `interview_review_record.py` |
| 求职助手 | `pages/AssistantPage.tsx` + `features/assistant/*` | `assistant.ts` | `/api/assistant*` | `assistant/assistant_service.py` `assistant_tools/` `assistant/assistant_skills.py` `assistant/assistant_web_search.py` `feature_catalog.py` | `assistant.py`(ChatConversation/ChatMessage/AssistantSkill) |
| 我的资料 | `pages/ProfilePage.tsx` + `features/profile/*` | `profile.ts` `photo.ts` | `/api/profile` | `profile/profile_service.py` `profile_text_parser.py` `services/profile_parser/*` | `profile.py` |
| 资料箱 | `pages/MaterialsPage.tsx` | `material.ts` | `/api/materials` | `materials.py` `document_text.py` `text_extraction.py` | `material.py` |
| 知识库 | `pages/KnowledgePage.tsx` | `knowledge.ts` | `/api/knowledge` | `knowledge_service.py` | `knowledge_entry.py` |
| 工作台（技能） | `pages/SkillsPage.tsx` | `skill.ts` | `/api/assistant/skills` | `assistant/assistant_skills.py` `skill_archive.py` | `assistant.py`(AssistantSkill) |
| 事实台账 | `pages/ClaimsPage.tsx` | `claims.ts` | `/api/claims` | `claims.py` `claim_draft.py` | `claim.py` |
| 面试深挖 | `pages/DrillPage.tsx`（路由 `/claims/drill`） | `drill.ts` | `/api/drill` | `drill.py` | `drill.py` |
| 回收站 | `pages/TrashPage.tsx` | `trash.ts` | `/api/trash` | `trash.py`（`TRASH_SPECS` 注册表） | 多表软删 |
| 设置 | `pages/SettingsPage.tsx` | `settings.ts` `system.ts` `update.ts` | `/api/settings` `/api/system` `/api/update` | `settings_service.py` `datasets.py` `data_backup.py` `update_check.py` | `setting.py` |

页面内的功能组件（不占独立菜单，但常被问起）：

| 功能 | 前端组件 | 前端 API | 后端路由 | 核心逻辑 |
| ---- | ---- | ---- | ---- | ---- |
| 内推 | `components/ReferralPanel.tsx` | `referrals.ts` | `/api/referrals` | `referral_service.py` |
| 提醒 | `components/ReminderPanel.tsx` | `reminders.ts` | `/api/reminders` | `reminder_service.py` |
| 离线分享包 | `components/SharePackageModal.tsx` | `sharePackages.ts` | `/api/share-packages` | `share_package.py` |
| ATS 检测 | `components/AtsCheckPanel.tsx` | `ats.ts` | `/api/resumes/...` | `ats_check.py` |
| 匹配度分析 | `components/JobMatchModal.tsx` | `jobs.ts` | `/api/jobs/.../match` | `job/job_match.py` |

## 后端目录速览（backend/app/）

| 目录 | 职责 | 一句话 |
| ---- | ---- | ---- |
| `api/` | 路由层（35 个文件） | 只做参数校验与编排，不写业务 |
| `models/` | ORM 模型（20 个文件） | 一张表一个文件；**新增表必须注册进 `models/__init__.py`** |
| `schemas/` | Pydantic 契约 | 前后端共用的请求/响应结构 |
| `services/` | 业务层（最大） | 核心逻辑，与框架解耦、可离线测试 |
| `services/resume/` `services/profile/` | 简历域 / 资料域 | 生成落地、一致性、版式、模板；读写、相关性、上下文、照片 |
| `services/job/` `services/jd/` | 岗位域 / JD 规则 | 服务、匹配、需求解读；技能学历年限规则 |
| `services/assistant/` `services/interview/` | 助手域 / 面试域 | 服务、技能、来源、搜索；模拟面试、题库、面经 |
| `services/llm/` | 大模型抽象 | OpenAI 兼容 + Anthropic 原生，一个 Provider 接口 |
| `services/apply/` | 投递编排 | 任务运行器、采集、投递执行、表单引擎 |
| `services/browser/` | 浏览器桥接 | CDP 客户端、投递专用浏览器、页面就绪等待 |
| `services/sites/` | 站点适配器 | base 契约 + registry 分发 + 单站点实现 |
| `services/sites/official/` | 官网采集 | 读路径契约 + robots 闸门 + 阻断识别 + 完整性对账（与上面那条是**并列**关系，不是子集） |
| `services/assistant_tools/` | 助手工具 | 工具注册表与 handler，按域拆 `job_tools`/`data_tools` 等 |
| `services/job_parser/` `services/profile_parser/` | 文本规则解析 | 粘贴招聘信息/资料的本地规则 |
| `middleware/` | 请求中间件 | 请求 ID + 请求体大小限制 |
| `prompts/` | 提示词模板 | 与代码分离，调参改 `.md` 不动代码 |
| `templates/` | 简历 HTML 模板 | Jinja2 |

入口文件：`main.py`（兼容入口，重新导出）→ `application.py`（真正的装配：路由/中间件/生命周期）。`database_migrations.py` 编排 Alembic 升级。

## 前端目录速览（frontend/src/）

| 目录 | 职责 |
| ---- | ---- |
| `pages/` | 每个菜单项一个页面，`App.tsx` 里的 `MENU_ITEMS` 与 `Routes` 是唯一路由源 |
| `components/` | 页面内可复用组件；`components/common/` 是跨模块交互原语（行操作、右键菜单、详情抽屉） |
| `features/` | 重页面的专用 hooks 与子组件（目前只有 assistant、profile 两个） |
| `api/` | 所有 HTTP 请求的封装，前端唯一发起请求的地方 |
| `types/` | TypeScript 类型，枚举与后端常量逐字镜像 |
| `hooks/` | 通用 hooks（`useApi.ts` 等） |
| `utils/` | 纯工具函数 |
| `styles/` | 按视觉域拆分的样式 |

前端没有 Redux / Zustand / React Query，状态是页面级 `useState` + `hooks/useApi.ts`，路由用 `React.lazy` 懒加载。

## 我要改 X，该动哪

| 我要做 | 先看 | 然后 |
| ---- | ---- | ---- |
| 改一个页面的布局/样式 | `pages/XxxPage.tsx` + `styles/` | `components/` 里它引用的子组件 |
| 加一个新页面 | `App.tsx` 的 `MENU_ITEMS` + `Routes` | 新建 `pages/`，同步 `userGuideSteps.ts` |
| 改一个接口的返回字段 | `api/xxx.py` | `schemas/xxx.py` + 前端 `types/` + `api/xxx.ts` |
| 改一段业务规则/算法 | `services/` 里对应文件 | 对应 `tests/`，先加可复现测试 |
| 加一张表/一个字段 | 新建 Alembic 迁移 | 注册进 `models/__init__.py`，同步 `trash.TRASH_SPECS`（若软删） |
| 改简历生成效果 | `prompts/*.md` + `resume/resume_generator.py` | `resume/resume_content.py` / `resume/resume_grounding.py` |
| 加一个新 LLM 服务商 | `services/llm/` | `config.ts` 的 `LLM_PRESETS` |
| 加一个招聘站点适配器（投递） | `services/sites/` 实现 `base.py` 契约 + `registry.py` 注册 | 前端不用改 |
| 加一个招聘系统适配器（官网采集） | `services/sites/official/feeds/` 实现 `JobFeed` 契约 + `official/registry.py` 注册 | 前端不用改；命中判据必须是"端点存在**且**返回 ≥1 条岗位" |
| 改助手的"能力" | `services/feature_catalog.py` | 同步 `assistant_tools/_registry.py` 的 `_TOOLS` |
| 改应用内使用指南 | `components/userGuideSteps.ts` | `docs/user-guide.md` 一起改 |

> 注意：这个项目刻意保持**"一处逻辑只留一份实现"**（如投递准入 `models/apply.py::admission_of`、状态合并 `models/tracker.py::resolve_status`）。改这类逻辑前先 `grep` 确认只有一处，改完不要再另写一份。

## 测试在哪

- **后端**：`backend/tests/`，与被测模块同层拆分（`test_xxx.py` 管规则、`test_xxx_api.py` 管 HTTP 面、`test_migration_00NN.py` 管迁移）。命令见 [AGENTS.md](../AGENTS.md)。
- **前端**：Vitest，测试与被测文件同目录（`XxxPage.tsx` 旁就是 `XxxPage.test.tsx`）。

## 想了解得更深

- 每个功能的**数据流、设计决策、为什么这么设计**：见 [architecture.md](architecture.md)（含 mermaid 时序图与 17 条扩展点）。
- 每个版本**改了什么、为什么**：见 [CHANGELOG.md](../CHANGELOG.md)（记录了真实用户反馈驱动的修复）。

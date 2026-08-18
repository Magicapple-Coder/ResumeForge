# 架构设计

## 总体架构

前后端分离：React（Vite + TypeScript + Ant Design）+ FastAPI（Python），本地 SQLite 存储，单用户本地部署。除用户主动配置的大模型 API 外，不依赖额外的数据库或业务服务。

```mermaid
flowchart LR
    subgraph Frontend["前端 (React)"]
        UI[页面与组件]
        API[api/ 接口层]
    end
    subgraph Backend["后端 (FastAPI)"]
        ROUTES[api/ 路由层]
        SVC[services/ 业务层]
        LLM[services/llm/ 模型抽象]
        PARSER[岗位文本与 JD 规则解析]
        PROMPTS[prompts/ 提示词模板]
        DB[(SQLite)]
    end
    LLMAPI[大模型 API<br/>DeepSeek/豆包/OpenAI/...]

    UI --> API --> ROUTES --> SVC
    SVC --> LLM --> LLMAPI
    SVC --> PARSER
    SVC --> PROMPTS
    ROUTES --> DB
```

## 目录结构

```
backend/app/
├── main.py            # 应用入口：装配路由/中间件/建表与兼容升级
├── config.py          # 服务端配置（.env）
├── database.py        # 数据库连接、会话与 SQLite 缺列补齐
├── database_migrations.py # Alembic 编排与 SQLite 升级前备份
├── models/            # ORM 模型（profile/job/resume/setting）
├── schemas/           # Pydantic 数据结构（前后端契约）
├── api/               # 路由层：校验参数、编排服务、组装响应
├── middleware/        # 请求关联 ID 与请求体大小限制
├── services/          # 业务层：核心逻辑，与框架解耦
│   ├── llm/           # 大模型抽象（base + openai_compat）
│   ├── job_text_parser.py  # 粘贴招聘文本解析为可编辑岗位草稿
│   ├── jd_parser.py   # JD 规则解析（技能标签/学历/年限）
│   ├── resume_generator.py  # 简历生成流水线
│   ├── resume_suggestions.py # 按岗位生成简历修改建议
│   ├── exporter.py    # 导出 JSON/Markdown/HTML
│   ├── profile_service.py   # 个人资料读写
│   └── settings_service.py  # 运行时配置存取
├── prompts/           # 提示词模板（独立于代码，方便调参）
├── templates/         # 简历 HTML 模板（Jinja2）
└── data/              # 技能词典
```

## 岗位管理与个人资料

- 岗位备注随岗位保存，并纳入岗位列表的关键词搜索。批量状态更新使用 `POST /api/jobs/batch-status`，批量删除使用 `POST /api/jobs/batch-delete`。
- 两个批量接口都会先去重并校验全部岗位 ID；只要有 ID 不存在就不执行任何修改，全部有效时才在单一事务中提交，提交异常会回滚。
- 个人照片以通过格式、文件签名和体积校验的 data URL 保存在本地资料中。照片不会发送给大模型，而是在模型输出解析完成后注入结构化简历，供 HTML 预览、浏览器打印及导出使用。
- 每份 `ResumeRecord` 保存可空 `job_id`、岗位快照和来源 `source`。一个岗位可以关联多份 AI 生成或用户编写的简历；简历中心可按岗位筛选并展示来源，岗位详情和简历详情支持双向跳转。岗位删除后保留历史简历，但无法再生成新的岗位化建议。
- 教育、实习/工作、校园和项目条目各可保存一份 UTF-8 Markdown/TXT 参考文件。浏览器只保存文件名与正文，不保存本机路径；生成器只把与目标 JD 相关的正文片段放入候选上下文。

SQLite 启动升级以 Alembic 为唯一结构来源：空库执行完整 revision 链，已版本化数据库只执行待应用 revision。仅当检测到早期未版本化业务表时，才先执行 `create_all` 和 `ensure_sqlite_columns` 补齐历史兼容结构，再标记为基线并交给 `run_database_migrations`。有用户数据且存在待执行 revision 时，使用 SQLite backup API 在数据库同级 `backups/` 目录创建一致性备份，然后升级到 `head`。后续新增/删除列、改类型、约束变化和数据回填都必须新增 revision，不再扩大临时兼容层。

## 核心数据流：AI 生成简历

```mermaid
sequenceDiagram
    participant U as 用户
    participant F as 前端
    participant B as 后端 API
    participant G as ResumeGenerator
    participant L as 大模型

    U->>F: 选择岗位 + 是否美化拓展 + 拓展程度
    F->>B: POST /api/resumes/generate (SSE)
    B->>B: 校验资料与 LLM 配置
    B->>G: generate(profile, job, options)
    G->>G: 筛选岗位候选事实与相关参考片段
    G->>G: 按拓展等级渲染 Prompt（prompts/*.md + Jinja2）
    G->>L: 流式请求 chat/completions
    L-->>G: SSE 流式输出（JSON 文本）
    G-->>B: progress / delta 事件
    G->>G: 提取 JSON + 宽松校验
    G->>G: strong + 附件事实时执行内容质量检查
    opt 项目遗漏、内容过少或只是照抄附件
        G->>L: 非流式质量重试（最多一次）
        L-->>G: 完整 JSON
    end
    G->>G: 从本地资料注入照片（照片不发送给模型）
    G->>G: 一致性检查
    G-->>B: 生成完成（含防虚构 warnings）
    B->>B: 先落库 ResumeRecord
    B-->>F: saved 事件（record_id）
    B-->>F: done 事件（仅在持久化成功后发送）
    F->>B: POST /api/resumes/render 即时预览
    F->>U: 展示预览 + 导出按钮
    opt 用户主动请求岗位化建议
        F->>B: POST /api/resumes/{id}/suggestions
        B->>L: 非流式审核简历与 JD
        L-->>B: 结构化修改建议（仅基于已有事实）
        B-->>F: 建议列表
    end
```

## 核心数据流：用户编写简历

```mermaid
sequenceDiagram
    participant U as 用户
    participant F as 前端
    participant B as 后端 API
    participant DB as SQLite

    U->>F: 在岗位页选择“自行编写”
    F->>B: GET /api/profile
    B-->>F: 返回完整个人资料
    F->>F: 转换为统一 ResumeContent 并预填编辑器
    U->>F: 选择、调整或补充简历内容
    F->>B: POST /api/resumes/manual
    B->>B: 校验内容与可选 job_id
    B->>DB: 保存 source=manual 与岗位快照
    B-->>F: 返回简历记录
    F->>U: 在简历中心展示“用户编写”来源
```

AI 生成与用户编写最终使用相同的 `ResumeContent`、预览、编辑和导出链路，避免维护两套简历格式。用户编写路径不调用大模型；从资料预填后由用户决定保留哪些内容。

## 关键设计决策

| 决策                          | 理由                                                                                                |
| ----------------------------- | --------------------------------------------------------------------------------------------------- |
| SQLite 本地存储               | 单用户工具，零部署成本；切换多用户数据库时可复用 ORM，但仍需正式迁移、并发和数据库方言适配          |
| LLM 走 OpenAI 兼容协议        | DeepSeek/豆包/Kimi/智谱/Ollama 全部兼容，一套实现全覆盖                                             |
| 用户 API Key 存本地 DB        | 定位为个人本地工具，不对外暴露；README 有安全说明                                                   |
| Prompt 独立成文件             | 模板与代码分离，调参改 `prompts/*.md` 即可，无需动代码                                              |
| PDF 用浏览器打印实现          | 服务端 PDF 在中文环境依赖系统字体，跨平台极易踩坑；浏览器打印零依赖且排版稳定                       |
| A4 单页预览与打印             | HTML 模板固定 210×297mm；预览和导出在内容超长时整体缩放，保证投递打印尺寸一致                       |
| 岗位化建议按需生成            | 用户确认预览后再调用一次非流式模型，避免每次生成增加成本；建议不覆盖简历内容                        |
| 模型输出宽松解析 + 修复重试   | 大模型输出不稳定，先容错提取 JSON，失败后用修复 Prompt 重试一次，再失败友好降级                     |
| 深度美化质量门槛              | 在事实回填前识别合法但空洞的附件项目，最多非流式重试一次，避免前端拼接两份 JSON；失败时保留首轮结果 |
| 分级美化拓展                  | 关闭时严格回填资料原文；开启后允许基于资料与相关参考片段重组表达，但结构事实和数字仍受校验          |
| 一致性校验（防 AI 虚构）      | 固定名称、角色、时间、技能等结构事实，并拦截资料或参考文件未支持的量化结果                          |
| 岗位文本使用本地规则解析      | 粘贴内容不发送给大模型，先生成可编辑草稿，用户确认后才入库                                          |
| 照片在模型调用后注入          | 避免把无意义的 base64 内容发送给模型，同时保证预览与导出使用已校验的本地照片                        |
| 旧 SQLite 库补齐已知列        | 只对未版本化旧库运行兼容建表与幂等补列；空库和已版本化数据库由 Alembic 独立管理                     |
| Alembic revision + 升级前备份 | 早期数据库平滑进入正式迁移链；有用户数据时先备份，再执行可审查、可测试的版本化变更                  |
| AI 与手写共用内容结构         | 两种来源只在创建方式和元数据上不同，预览、编辑、导出与岗位关联行为保持一致                          |

## 部署与安全边界

- 前端只请求同源 `/api`。开发环境由 Vite 代理；生产环境必须由反向代理把 `/api` 转发到 FastAPI，并为 BrowserRouter 配置 `index.html` fallback。
- 默认定位是本机单用户应用，后端只应监听回环地址。CORS 只限制浏览器跨域读取，不提供身份认证；没有额外认证和 TLS 时不得直接暴露到公网。
- 请求上下文中间件同时校验声明长度和流式读取的实际长度，超限返回 413；每个响应携带 `X-Request-ID`，日志使用同一 ID 关联排查。
- API Key 以明文保存在本地 SQLite 中。照片不进入模型上下文，但岗位、资料以及被选中的总结片段会发送给用户选择的大模型服务商。
- 敏感数据处理和漏洞报告方式见 [SECURITY.md](../SECURITY.md)。

## 扩展点

1. **新增模型提供商**：非 OpenAI 兼容协议时，在 `services/llm/` 新增 Provider 类，并在 `create_provider` 中按 `provider` 字段分发。
2. **扩展岗位文本识别规则**：在 `services/job_text_parser.py` 增加字段标签或章节规则，并补充对应离线测试。
3. **新增导出格式**：在 `services/exporter.py` 加导出函数，`api/resumes.py` 的 `_EXPORT_FORMATS` 加一行。
4. **调整美化拓展策略**：后端 `resume_generator.py` 的分级指令与前端 `config.ts` 的 `RESUME_ENHANCEMENT_LEVELS` 保持一致，并补充生成器测试。

## 测试策略

- 后端核心业务（岗位文本/JD 解析、资料参考文件、岗位相关片段筛选、分级生成、照片校验与渲染、导出、防虚构校验）有单元测试，生成流水线用假 Provider，不依赖真实网络。
- API 层有冒烟测试（TestClient），覆盖岗位备注搜索、批量操作原子性、照片往返与其他核心链路。
- SQLite 升级测试使用临时旧库验证兼容补列、revision 标记、索引/外键迁移、幂等执行、备份和原数据保留，不接触真实用户数据库。
- 前端使用 Vitest 覆盖关键请求封装和核心交互，TypeScript strict、ESLint、Prettier 与生产构建提供静态门禁；复杂用户链路仍需按风险逐步补齐组件或端到端测试。
- GitHub Actions 在 Linux/Python 3.10、3.12 和 Windows/Python 3.12 上运行后端测试、覆盖率与 Ruff，并在 Node 20 上运行前端测试、格式检查、Lint 和构建。
- Python 与 npm 依赖审计在 CI 中作为提示项运行，避免外部公告服务短暂不可用阻断功能检查；Dependabot 持续提交可审查的依赖更新。

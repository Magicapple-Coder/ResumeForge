# 简历通 ResumeForge

[![CI](https://github.com/Magicapple-Coder/ResumeForge/actions/workflows/ci.yml/badge.svg)](https://github.com/Magicapple-Coder/ResumeForge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> 面向求职场景的个性化简历工具：录入岗位 → 维护个人资料 → AI 生成或自行编写 → 导出多格式文件。
> 单用户本地运行，业务数据默认保存在本机；AI 功能只把生成所需内容发送给你主动配置的模型服务商。LLM API Key 由你自己配置，代码中不内置任何密钥。

一个岗位可以关联多份简历。你只需要维护一份完整的个人资料库，既可以针对岗位 JD 多次生成不同版本，也可以从资料快速预填后自行编写；ResumeForge 会保留全部历史记录并标明简历来源。

## ✨ 功能特性

| 模块               | 说明                                                                                                             |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- |
| 📋 岗位管理        | 手动填写或粘贴跨行业招聘信息生成草稿；职责、要求之外的有用内容进入“其他信息”，保存时提取技能标签                 |
| 👤 个人资料库      | 基本信息、简历照片、教育/工作/校园/项目经历、技能、获奖；每条经历可附加 Markdown/TXT 总结文件                    |
| 🤖 AI 定制简历     | 按 JD 筛选事实并流式生成，可选择是否进行岗位导向美化拓展及轻度、适中、深度三级强度；预览可按需生成岗位化修改建议 |
| ✍️ 自行编写简历    | 从个人资料预填后自由修改；编辑时在旁边保留目标岗位职责、要求、技能与其他信息供对照                               |
| 📚 简历历史        | AI 生成和用户编写的简历均自动留存，可收藏、按来源区分、随时查看和重新导出                                        |
| 🔗 岗位关联        | 一个岗位可关联多份简历；岗位可查看全部对应简历，简历可返回目标岗位                                               |
| ⭐ 收藏夹          | 分页集中查看收藏的岗位与简历，并可跳转详情或取消收藏                                                             |
| 💡 岗位需求解读    | 按需依据招聘原文生成结构化需求总结、原文证据和通用求职准备建议                                                   |
| 💬 AI 求职助手     | 使用设置中的模型进行流式问答，保存会话历史；可显式关联岗位、简历、资料，上传文本或图片并按需联网搜索             |
| 📄 多格式导出      | 固定 A4 单页 HTML 预览（含简历照片）→ 浏览器打印为 PDF；JSON、Markdown 直接下载                                  |
| 🔍 全局搜索        | 岗位与简历历史一键检索，快速定位需要的信息                                                                       |
| 🛡 防虚构校验       | 生成结果中的学校/公司/项目名自动与资料库比对，不一致时给出警告                                                   |
| 🔑 你的 Key 你做主 | 兼容任意 OpenAI 协议接口：DeepSeek、豆包、Kimi、OpenAI、Ollama 内置预设，也支持自定义                            |

## 🧰 技术栈

| 层         | 技术                                                                              |
| ---------- | --------------------------------------------------------------------------------- |
| 前端       | React 18 + TypeScript（strict）+ Ant Design 5 + Vite 6 + React Router             |
| 后端       | Python 3 + FastAPI + SQLAlchemy 2.0 + Pydantic v2 + httpx + Jinja2                |
| 存储       | SQLite（本地单文件，零部署成本）                                                  |
| 测试与质量 | pytest + coverage + Ruff（后端）、Vitest + TypeScript + ESLint + Prettier（前端） |

## 🏗 架构

前后端分离：前端统一通过同源 `/api` 访问后端。开发环境由 Vite 自动代理；生产环境需要由 Web 服务器托管 `frontend/dist`，将 `/api` 反向代理到 FastAPI，并把非静态文件的前端路由回退到 `index.html`。

```
┌──────────────┐   /api (REST + SSE)   ┌───────────────────────────────┐
│  React 前端   │ ───────────────────▶ │        FastAPI 后端            │
│  岗位/资料/   │                      │  API 路由 → 服务层 → 数据层     │
│  简历/助手    │ ◀─────────────────── │  ├─ AI 生成 / 手写简历保存       │
└──────────────┘                       │  ├─ 岗位文本解析（规则，无 LLM）  │
                                       │  ├─ JD 标签解析（规则，无 LLM）   │
                                       │  ├─ 岗位解读 / 求职助手           │
                                       │  ├─ 导出（HTML/JSON/Markdown）  │
                                       │  └─ SQLite（单文件数据库）       │
                                       └───────────────────────────────┘
```

详细设计（含决策记录与扩展点）见 [docs/architecture.md](docs/architecture.md)。

## 🚀 快速开始

```powershell
git clone https://github.com/Magicapple-Coder/ResumeForge.git
cd ResumeForge
```

### 环境要求

- Python ≥ 3.10
- Node.js ≥ 20.19.0（含 npm）

### 1. Windows 一键启动（推荐）

在项目根目录双击 [start.cmd](start.cmd)。首次运行会自动创建后端虚拟环境、安装缺失的前后端依赖、启动两个服务，并打开浏览器：

```text
http://127.0.0.1:5173
```

之后再次双击 `start.cmd` 即可打开项目，无需分别启动前端和后端。需要完全关闭服务时，双击 [stop.cmd](stop.cmd)；它只会结束由启动器记录并验证过的 ResumeForge 进程，不会结束其他项目。

启动器会固定前端代理到本次启动的本地后端。若提示端口被其他程序占用，请先关闭旧的 ResumeForge 服务或冲突程序，不要在两个相同端口上重复启动。启动日志和临时进程记录位于 `runtime/`，不会提交到 Git。

### 2. 手动启动（开发、排错或 macOS/Linux）

```powershell
cd backend

# 创建虚拟环境并安装运行依赖
python -m venv .venv
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动服务（默认 http://127.0.0.1:8000，接口文档见 /docs）
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

macOS/Linux 使用 `.venv/bin/python -m pip ...` 和 `.venv/bin/python -m uvicorn ...` 替换上面的 Windows 路径。Git Bash 可使用 `export PYTHONUTF8=1`。

数据库文件首次启动时自动创建于 `backend/data/resume_forge.db`。空库和已版本化数据库直接由 Alembic revision 管理；只有检测到早期未版本化业务表时，才先用幂等兼容层补齐已知列并接入迁移基线。如果已有用户数据且存在待执行迁移，会先在数据库同级的 `backups/` 目录创建一致性备份。升级前仍建议自行备份。可选环境变量见 [backend/.env.example](backend/.env.example)（全部有默认值，不配置也能运行）。

然后在另一个终端启动前端：

```powershell
cd frontend
npm ci
npm run dev        # http://localhost:5173，已配置 /api 代理到 8000 端口
```

生产部署不能只复制 `dist` 后直接打开：静态服务器需要支持 SPA history fallback，并把同源 `/api` 请求转发到后端。后端默认只应监听回环地址；若要供其他设备访问，需要先增加身份认证、TLS 和更严格的网络边界。

### 3. 配置大模型

打开页面左侧 **设置**，选择内置预设（自动填充接口地址与模型名），填入你的 API Key 后点击「测试连接」。内置预设：

| 预设             | 说明                                  |
| ---------------- | ------------------------------------- |
| DeepSeek         | 便宜好用的国产模型，`deepseek-chat`   |
| 豆包（火山方舟） | `doubao-seed-1-6-250615` 等           |
| Kimi（月之暗面） | `kimi-k2-0711-preview` 等             |
| OpenAI           | 官方接口，`gpt-4o-mini` 等            |
| Ollama           | 本地模型，`http://localhost:11434/v1` |

也支持任意 OpenAI 兼容接口：填 `Base URL` + `API Key` + `模型名` 即可。配置保存在本地数据库中，浏览器只会收到脱敏占位符；测试连接和生成简历时，后端才会把密钥作为鉴权信息发送到你主动配置的服务商。修改已保存配置的 `Base URL` 时，需要重新填写 API Key。

设置页中 `temperature`、超时时间和最大输出 Token 的标签均提供悬停提示。图片附件使用 OpenAI Chat Completions 的 `image_url` 消息格式；是否真正支持图片取决于所选模型及服务商，纯文本模型可能拒绝请求或无法理解图片。请先用服务商文档确认模型的多模态能力。

### 4. 使用流程

首次打开网站会自动显示四步使用引导；关闭后不会再次自动弹出，随时可以点击左侧导航底部的 **使用指南** 重新查看。引导完成状态仅保存在当前浏览器的本地存储中，不进入简历数据库。

1. **岗位** 页 → 点「手动添加」，直接填写岗位，或粘贴官网招聘信息后点「识别并填充」，核对草稿并保存；本地规则覆盖互联网、医疗、教育、制造、零售、物流等常见招聘表达，无法归入职责或任职要求但仍有用的福利、团队介绍、职位 ID、部门、工作安排及申请流程会进入“其他信息”；可记录招聘发布时间、备注和收藏状态，并批量调整状态或删除岗位；
2. **个人资料** 页 → 可直接粘贴整段个人简历信息并点「识别并填充」，也可以手动核对教育、工作、校园、项目和技能等信息；支持中英文/编号分区、字段同义词、连续多段经历、无标题的“组织/公司 + 角色 + 日期”结构和常见日期格式；可上传简历照片，并为每条经历附加 UTF-8 编码的 Markdown/TXT 总结文件（不超过 200 KB）；
3. **岗位** 页 → 可先查看“岗位需求解读”，再选择「生成简历」或「自行编写」；自行编写会从个人资料预填并在编辑器旁展示岗位参考，AI 生成可选择是否启用岗位导向美化拓展及拓展程度；
4. 预览时切换到“编辑”模式，点击纸面内容即可定位到对应结构化字段；保存后可在简历中心收藏、查看来源、关联岗位并导出 A4 PDF / JSON / Markdown；
5. **收藏夹** 集中展示收藏的招聘信息和简历；**求职助手** 支持多轮会话，可按需选择岗位、简历或个人资料作为上下文，也可上传附件或开启联网搜索。

### 运行测试

```powershell
cd backend
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest --cov=app --cov-config=../pyproject.toml
```

```bash
cd frontend
npm test         # Vitest 单元测试
npm run format:check
npm run lint
npm run build    # tsc 类型检查 + 生产构建
```

GitHub Actions 会在 Linux 与 Windows 上重复执行关键检查；依赖审计作为提示项运行，避免公告服务或网络短暂不可用误阻断其他质量门禁。

## 🔄 更新而不丢失数据

用户数据默认保存在 `backend/data/resume_forge.db`，配置保存在 `backend/.env`；二者都被 Git 忽略，正常 `git pull --ff-only` 不会覆盖。每次更新前请先关闭服务并运行数据库备份脚本，再拉取代码、重新安装依赖并重启：

```powershell
cd backend
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe scripts\backup_database.py
cd ..
git pull --ff-only
.\backend\.venv\Scripts\python.exe -m pip install -r .\backend\requirements.txt
cd frontend
npm ci
```

后端启动时会自动运行 Alembic 数据库迁移，并在有待迁移数据时创建 `backend/data/backups/` 备份。不要使用 `git clean -fdx`，也不要删除整个项目目录后直接覆盖；完整的升级、压缩包更新和回滚步骤见 [docs/upgrading.md](docs/upgrading.md)。

## ❓ FAQ

**API Key 存在哪里？安全吗？**
保存在本地 SQLite 数据库的 `app_setting` 表中，不会通过读取接口返回真实值；设置页看到的是脱敏占位符。测试连接或生成简历时，后端才会把密钥作为鉴权信息发送到你配置的模型服务商。若修改 `Base URL`，必须重新填写密钥，避免脱敏占位符被转发到另一台主机。这是单用户本地工具的取舍：换取零配置体验。仓库代码与 `.env.example` 中不含任何真实密钥（`gitignore` 已忽略 `.env`）。若对明文存储不放心，可自行改造 `backend/app/services/settings_service.py` 增加加密（如系统钥匙串）。

**PDF 如何导出？**
预览页右上角「打印 / 保存 PDF」调用浏览器打印（210×297mm A4 单页版式已内置在模板中，内容过长会整体缩放）。相比服务端 PDF 库，浏览器打印免去中文字体跨平台兼容问题，且所见即所得。

**粘贴招聘信息后会自动创建岗位吗？**
不会直接入库。「识别并填充」使用本地规则拆分职位名称、公司、地点、职责、要求、其他信息和招聘发布时间，不访问网络，也不会把招聘文本发送给大模型。规则覆盖多种行业的常见中英文标题、章节、字段同义词、全角文本、无空行或同一行多字段格式；岗位技能标签会归一化高置信度技术、办公软件、生产、物流、医疗、教育及职业资质词。福利、团队/公司介绍、职位 ID、部门、工作安排和申请流程等会尽量进入“其他信息”。“更新于”不会被当作招聘发布时间。规则解析无法保证所有网站和行业模板都无误，请核对草稿和提示后再保存。

**岗位需求解读会读取我的资料吗？**
不会。岗位需求解读只把当前岗位招聘信息发送给设置中的模型，生成需求总结、带原文证据的要求和通用准备建议；它不会读取个人资料，也不会修改或保存岗位、资料和简历。关闭弹窗后解读结果不会作为新的数据库记录保留，需要时可重新生成。

**AI 求职助手会读取或修改哪些内容？**
助手默认只收到当前问题和最近的已完成对话文本。只有你明确选择关联岗位、关联简历或“使用我的资料”时，对应内容才加入本次模型上下文；资料上下文会移除姓名、电话、邮箱和照片等身份字段。关联简历只移除照片，简历正文中的姓名和联系方式仍会随正文发送，因此选择前请确认内容和服务商。助手没有写入岗位、资料或简历的工具权限，只能返回建议或草稿，实际修改仍需你在对应页面确认保存。会话、消息和附件会保存在本地 SQLite，删除会话会同时删除其消息历史。

每条消息最多上传 4 个附件，支持 UTF-8 的 TXT/Markdown/JSON/CSV 以及 PNG/JPEG/WebP/GIF；单个附件不超过 2 MB、合计不超过 5 MB。当前消息中的文本附件和图片会发送给所选模型，后续历史只复用受限的文本内容，不重复发送历史图片。请勿上传无关敏感文件，并确认所选模型支持图片输入。

**联网搜索会自动抓取招聘网站吗？**
不会。开启联网搜索后，查询会发送给固定的 Bing RSS 搜索接口，最多读取少量公开结果的标题、URL 和摘要，不跟随结果链接，也不抓取网页正文。对于可识别的求职问题，系统会去除“如果”等口语填充词并筛掉没有招聘语义的词典、百科、诗歌等结果；没有直接相关的公开来源时不会展示凑数链接，而会提示调整关键词。助手被要求在寻找招聘信息时优先采用公司、学校、医院、政府或其他用人单位的官方页面，并把第三方页面仅作为线索；但搜索摘要可能不完整、过期或仍包含第三方结果，投递前必须打开来源并自行核验是否为官方页面。

**个人资料可以整段粘贴吗？**
可以。个人资料页的「粘贴识别」会在本地按教育、工作/实习、校园、项目、技能、奖项和总结等分区拆分，并识别常见中文/英文字段、连续无空行的多段经历、全角复制文本、技能缩写和日期写法；没有标题时，也会识别“公司/学生组织 + 角色 + 日期”的连续结构。结果只回填可编辑草稿，不会直接覆盖已保存资料。规则无法确定的内容会保留在相应描述或提示中，保存前请快速核对。

**个人照片会发送给大模型吗？**
不会。照片经格式、文件签名和 2 MB 大小校验后保存在本地 SQLite 中；生成简历时不进入模型上下文，而是在模型内容解析完成后注入简历，并用于 HTML 预览、打印和导出。

**经历总结文件保存在哪里，会发送给大模型吗？**
浏览器会读取 Markdown/TXT 正文并保存到本地 SQLite，不保存或依赖原始文件路径。启用美化拓展时，系统会从正文中选取与当前 JD 相关的片段，连同候选资料发送给你配置的模型服务商；照片仍不会发送。总结文件可能包含个人或项目敏感信息，使用第三方模型前请确认其数据政策。

**升级后旧数据库需要手动迁移吗？**
通常不需要。启动时会先兼容早期未记录 revision 的数据库，再自动执行 `backend/migrations/` 中尚未应用的 Alembic revision；当前 `0003` 增加岗位“其他信息”，`0004` 增加简历收藏状态，`0005` 增加助手会话与消息表。迁移会为旧记录使用兼容默认值，检测到已有用户数据时先创建 SQLite 备份。迁移和自动备份都不能替代用户自己的备份策略，升级前仍建议复制 `backend/data/resume_forge.db` 到安全位置。

需要随时手动创建一致性备份时，可在 `backend` 目录运行 `.venv\Scripts\python.exe scripts\backup_database.py`；macOS/Linux 将 Python 路径替换为 `.venv/bin/python`。

**AI 会不会编造经历？**
美化拓展不等于虚构。生成链路会固定姓名、公司/组织/项目、角色、时间和技能等结构事实；模型只能使用资料字段与参考文件中的事实重组表达，未被资料支持的量化结果会被拦截并提示。深度美化且存在附件事实时，系统还会识别项目遗漏、要点过少或照抄附件的结果，并自动重试一次。关闭美化拓展后，经历要点会严格回填为资料原文。见 [docs/prompt-tuning.md](docs/prompt-tuning.md)。

## 📖 文档

| 文档                                           | 内容                             |
| ---------------------------------------------- | -------------------------------- |
| [docs/architecture.md](docs/architecture.md)   | 系统架构、关键设计决策、扩展点   |
| [docs/prompt-tuning.md](docs/prompt-tuning.md) | 提示词调优指南与防虚构校验说明   |
| [docs/upgrading.md](docs/upgrading.md)         | 安全升级、备份、迁移与回滚       |
| [CONTRIBUTING.md](CONTRIBUTING.md)             | 开发环境、代码约定与提交检查     |
| [AGENTS.md](AGENTS.md)                         | 项目长期维护、测试与安全规则     |
| [SECURITY.md](SECURITY.md)                     | 安全边界、敏感数据与漏洞报告方式 |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)       | 社区协作与行为准则               |
| [CHANGELOG.md](CHANGELOG.md)                   | 版本变化与兼容性说明             |

## 🤝 参与贡献

欢迎提 Issue 与 PR。开发环境、代码约定、测试命令和数据库兼容要求见 [CONTRIBUTING.md](CONTRIBUTING.md)；安全问题请按 [SECURITY.md](SECURITY.md) 私密报告，不要在公开 Issue 中粘贴 API Key 或真实简历。

## 📁 目录结构

```
ResumeForge/
├── backend/
│   ├── app/
│   │   ├── api/            # FastAPI 路由层（薄，只做参数校验与调用服务）
│   │   ├── middleware/     # 请求 ID、请求体大小等通用 HTTP 边界
│   │   ├── services/       # 业务逻辑：简历生成、岗位文本/JD 解析、导出
│   │   ├── models/         # SQLAlchemy ORM 模型
│   │   ├── schemas/        # Pydantic 请求/响应模型
│   │   ├── prompts/        # 提示词模板（与代码分离，改 prompt 不动代码）
│   │   ├── templates/      # 简历 HTML 导出模板
│   │   └── data/           # 技能词典
│   ├── migrations/         # Alembic 数据库迁移 revision
│   ├── scripts/            # 数据库备份等维护脚本
│   ├── tests/              # pytest 单元测试
│   ├── requirements.txt     # 直接运行依赖
│   ├── requirements-dev.txt # CI、覆盖率、Ruff 与依赖审计工具
│   └── .env.example        # 环境变量示例
├── frontend/
│   └── src/
│       ├── api/            # 请求封装与 SSE 流解析
│       ├── components/     # 业务组件（生成弹窗、预览、表单等）
│       ├── pages/          # 首页、岗位、资料、简历、收藏夹、求职助手与设置页面
│       ├── hooks/          # useApi 等通用 Hook
│       └── types/          # 与后端 schema 镜像的 TS 类型
├── docs/                   # 架构 / Prompt 调参文档
└── .github/                # CI、依赖更新、Issue 与 PR 模板
```

## 📄 许可证

[MIT](LICENSE) © ResumeForge 贡献者

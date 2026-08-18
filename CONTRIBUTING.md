# 参与贡献

感谢你帮助改进 ResumeForge。项目采用渐进式维护方式：优先保留现有行为，用小而可验证的改动解决一个明确问题。

提交修改前请先阅读项目根目录的 [AGENTS.md](AGENTS.md)，其中包含长期维护原则、Windows 环境约定、验证命令和安全边界。

## 开始之前

- Python 3.10 或更高版本。
- Node.js 20.19.0 或更高版本，并使用随 Node 提供的 npm。
- Windows 中文环境运行 Python 命令前建议设置 `PYTHONUTF8=1`。
- 不要提交 `.env`、数据库、真实简历、API Key、构建产物、虚拟环境或其他个人数据。

## 本地开发

后端（PowerShell）：

```powershell
cd backend
$env:PYTHONUTF8 = "1"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

前端：

```powershell
cd frontend
npm ci
npm run dev
```

开发环境由 Vite 将 `/api` 转发到 `http://127.0.0.1:8000`。

## 修改原则

- API 路由负责参数校验和业务编排，核心逻辑优先放在 `backend/app/services/`。
- Pydantic Schema 与前端 TypeScript 类型需要同步维护。
- 新增配置必须提供安全默认值，并同步更新 `.env.example` 和相关文档。
- SQLite 表结构变更必须新增 `backend/migrations/versions/` 下的 Alembic revision，并有旧数据保留、重复启动和备份测试；不要修改已经发布的 revision。
- 不要在日志、异常消息、测试夹具或截图中泄露 API Key 和个人资料。
- 不做与当前问题无关的全量重构或格式化，避免掩盖行为变化。

## 提交前检查

后端：

```powershell
cd backend
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest --cov=app --cov-config=../pyproject.toml
```

前端：

```powershell
cd frontend
npm test
npm run format:check
npm run lint
npm run build
```

涉及界面交互时，还应手动验证对应流程及常见空状态、错误状态和窄屏布局。涉及用户可见行为、依赖、配置或数据库兼容性的改动，请同步更新 `README.md`、相关 `docs/` 文档及 `CHANGELOG.md`。

## Pull Request

- 一个 PR 聚焦一个主题，并说明原因、影响范围和验证结果。
- 对破坏性变更、数据迁移、安全边界变化或新的外部网络请求作醒目标注。
- 界面变化提供修改前后截图。
- 新功能和缺陷修复应提供与风险相称的自动化测试。
- 保持 lockfile 与依赖清单一致，但不要提交本地虚拟环境或 `node_modules`。

安全问题请不要提交公开 Issue，按 [SECURITY.md](SECURITY.md) 的方式报告。

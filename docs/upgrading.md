# 升级与数据安全

ResumeForge 是本地单用户应用。代码、Python/Node 依赖和本地业务数据分开管理：Git 只跟踪代码和配置示例，用户数据库位于 `backend/data/`，不会被正常的 `git pull` 覆盖。

## 推荐升级流程（Git 安装）

升级前先关闭正在运行的后端和前端进程，在项目目录执行：

### Windows PowerShell

```powershell
Set-Location "C:\path\to\ResumeForge"
cd backend
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe scripts\backup_database.py
cd ..
git status
git pull --ff-only

cd backend
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm ci
```

### macOS / Linux

```bash
cd ~/ResumeForge/backend
export PYTHONUTF8=1
.venv/bin/python scripts/backup_database.py
cd ..
git status
git pull --ff-only

cd backend
.venv/bin/python -m pip install -r requirements.txt
cd ../frontend
npm ci
```

依赖安装完成后，Windows 用户可在项目根目录双击 `start.cmd`，它会启动前后端并自动打开页面。需要关闭服务时双击 `stop.cmd`。启动器只会终止自己记录且校验通过的 ResumeForge 进程。

一键启动器默认使用后端端口 8005、前端端口 5173；若端口冲突，可通过 `-BackendPort` 或 `-FrontendPort` 参数指定其他端口（`start.cmd -BackendPort 8010`，参数用空格分隔）。手动启动示例中的后端端口 8000 是开发默认值，与一键启动器互不冲突。

启动器会在 `frontend/` 目录执行 npm 安装，因此从资源管理器双击启动时不会因为当前工作目录不同而误报缺少 `package-lock.json`。仓库包含锁文件时使用 `npm ci`；旧压缩包缺少锁文件时会回退到一次 `npm install`。

首次创建环境时，启动器会探测现有 **Python 3.10 – 3.13** 和 Node.js 20.19.0+/npm，满足要求时直接复用（装了好几个受支持版本时优先用 3.12）。缺少 Python 时优先通过 Windows `winget` 进行用户级静默安装，再回退到固定版本且校验 SHA-256 的 Python 官方 x64 安装器；缺少 Node.js/npm 时同样先使用 `winget`，再回退到校验过的 Node.js 官方 x64/ARM64 便携 ZIP（先试国内镜像，再回官方源，**两者都做 SHA-256 校验**），并解压到 `runtime/tools/`。自动准备需要网络，不会触碰数据库或 `.env`；如果 winget、网络、系统架构或权限不满足条件，启动器会停止并给出手动安装指引。升级代码时 `runtime/` 不受正常 `git pull` 影响；即使便携 Node 目录被手动删除，下次启动也只会重新准备运行时，不影响业务数据。

**只装了 Python 3.14 的电脑会被当成"没有可用 Python"**：锁定的后端依赖（尤其是 `pydantic-core==2.33.1`）还没有 cp314 轮子，装的时候会退化成源码编译并失败。启动器会明确提示版本窗口，然后走自动准备装一个 3.12；已有的 3.14 不受影响。若 `.venv` 是早前用超出窗口的解释器建的，启动时会把它移到 `runtime/venv-unsupported-<时间戳>/` 后重建，而不是反复用同一个坏环境失败。

开发、排错或 macOS/Linux 环境仍可分别启动后端与前端，并确认健康检查正常：

```powershell
# 终端 1（Windows）
cd backend
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 终端 2
cd frontend
npm run dev
```

macOS/Linux 将后端 Python 路径替换为 `.venv/bin/python`；前端命令不变。

`git pull --ff-only` 如果发现你改过本地代码会停止，而不会自动覆盖修改；先保存或处理本地改动，再重新执行。不要使用 `git clean -fdx` 清理项目，否则会删除被忽略的数据库和 `.env`。

## 数据迁移与回滚

- 后端启动时会自动执行 `backend/migrations/` 中尚未应用的 Alembic migration。
- 检测到已有数据且存在待迁移版本时，程序会先在 `backend/data/backups/` 创建一致性 SQLite 备份。
- 当前迁移链中的 `0003_job_additional_info` 会为旧岗位补充空的“其他信息”，`0004_resume_favorite` 会把旧简历收藏状态初始化为未收藏，`0005_chat_assistant` 新增助手会话和消息表，`0006_chat_conversation_flags` 新增置顶/收藏字段且不会重建会话父表；这些升级不会改写原有岗位、资料、简历正文或助手消息。
- 自动备份不是替代品；升级前仍应把 `backend/data/resume_forge.db` 和 `.env` 复制到项目目录之外，并对备份设置访问权限。
- `backend/data/backups/` **不会自动清理**：迁移前的自动备份和「数据备份与恢复」里恢复前的自动备份都写在这个目录，每个文件都是一份完整的数据库副本。长期使用会持续累积，确认不再需要回滚后建议手动删除较早的文件。
- 升级启动失败时，先停止服务，保留错误日志；不要删除原数据库。可从升级前备份恢复数据库，再检出上一个稳定版本启动。

不要为了切回旧代码直接运行上述 revision 的 `downgrade`：降级 `0005` 会删除助手会话历史，降级 `0004` 会删除简历收藏状态，降级 `0003` 会删除岗位“其他信息”。需要保留这些数据时，应停止服务并恢复升级前备份，再检出匹配的旧版本代码。

示例回滚步骤（请把路径换成自己的备份文件）：

```powershell
$backup = "backend\data\backups\resume_forge-YYYYMMDD-HHMMSS-ffffff.db"
Copy-Item $backup backend\data\resume_forge.db -Force
git checkout <previous-stable-tag-or-commit>  # 例如已发布的 v0.1.0 标签或对应提交
```

将占位符替换为你要回滚到的实际稳定标签或提交；发布新版本时应为稳定版本创建 Git 标签（形如 `v0.3.0`）。版本号与 CHANGELOG 可以交给 `scripts/bump_version.py` 处理：它按自上一个 `v*` 标签以来的提交类型判定幅度，同步更新后端配置、前端 `package.json` 与 lockfile、README 与 CHANGELOG，但**不会替你提交或打标签**，改完会打印需要手动执行的命令。如果数据库已经执行了不可逆的迁移，必须先阅读对应 revision 的降级说明；不要把新版本数据库直接交给旧版本使用。

改用回滚也可以走应用内：在 **设置 → 数据集** 里把之前导出的备份包导入为一份新数据集（只新增、
不覆盖当前数据），确认内容无误后再切换过去。切换时会对该数据集补跑建表/补列/Alembic 迁移，
所以导入一份来自旧版本的数据集也能正常使用。注意备份包记录着导出时的 Alembic revision，
**旧版本无法导入新版本导出的备份**，会明确拒绝并提示先升级应用。

设置页的「最大输出 Token」在新版本中可以用 `0` 表示“不限制”，但旧版本会把 `0` 判定为非法值并把整份模型配置（含 Base URL、模型名称和 API Key）重置为默认值。回退到旧版本之前，请先在设置页把该字段改回 256 以上的具体数值。这一项不涉及数据库结构变更。

## 使用压缩包更新

如果不使用 Git，请先退出程序并备份 `backend/data/` 和 `backend/.env`，再把新版本解压到新的目录。安装新版本依赖后，将旧目录的 `backend/data/` 和 `backend/.env` 复制到新目录；不要覆盖新版本的代码文件，也不要把数据库提交到公开仓库。

解压后如果启动失败，控制台会打印 `runtime/backend.stderr.log` 的最后几行。**「安装包不完整，后端无法启动：缺少 backend/...」表示这份压缩包少了文件**（手工打包时漏掉目录是最常见的原因），重新下载完整压缩包即可，不必在本机排查代码或环境。务必重新下载，不要从旧目录复制缺失文件凑齐：内容可能属于另一个版本，对照不上。

## 打包发行包（维护者）

`scripts/Build-Release.ps1` 是唯一推荐的出包方式：

```powershell
# 打包某个标签（发布用）
.\scripts\Build-Release.ps1 -Ref v0.6.0
# 打包当前提交（本地试验）；输出目录默认是 <项目>\dist
.\scripts\Build-Release.ps1 -OutputDirectory D:\tmp
```

它用 `git archive` 从指定的 ref 生成 `ResumeForge-<版本>.zip`（顶层是一个同名文件夹），所以：

- **不会漏文件**：压缩包内容就是该 ref 跟踪的文件全集，`git ls-files` 里有什么就有什么。手工压缩最容易漏掉 `backend/app/data/`（内置技能词典），那种包在别的电脑上必然起不来。
- **不会夹带私人数据**：`backend/data/`（数据库与迁移前备份）、`backend/.env`、`runtime/`、`node_modules/`、各种缓存都被 `.gitignore` 排除，因此不进包。`.env.example` 是例外，它本就要随包发送。
- **写完后自检**：脚本会重新打开压缩包，逐个确认必需文件在、必需目录非空、禁止路径不在，并检查 `start.cmd` 保持 CRLF 行尾。任何一项不过就**删除该压缩包并报错**，不会留下一个半成品。
- 工作区有未提交改动时会给出警告：压缩包内容是该 ref 的提交状态，不包含未提交的改动。

出包后请把 zip 挂到 GitHub Releases（仓库目前只有 tag，没有 Release 附件），而不要用聊天工具零散发文件，否则用户拿到的版本无从核对。CI 在 Windows 上运行 `scripts/tests/Test-Build-Release.ps1`：它会真的打一次包，并断言压缩包包含的文件与 `git ls-tree -r HEAD` 完全一致、必需文件齐备、禁止路径没有泄漏、`.cmd` 保持 CRLF、以及出包清单与后端 `app/preflight.py` 的运行时清单一致。

## 保留哪些文件

升级时需要保留：

- `backend/data/resume_forge.db` 及 `backend/data/backups/`；
- `backend/.env`（如果修改过服务端配置）；
- 个人导出的简历和外部备份文件。

不需要也不应复制：

- `backend/.venv/`、`frontend/node_modules/` 和 `frontend/dist/`；
- 测试缓存、日志和临时文件。

依赖版本变化后重新执行安装命令，比复制旧虚拟环境更可靠。

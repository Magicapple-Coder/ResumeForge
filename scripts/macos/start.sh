#!/bin/bash
# ResumeForge 启动器（macOS）。
#
# 与 Windows 侧 scripts/Start-ResumeForge.ps1 一一对应，功能相同：
#   1. 检查/自举 Python 与 Node（不要求用户预先装任何东西）
#   2. 首次运行创建 backend/.venv 并安装后端依赖、安装前端依赖
#   3. 启动后端（uvicorn）与前端（vite），等两边都健康
#   4. 打开浏览器，并把 PID 记录写进 runtime/，供 stop.command 使用
#
# 直接双击项目根目录的 start.command 即可；也可以在终端里执行：
#   bash scripts/macos/start.sh --backend-port 8010 --frontend-port 5180 --no-browser
#
# 这个脚本**不修改项目之外的任何东西**：Python 与 Node 的便携版都放在
# runtime/tools/ 里，不写 /usr/local，不弹管理员授权，也不需要 Homebrew。

set -euo pipefail

RF_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RF_PROJECT_ROOT=$(cd "$RF_SCRIPT_DIR/../.." && pwd)

RF_BACKEND_DIR="$RF_PROJECT_ROOT/backend"
RF_FRONTEND_DIR="$RF_PROJECT_ROOT/frontend"
RF_RUNTIME_DIR="$RF_PROJECT_ROOT/runtime"

# 端口与 Windows 侧保持一致，文档里的示例才能通用。
RF_BACKEND_PORT=8005
RF_FRONTEND_PORT=5173
RF_OPEN_BROWSER=1

# 首次运行要跑数据库迁移，而且冷机器上杀毒软件扫描全新的 .venv / node_modules
# 会明显拖慢启动，所以超时给得比较宽。
RF_BACKEND_START_TIMEOUT_SECONDS=90
RF_FRONTEND_START_TIMEOUT_SECONDS=120

# 参数错误时打印用法并以 2 退出。用 2 这个专属状态码，是为了让收尾钩子知道
# "这次根本没走到启动阶段"，不要打出"已停止，没有启动任何服务"那套话。
rf_argument_error() {
    printf '\n%s\n' "$1" >&2
    shift
    for line in "$@"; do
        printf '%s\n' "$line" >&2
    done
    printf '\n' >&2
    rf_usage >&2
    exit 2
}

rf_usage() {
    cat <<'USAGE'
用法：start.command [选项]

选项：
  --backend-port PORT    后端端口（默认 8005）
  --frontend-port PORT   前端端口（默认 5173）
  --no-browser           启动后不自动打开浏览器
  -h, --help             显示这段说明
USAGE
}

rf_parse_arguments() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --backend-port)
                [ "$#" -ge 2 ] || rf_argument_error "--backend-port 后面缺少端口号。"
                RF_BACKEND_PORT=$2
                shift 2
                ;;
            --frontend-port)
                [ "$#" -ge 2 ] || rf_argument_error "--frontend-port 后面缺少端口号。"
                RF_FRONTEND_PORT=$2
                shift 2
                ;;
            --no-browser)
                RF_OPEN_BROWSER=0
                shift
                ;;
            -h | --help)
                rf_usage
                exit 0
                ;;
            *)
                rf_argument_error "无法识别的参数：$1"
                ;;
        esac
    done

    for port in "$RF_BACKEND_PORT" "$RF_FRONTEND_PORT"; do
        case "$port" in
            '' | *[!0-9]*) rf_argument_error "端口必须是数字：$port" ;;
        esac
        if [ "$port" -lt 1024 ] || [ "$port" -gt 65535 ]; then
            rf_argument_error "端口必须在 1024 到 65535 之间：$port" \
                "小于 1024 的端口在 macOS 上需要 root 权限，本启动器不会提权。"
        fi
    done
    if [ "$RF_BACKEND_PORT" -eq "$RF_FRONTEND_PORT" ]; then
        rf_argument_error "后端端口与前端端口不能相同：两者都是 ${RF_BACKEND_PORT}。" \
            "用 --backend-port / --frontend-port 指定不同的端口。"
    fi
}

# shellcheck source=lib/common.sh
. "$RF_SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/python.sh
. "$RF_SCRIPT_DIR/lib/python.sh"
# shellcheck source=lib/node.sh
. "$RF_SCRIPT_DIR/lib/node.sh"

RF_BACKEND_URL="http://127.0.0.1:$RF_BACKEND_PORT"
RF_FRONTEND_URL="http://127.0.0.1:$RF_FRONTEND_PORT"
# 记录文件名刻意与 Windows 的 runtime/*.json 区分：同名不同格式只会互相干扰。
RF_BACKEND_RECORD="$RF_RUNTIME_DIR/backend.macos.pid"
RF_FRONTEND_RECORD="$RF_RUNTIME_DIR/frontend.macos.pid"
RF_BACKEND_STDOUT="$RF_RUNTIME_DIR/backend.stdout.log"
RF_BACKEND_STDERR="$RF_RUNTIME_DIR/backend.stderr.log"
RF_FRONTEND_STDOUT="$RF_RUNTIME_DIR/frontend.stdout.log"
RF_FRONTEND_STDERR="$RF_RUNTIME_DIR/frontend.stderr.log"

# 后端进程命令行里必须出现的片段。stop 之前要拿它复核，避免误停。
RF_BACKEND_COMMAND_PATTERN='uvicorn app.main:app'
# 前端同理。--strictPort 是我们自己传的、vite 默认没有的参数，用它做特征最稳：
# macOS 上 npm 会被 exec 成 `node .../npm-cli.js run dev -- --host ... --strictPort`，
# 只看 "npm" 或 "run dev" 都不够独特。
RF_FRONTEND_COMMAND_PATTERN='run dev.*--strictPort'
# 后端依赖探针：直接让解释器去 import，而不是检查目录名。
# 一个丢了 pydantic、或轮子和解释器不匹配的 venv 能通过"目录存在"检查，
# 然后在 import 时才死，报错只剩一句"启动没成功"。
RF_BACKEND_DEPENDENCY_PROBE='import fastapi, uvicorn, sqlalchemy, alembic, pydantic, pydantic_settings, PIL, pypdf, fpdf, websocket, docx, multipart'

rf_started_backend_pid=""
rf_started_frontend_pid=""

# 失败时收尾：只停"这一次启动起来的"进程，绝不去动用户既有的服务。
rf_cleanup_on_failure() {
    status=$?
    # 2 是参数错误（rf_argument_error），那时连启动阶段都没进，
    # 再打一段"已停止，没有启动任何服务"只会淹没真正的用法说明。
    if [ "$status" -ne 0 ] && [ "$status" -ne 2 ]; then
        if [ -n "$rf_started_frontend_pid" ]; then
            stop_process_tree "$rf_started_frontend_pid" TERM
            rm -f "$RF_FRONTEND_RECORD"
        fi
        if [ -n "$rf_started_backend_pid" ]; then
            stop_process_tree "$rf_started_backend_pid" TERM
            rm -f "$RF_BACKEND_RECORD"
        fi
        printf '\n%s启动失败。%s\n\n' "$RF_COLOR_RED" "$RF_COLOR_RESET"
        printf '已停止，没有启动任何服务。\n'
        printf '按上面的步骤处理后，关掉这个窗口重新双击 start.command 即可。\n'
        printf '如果上面的办法都不行，请把这段内容截图发到项目的 GitHub Issues。\n'
    fi
    return 0
}
trap rf_cleanup_on_failure EXIT

# ---------------------------------------------------------------------------
# 后端
# ---------------------------------------------------------------------------

# 准备 backend/.venv。返回时 RF_VENV_PYTHON 指向可用的解释器。
rf_prepare_backend_venv() {
    RF_VENV_PYTHON="$RF_BACKEND_DIR/.venv/bin/python3"
    venv_config="$RF_BACKEND_DIR/.venv/pyvenv.cfg"

    if [ -x "$RF_VENV_PYTHON" ] && ! rf_venv_version_supported "$venv_config"; then
        # 用窗口外的版本建的 venv 永远装不上钉死的轮子，复用它等于每次都以同一种
        # 方式失败。挪开而不是删除：项目保留可恢复的派生产物，同卷改名是零成本。
        stale_dir="$RF_RUNTIME_DIR/venv-unsupported-$(date '+%Y%m%d-%H%M%S')"
        log_warn "backend/.venv 是用不受支持的 Python 版本建的，已移到 $stale_dir 并重建（原目录没有被删除，需要时可手动找回）。"
        mv "$RF_BACKEND_DIR/.venv" "$stale_dir"
    fi

    if [ ! -x "$RF_VENV_PYTHON" ]; then
        rf_ensure_system_python
        log_info "首次运行：正在创建 Python 虚拟环境（这一步只做一次）..."
        if ! "$RF_PYTHON" -m venv "$RF_BACKEND_DIR/.venv"; then
            die "创建 Python 虚拟环境失败。" \
                "怎么办：" \
                "  1) 确认 backend 目录可写（没有被设为只读、也没有被安全软件锁定）；" \
                "  2) 删掉 backend/.venv 后重新双击 start.command；" \
                "  3) 仍失败：把上面的报错原文发到项目的 GitHub Issues。"
        fi
    fi

    if [ ! -x "$RF_VENV_PYTHON" ]; then
        die "没有找到后端的 Python 环境：$RF_VENV_PYTHON" \
            "怎么办：删掉 backend/.venv 目录后重新双击 start.command，让它重建一次。"
    fi
}

rf_ensure_backend_dependencies() {
    if "$RF_VENV_PYTHON" -c "$RF_BACKEND_DEPENDENCY_PROBE" >/dev/null 2>&1; then
        return 0
    fi

    # 极少数便携版解释器不带 pip（system-site-packages 被裁掉、或 venv 用了
    # --without-pip 建的）。先补上，再往下走，否则用户的报错会是
    # "No module named pip"，看不出该怎么办。
    if ! "$RF_VENV_PYTHON" -m pip --version >/dev/null 2>&1; then
        log_info "后端环境里没有 pip，正在补装..."
        "$RF_VENV_PYTHON" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi

    log_info "首次运行：正在安装后端依赖（约 40 个包，第一次要几分钟）..."
    if ! "$RF_VENV_PYTHON" -m pip install --timeout 300 --retries 10 \
        -r "$RF_BACKEND_DIR/requirements.txt"; then
        die "后端依赖安装失败。" \
            "最常见的原因是网络：默认走官方 PyPI，国内经常很慢或直接超时。" \
            "怎么办（按顺序试）：" \
            "  1) 换国内镜像重装（最有效）：" \
            "     backend/.venv/bin/python3 -m pip install -i https://mirrors.aliyun.com/pypi/simple -r backend/requirements.txt" \
            "  2) 需要代理时，先在终端里 export HTTPS_PROXY=http://127.0.0.1:端口 再重试；" \
            "  3) 确认能打开 https://mirrors.aliyun.com/pypi/simple/（打不开就是网络被拦了）；" \
            "  4) 仍失败：把上面 pip 的报错原文发到 GitHub Issues。"
    fi
}

rf_start_backend() {
    if is_resumeforge_backend_healthy "$RF_BACKEND_URL"; then
        log_info "后端已经在运行：$RF_BACKEND_URL"
        return 0
    fi

    if tcp_port_in_use "$RF_BACKEND_PORT"; then
        # 端口被占但健康检查不过：可能是我们自己上一次运行留下的、已经崩掉的后端
        # （进程还在，服务不响应）。记录能对上就自己收拾，否则明确说"这不是我的"。
        if process_record_match "$RF_BACKEND_RECORD" "$RF_BACKEND_COMMAND_PATTERN"; then
            log_warn "上一次运行留下的简历通后端正占着端口 ${RF_BACKEND_PORT}，先停掉它再启动一个新的。"
            stop_recorded_process "backend" "$RF_BACKEND_RECORD" "$RF_BACKEND_COMMAND_PATTERN"
            sleep 1
        else
            die "端口 $RF_BACKEND_PORT 已被别的程序占用（不是简历通自己的后端，所以不会去动它）。" \
                "怎么办（二选一）：" \
                "  1) 关掉占用该端口的程序（想知道是谁：lsof -nP -iTCP:$RF_BACKEND_PORT -sTCP:LISTEN）；" \
                "  2) 换一个端口启动：start.command --backend-port 8010"
        fi
    fi

    rf_prepare_backend_venv
    rf_ensure_backend_dependencies

    # 子 shell 里 exec，让记录下来的 PID 就是 uvicorn 本身，
    # 而不是一层随时会消失的 shell 包装。
    (
        cd "$RF_BACKEND_DIR"
        exec "$RF_VENV_PYTHON" -m uvicorn app.main:app \
            --host 127.0.0.1 --port "$RF_BACKEND_PORT" --log-level warning
    ) >>"$RF_BACKEND_STDOUT" 2>>"$RF_BACKEND_STDERR" &
    rf_started_backend_pid=$!
    save_process_record "$rf_started_backend_pid" "$RF_BACKEND_RECORD"

    if wait_until_healthy "$RF_BACKEND_URL" "$RF_BACKEND_START_TIMEOUT_SECONDS" "$rf_started_backend_pid"; then
        log_info "后端已启动：$RF_BACKEND_URL"
        return 0
    fi

    if ! kill -0 "$rf_started_backend_pid" 2>/dev/null; then
        die "$(format_service_start_failure "后端" "在变得健康之前就退出了" "$RF_BACKEND_STDERR")" \
            "上面是后端的真实报错，通常能直接看出原因（缺依赖、端口被拦、数据库文件损坏等）。"
    fi
    die "$(format_service_start_failure "后端" "在 ${RF_BACKEND_START_TIMEOUT_SECONDS} 秒内没有启动成功" "$RF_BACKEND_STDERR")" \
        "怎么办：先看上面的日志；如果日志是空的，可能是端口被防火墙拦了，换一个端口试试：" \
        "  start.command --backend-port 8010"
}

# ---------------------------------------------------------------------------
# 前端
# ---------------------------------------------------------------------------

rf_ensure_frontend_dependencies() {
    vite_command="$RF_FRONTEND_DIR/node_modules/.bin/vite"
    if [ -x "$vite_command" ]; then
        return 0
    fi

    log_info "首次运行：正在安装前端依赖（几百个包，第一次要几分钟）..."
    # npm ci 按当前目录解析 package-lock.json，所以必须先进到 frontend/。
    # 没有 lockfile 的旧源码包用 npm install 现场生成一份，而不是直接报 EUSAGE。
    if [ -f "$RF_FRONTEND_DIR/package-lock.json" ]; then
        install_command=ci
    else
        log_warn "没有找到 frontend/package-lock.json，改用 npm install 现场生成一份（这样装出来的版本可能与发布时不同）。"
        install_command=install
    fi

    if ! (
        cd "$RF_FRONTEND_DIR"
        "$RF_NPM_PATH" "$install_command" \
            --no-audit --no-fund \
            --fetch-timeout=1800000 --fetch-retries=5 \
            --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=120000
    ); then
        die "前端依赖安装失败。" \
            "可能原因：网络不通、npm 镜像不可达、或磁盘空间不足。" \
            "怎么办：" \
            "  1) 手动重试看完整报错：在 frontend 目录执行" \
            "     $RF_NPM_PATH install --registry=https://registry.npmmirror.com" \
            "  2) 空间不足时先清理磁盘（node_modules 需要约 400 MB）；" \
            "  3) 需要代理时先在终端里 export HTTPS_PROXY=http://127.0.0.1:端口；" \
            "  4) 仍失败：把上面 npm 的报错原文发到 GitHub Issues。"
    fi
}

rf_start_frontend() {
    if is_resumeforge_backend_healthy "$RF_FRONTEND_URL"; then
        log_info "前端已经在运行：$RF_FRONTEND_URL"
        return 0
    fi

    if tcp_port_in_use "$RF_FRONTEND_PORT"; then
        if process_record_match "$RF_FRONTEND_RECORD" "$RF_FRONTEND_COMMAND_PATTERN"; then
            log_warn "上一次运行留下的简历通前端正占着端口 ${RF_FRONTEND_PORT}，先停掉它再启动一个新的。"
            stop_recorded_process "frontend" "$RF_FRONTEND_RECORD" "$RF_FRONTEND_COMMAND_PATTERN"
            sleep 1
        else
            die "端口 $RF_FRONTEND_PORT 被另一个前端占用，而且它连的不是本次的后端（所以不会去动它）。" \
                "怎么办（二选一）：" \
                "  1) 关掉占用该端口的程序（想知道是谁：lsof -nP -iTCP:$RF_FRONTEND_PORT -sTCP:LISTEN）；" \
                "  2) 换一个端口启动：start.command --frontend-port 5180"
        fi
    fi

    rf_ensure_node_runtime
    rf_ensure_frontend_dependencies

    # 这个环境变量只作用于本次进程，让 Vite 代理指向上面启动的后端，
    # 不去改用户仓库里受跟踪的或本地的 .env。
    (
        cd "$RF_FRONTEND_DIR"
        export VITE_BACKEND_URL="$RF_BACKEND_URL"
        exec "$RF_NPM_PATH" run dev -- \
            --host 127.0.0.1 --port "$RF_FRONTEND_PORT" --strictPort
    ) >>"$RF_FRONTEND_STDOUT" 2>>"$RF_FRONTEND_STDERR" &
    rf_started_frontend_pid=$!
    save_process_record "$rf_started_frontend_pid" "$RF_FRONTEND_RECORD"

    if wait_until_healthy "$RF_FRONTEND_URL" "$RF_FRONTEND_START_TIMEOUT_SECONDS" "$rf_started_frontend_pid"; then
        log_info "前端已启动：$RF_FRONTEND_URL"
        return 0
    fi

    if ! kill -0 "$rf_started_frontend_pid" 2>/dev/null; then
        die "$(format_service_start_failure "前端" "在变得健康之前就退出了" "$RF_FRONTEND_STDERR")" \
            "上面是前端的真实报错，通常能直接看出原因（依赖装坏了、端口被拦等）。"
    fi
    die "$(format_service_start_failure "前端" "在 ${RF_FRONTEND_START_TIMEOUT_SECONDS} 秒内没有启动成功" "$RF_FRONTEND_STDERR")" \
        "怎么办：先看上面的日志；如果日志是空的，可能是端口被防火墙拦了，换一个端口试试：" \
        "  start.command --frontend-port 5180"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

rf_main() {
    rf_parse_arguments "$@"

    for directory in "$RF_BACKEND_DIR" "$RF_FRONTEND_DIR"; do
        if [ ! -d "$directory" ]; then
            die "找不到项目目录：$directory" \
                "请确认解压出来的文件夹没有被移动或删除。"
        fi
    done

    mkdir -p "$RF_RUNTIME_DIR"

    log_step "启动后端"
    rf_start_backend

    log_step "启动前端"
    rf_start_frontend

    if [ "$RF_OPEN_BROWSER" -eq 1 ]; then
        # 打不开浏览器不该让刚启动好的服务被收掉，所以失败只提示。
        if ! open "$RF_FRONTEND_URL" >/dev/null 2>&1; then
            log_warn "没能自动打开浏览器，请手动访问 $RF_FRONTEND_URL"
        fi
    fi

    printf '\n'
    log_ok "简历通已就绪。要关闭服务，双击 stop.command（或在终端里执行 bash scripts/macos/stop.sh）。"
    printf '打开地址：%s\n' "$RF_FRONTEND_URL"
}

# 只有直接执行时才跑主流程。这样 start.sh 也能被 source 进测试脚本
# （scripts/tests/test-macos-launcher.sh 就靠这个特性逐个验证纯函数），
# 而不会在 source 的瞬间就去启动服务。
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    rf_main "$@"
fi

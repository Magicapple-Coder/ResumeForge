# ResumeForge macOS 启动链：日志、下载校验、端口探测、进程记录与停止。
#
# 由 scripts/macos/start.sh、stop.sh、update.sh 共同 source。
# 与 Windows 侧对应关系：
#   ResumeForge.Common.ps1  → 本文件（健康探测 / 端口占用 / 进程记录 / 停止）
#   ResumeForge.Python.ps1  → lib/python.sh
#   ResumeForge.Node.ps1    → lib/node.sh
#   ResumeForge.Process.ps1 → start.sh（编排）
#
# 兼容性约束：macOS 自带的 /bin/bash 是 **3.2**。不要用关联数组（declare -A）、
# ${var,,}、mapfile/readarray、[[ =~ ]] 捕获组等 4.x 起的特性。
# 也不要依赖 jq / GNU coreutils：只用 macOS 自带工具（curl、tar、shasum、lsof、ps、pgrep）。
#
# 显示约定：所有面向用户的输出都走 log_* 函数，颜色只在终端里启用（重定向到文件时
# 会退化成纯文本，日志文件因此仍然可读）。

: "${RF_DOWNLOAD_TIMEOUT_SECONDS:=600}"

if [ -t 1 ]; then
    RF_COLOR_RESET=$'\033[0m'
    RF_COLOR_RED=$'\033[31m'
    RF_COLOR_GREEN=$'\033[32m'
    RF_COLOR_YELLOW=$'\033[33m'
    RF_COLOR_CYAN=$'\033[36m'
    RF_COLOR_DIM=$'\033[2m'
else
    RF_COLOR_RESET=""
    RF_COLOR_RED=""
    RF_COLOR_GREEN=""
    RF_COLOR_YELLOW=""
    RF_COLOR_CYAN=""
    RF_COLOR_DIM=""
fi

log_info() { printf '%s\n' "$*"; }
log_dim() { printf '%s%s%s\n' "$RF_COLOR_DIM" "$*" "$RF_COLOR_RESET"; }
log_step() { printf '\n%s==> %s%s\n' "$RF_COLOR_CYAN" "$*" "$RF_COLOR_RESET"; }
log_ok() { printf '%s%s%s\n' "$RF_COLOR_GREEN" "$*" "$RF_COLOR_RESET"; }
log_warn() { printf '%s%s%s\n' "$RF_COLOR_YELLOW" "$*" "$RF_COLOR_RESET" >&2; }

# die 打印可执行的处置建议后以非零码退出。
# 用法：die "第一行原因" "第二行怎么办" ...
die() {
    printf '\n%s%s%s\n' "$RF_COLOR_RED" "$1" "$RF_COLOR_RESET" >&2
    shift
    for line in "$@"; do
        printf '%s\n' "$line" >&2
    done
    exit 1
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# rf_version_ge A B → A >= B（点分数字，比较前三位）
# 不用 sort -V：BSD sort 直到较新版本才支持 -V，启动器要能在任何 macOS 上跑。
rf_version_ge() {
    a=$1
    b=$2
    index=1
    while [ "$index" -le 3 ]; do
        part_a=$(printf '%s' "$a" | cut -d. -f"$index")
        part_b=$(printf '%s' "$b" | cut -d. -f"$index")
        part_a=${part_a:-0}
        part_b=${part_b:-0}
        case "$part_a$part_b" in
            *[!0-9]*) return 1 ;;
        esac
        if [ "$part_a" -gt "$part_b" ]; then
            return 0
        fi
        if [ "$part_a" -lt "$part_b" ]; then
            return 1
        fi
        index=$((index + 1))
    done
    return 0
}

# ---------------------------------------------------------------------------
# 架构与平台
# ---------------------------------------------------------------------------

# 输出 arm64 或 x64，与 Node.js 发行包的命名一致（uname -m 给的是 arm64 / x86_64）。
detect_macos_arch() {
    machine=$(uname -m)
    case "$machine" in
        arm64 | aarch64) printf 'arm64\n' ;;
        x86_64 | amd64) printf 'x64\n' ;;
        *)
            die "无法识别的 Mac 处理器架构：$machine" \
                "本项目只提供 Apple 芯片（arm64）与 Intel（x64）两种运行时。"
            ;;
    esac
}

# ---------------------------------------------------------------------------
# 下载与校验
# ---------------------------------------------------------------------------

# sha256_of FILE → 十六进制摘要（小写）
sha256_of() {
    if command_exists shasum; then
        shasum -a 256 "$1" | awk '{print $1}'
    elif command_exists openssl; then
        openssl dgst -sha256 "$1" | awk '{print $NF}'
    else
        die "系统里既没有 shasum 也没有 openssl，无法校验下载内容。" \
            "这两个工具都是 macOS 自带的，出现这种情况通常说明系统被裁剪过。"
    fi
}

# download_file URL TARGET
# 返回 0 表示成功。刻意不在这里做校验：调用方要能一口气试多个镜像，
# 并逐个说明"这个源为什么不行"。
download_file() {
    curl -fL --connect-timeout 20 --max-time "$RF_DOWNLOAD_TIMEOUT_SECONDS" \
        --retry 2 --retry-delay 3 -o "$2" "$1"
}

# download_verified TARGET EXPECTED_SHA256 LABEL APPROX_MB URL [URL...]
#
# 按顺序尝试每个候选 URL，第一个摘要匹配的才被接受。
# 期望摘要写死在仓库里、不来自镜像，所以镜像只能"慢或旧"，不能替换内容。
# 每个候选失败都单独说一声：只说"下载失败"会让用户以为是自己网络全断了，
# 而实际情况常常是某一个加速站挂了、下一个源本来是好的。
download_verified() {
    target=$1
    expected=$2
    label=$3
    approx_size=$4
    shift 4

    if [ "$#" -eq 0 ]; then
        log_warn "没有可用的下载源，跳过 ${label} 的下载。"
        return 1
    fi

    log_info "正在下载经过校验的${label}（约 ${approx_size} MB）..."
    for url in "$@"; do
        if download_file "$url" "$target"; then
            actual=$(sha256_of "$target")
            if [ "$actual" = "$expected" ]; then
                return 0
            fi
            log_warn "$url 返回的文件摘要不匹配（期望 ${expected}，实际 ${actual}）。换下一个源..."
        else
            log_warn "$url 下载失败。换下一个源..."
        fi
        rm -f "$target"
    done

    return 1
}

# ---------------------------------------------------------------------------
# 端口与健康检查
# ---------------------------------------------------------------------------

# 端口是否已被监听。lsof 是 macOS 自带的；没有它时按"没有占用"处理——
# 后续启动会自己失败并给出真实报错，比这里猜错更安全。
tcp_port_in_use() {
    port=$1
    command_exists lsof || return 1
    [ -n "$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)" ]
}

# 服务地址一律**现用现派生**。
#
# 不要提前算好存进变量：端口可以被命令行覆盖（--backend-port 8123），而任何在赋值
# 时刻算好的 URL 都会停在默认端口上。CI 上就是这么栽的——服务好好地监听在 8123，
# 探针却一直敲 8005，于是"90 秒内没有启动成功"。这类错位在只有默认端口的环境里
# 永远看不出来，所以这里用函数从结构上杜绝。
rf_backend_url() {
    printf 'http://127.0.0.1:%s\n' "$RF_BACKEND_PORT"
}

rf_frontend_url() {
    printf 'http://127.0.0.1:%s\n' "$RF_FRONTEND_PORT"
}

# 只做健康探针，不做重定向判断：两个服务都从同一个 /api/health 取答案
# （前端经由 Vite 代理转发，代理不通时这个探针同样会失败）。
is_resumeforge_backend_healthy() {
    url=$1
    body=$(curl -fsS --max-time 2 "$url/api/health" 2>/dev/null) || return 1
    case "$body" in
        *'"status"'*'"ok"'*) return 0 ;;
        *) return 1 ;;
    esac
}

# 启动失败时打印"同刻"的服务状态。
#
# 为什么必须在这一刻打：脚本失败后会把自己起的进程停掉，事后（比如 CI 的收尾步骤）
# 再去看端口，只能看到"确实没有监听者"——那既可能是"从没起来"，也可能是"被停掉了"，
# 两种情况分不开。这里趁进程还在，把端口监听者、PID 存活与探针详情一并留下。
rf_dump_service_state() {
    local service_label=$1
    local port=$2
    local pid=$3
    local url=$4
    local listeners

    printf '%s\n' "---- ${service_label}启动失败现场 ----" >&2
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        printf '%s\n' "进程仍然存活（PID ${pid}）：不是「启动即退出」，而是没能进入可服务状态。" >&2
    else
        printf '%s\n' "进程已经退出（PID ${pid:-未知}）。" >&2
    fi
    if command_exists lsof; then
        listeners=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null)
        if [ -n "$listeners" ]; then
            printf '%s\n' "端口 ${port} 的监听者：" "$listeners" >&2
        else
            printf '%s\n' "端口 ${port} 没有任何监听者。" >&2
        fi
    fi
    printf '%s\n' "探针 ${url}/api/health ：" >&2
    curl -v --max-time 3 "$url/api/health" >&2 2>&1 || printf '%s\n' "（探针失败）" >&2
    printf '%s\n' "---- 现场结束 ----" >&2
}

# wait_until_healthy URL TIMEOUT_SECONDS [PID]
# PID 存在时，进程已死就立即返回失败——一个已经退出的子进程永远不会变健康。
# 报错应该指向真实原因（脚本写错、依赖缺失），而不是被拖到超时之后。
wait_until_healthy() {
    url=$1
    timeout=$2
    watched_pid=${3:-}

    elapsed=0
    while [ "$elapsed" -lt "$timeout" ]; do
        if is_resumeforge_backend_healthy "$url"; then
            return 0
        fi
        if [ -n "$watched_pid" ] && ! kill -0 "$watched_pid" 2>/dev/null; then
            return 1
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ---------------------------------------------------------------------------
# 进程记录：只停"确实是自己启动的那个进程"
#
# 记录格式是**扁平的 key=value**，不是 Windows 那边的 JSON。
# 理由：macOS 不预装 jq，而自己解析自己写的 JSON 只能靠 sed 硬凑正则——出错的
# 时候正好是最需要它可靠的时候（要停进程了）。key=value 读回来是一行 sed。
# 文件名也刻意与 Windows 的 runtime/*.json 区分：同名不同格式，被另一平台读到
# 只会互相干扰。runtime/ 是 gitignore 的，不入库。
# ---------------------------------------------------------------------------

# 进程启动时刻的签名。用 lstart 的原始字符串而不是自己算 Unix 时间：
# 它不需要解析、不受时区影响，同一个进程每次读出来都是同一串。
process_start_signature() {
    ps -p "$1" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

process_command_line() {
    # 用 args 而不是 command：两者在 macOS 上等价，但 args 在 Linux 与 BSD 上
    # 都是同一个字段名，测试脚本因此也能在别的平台上跑。
    ps -p "$1" -o args= 2>/dev/null
}

# save_process_record PID RECORD_PATH
save_process_record() {
    pid=$1
    record=$2
    {
        printf 'process_id=%s\n' "$pid"
        printf 'started_at=%s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        printf 'start_signature=%s\n' "$(process_start_signature "$pid")"
    } >"$record"
}

# process_record_field RECORD_PATH FIELD
process_record_field() {
    [ -f "$1" ] || return 1
    sed -n "s/^$2=//p" "$1" | head -n 1
    return 0
}

# process_record_match RECORD_PATH COMMAND_PATTERN
# 三项全部对得上才认：PID 存在、命令行匹配、启动时刻签名一致。
# PID 复用与残留记录都会在这里被挡掉，因此绝不会误停无关进程。
process_record_match() {
    record=$1
    pattern=$2

    [ -f "$record" ] || return 1
    pid=$(process_record_field "$record" "process_id")
    case "$pid" in
        '' | *[!0-9]*) return 1 ;;
    esac
    kill -0 "$pid" 2>/dev/null || return 1

    command_line=$(process_command_line "$pid")
    [ -n "$command_line" ] || return 1
    printf '%s\n' "$command_line" | grep -Eq "$pattern" || return 1

    recorded_signature=$(process_record_field "$record" "start_signature")
    if [ -n "$recorded_signature" ]; then
        current_signature=$(process_start_signature "$pid")
        [ "$recorded_signature" = "$current_signature" ] || return 1
    fi
    return 0
}

# 按 PID 递归停止整棵子进程树。Vite 的 esbuild 子进程、npm 的 sh 包装层都要一起走，
# 否则端口会一直被占住，下一次启动就会撞上"端口被占用"。
stop_process_tree() {
    pid=$1
    signal=${2:-TERM}
    [ -n "$pid" ] || return 0
    kill -0 "$pid" 2>/dev/null || return 0

    children=$(pgrep -P "$pid" 2>/dev/null || true)
    for child in $children; do
        stop_process_tree "$child" "$signal"
    done
    kill -"$signal" "$pid" 2>/dev/null || true
}

# stop_recorded_process DISPLAY_NAME RECORD_PATH COMMAND_PATTERN
stop_recorded_process() {
    display_name=$1
    record=$2
    pattern=$3

    [ -f "$record" ] || return 0

    if ! process_record_match "$record" "$pattern"; then
        log_warn "没有停止 ${display_name}：记录与当前进程对不上（可能是上一次运行留下的残留）。"
        return 0
    fi

    pid=$(process_record_field "$record" "process_id")
    stop_process_tree "$pid" TERM
    waited=0
    while [ "$waited" -lt 10 ] && kill -0 "$pid" 2>/dev/null; do
        sleep 1
        waited=$((waited + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
        stop_process_tree "$pid" KILL
    fi
    rm -f "$record"
    log_info "已停止 ${display_name}。"
}

# ---------------------------------------------------------------------------
# 启动失败时的报错：把日志尾巴直接打出来
# ---------------------------------------------------------------------------

# 打印日志最后 N 行（丢掉空行）。日志是 UTF-8，macOS 默认就是 UTF-8，无需转码。
# 显式 return 0：调用方在 set -e + pipefail 下用命令替换取结果，
# "整个文件都是空行"必须算读取成功、而不是失败。
log_tail() {
    path=$1
    count=${2:-12}
    if [ -f "$path" ]; then
        grep -v '^[[:space:]]*$' "$path" 2>/dev/null | tail -n "$count" || true
    fi
    return 0
}

# format_service_start_failure DISPLAY_NAME REASON LOG_PATH
# 把日志尾巴打在报错里：双击 start.command 的用户通常不会去看
# runtime/backend.stderr.log，只说"看日志"等于什么都没说。
format_service_start_failure() {
    display_name=$1
    reason=$2
    log_path=$3

    message="${display_name} ${reason}。日志：${log_path}"
    tail_output=$(log_tail "$log_path" 12)
    if [ -z "$tail_output" ]; then
        printf '%s（日志是空的）。\n' "$message"
    else
        printf '%s\n最后几行：\n%s\n' "$message" "$tail_output"
    fi
}

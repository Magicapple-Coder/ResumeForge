#!/bin/bash
# macOS 启动链的守卫测试。
#
# 为什么需要它：项目的维护者手上没有 Mac，macOS 分支的脚本**没法靠人工跑一遍来验证**。
# 这份测试就是那台缺席的 Mac —— 它在 CI 的 macOS runner 上跑，对同一批纯函数做断言，
# 把"只能靠人肉发现"的问题变成红灯：
#
#   * 换行/编码：.sh 与 .command 出现 CRLF，macOS 上会以
#     "bad interpreter: /bin/bash^M" 失败，而任何在 Windows 上的编辑都可能带进来；
#   * 可执行位：.command 双击要靠它；
#   * 自举常量（版本号、SHA-256、下载源）：钉死在这里，改一处必须同步改另一处；
#   * 版本窗口判断、进程记录匹配、进程树停止这些纯逻辑。
#
# 刻意不依赖任何测试框架：macOS 自带 bash 3.2，装了 pytest/vitest 也没用。
# 用法：bash scripts/tests/test-macos-launcher.sh

set -uo pipefail

RF_TEST_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
RF_START_SCRIPT="$RF_TEST_ROOT/scripts/macos/start.sh"

RF_SHELL_SOURCES="start.command stop.command update.command
scripts/macos/start.sh scripts/macos/stop.sh scripts/macos/update.sh
scripts/macos/lib/common.sh scripts/macos/lib/python.sh scripts/macos/lib/node.sh"

# 会被**直接执行**的脚本（.command 双击、或 bash scripts/macos/*.sh），必须有 shebang；
# lib/*.sh 是被 source 进来的，不带 shebang 是惯例，也不该被要求。
RF_EXECUTABLE_SOURCES="start.command stop.command update.command
scripts/macos/start.sh scripts/macos/stop.sh scripts/macos/update.sh"

# 变量定界检查要多扫一份：守卫脚本**自己**也曾踩过同一个坑（它的失败信息里就有）。
RF_QUOTING_SOURCES="$RF_SHELL_SOURCES
scripts/tests/test-macos-launcher.sh"

# 可选参数 1：临时目录的父目录。默认用 TMPDIR（macOS 上指向每个用户的私有目录），
# 只在 TMPDIR 不可写的环境里才需要显式指定。
rf_test_tmp_root=${1:-${TMPDIR:-/tmp}}
rf_test_tmp=$(mktemp -d "$rf_test_tmp_root/resumeforge-macos-test-XXXXXX") || {
    printf '无法在 %s 下创建临时目录。\n' "$rf_test_tmp_root" >&2
    printf '这是一个环境问题，不是被测代码的问题；可以显式指定一个可写目录：\n' >&2
    printf '  bash %s /tmp\n' "$0" >&2
    exit 2
}
if [ ! -d "$rf_test_tmp" ]; then
    printf '临时目录创建失败：%s 不是目录。\n' "$rf_test_tmp" >&2
    exit 2
fi
rf_test_failures=0

cleanup() {
    rm -rf "$rf_test_tmp"
}
trap cleanup EXIT

rf_check() {
    condition=$1
    message=$2
    if [ "$condition" = "0" ]; then
        printf '  ok   %s\n' "$message"
    else
        printf '  FAIL %s\n' "$message"
        rf_test_failures=$((rf_test_failures + 1))
    fi
}

rf_skip() {
    printf '  skip %s\n' "$1"
}

rf_expect_equal() {
    actual=$1
    expected=$2
    message=$3
    if [ "$actual" = "$expected" ]; then
        rf_check 0 "$message"
    else
        rf_check 1 "${message}（实际 '$actual'，期望 '$expected'）"
    fi
}

printf '== 文件形态：换行、编码、可执行位 ==\n'
for relative_path in $RF_SHELL_SOURCES; do
    source_path="$RF_TEST_ROOT/$relative_path"
    if [ ! -s "$source_path" ]; then
        rf_check 1 "$relative_path 不存在或为空"
        continue
    fi
    # CRLF 检查走字节比较而不是 grep 正则：正则里的 \r 在不同工具里解释不同，
    # 而这一项本身就不该有歧义。
    if LC_ALL=C tr -d '\r' <"$source_path" | cmp -s - "$source_path"; then
        rf_check 0 "$relative_path 是纯 LF 换行"
    else
        rf_check 1 "$relative_path 含有 CR：macOS 上会以 'bad interpreter' 失败"
    fi
done

for relative_path in $RF_EXECUTABLE_SOURCES; do
    source_path="$RF_TEST_ROOT/$relative_path"
    [ -s "$source_path" ] || continue
    rf_expect_equal "$(head -n 1 "$source_path")" '#!/bin/bash' "$relative_path 的 shebang 是 #!/bin/bash"
done

# .command 必须在 git 里带可执行位，否则 Finder 双击会被拒绝。
if command -v git >/dev/null 2>&1 && git -C "$RF_TEST_ROOT" rev-parse --git-dir >/dev/null 2>&1; then
    for command_name in start.command stop.command update.command; do
        mode=$(git -C "$RF_TEST_ROOT" ls-files --stage -- "$command_name" 2>/dev/null | awk '{print $1}' | head -n 1)
        if [ -z "$mode" ]; then
            rf_skip "$command_name 还没有被 git 跟踪，无法检查可执行位"
        else
            rf_expect_equal "$mode" "100755" "$command_name 在 git 里是可执行文件（100755）"
        fi
    done
fi

printf '\n== 语法 ==\n'
for relative_path in $RF_SHELL_SOURCES; do
    if bash -n "$RF_TEST_ROOT/$relative_path" 2>"$rf_test_tmp/syntax.txt"; then
        rf_check 0 "$relative_path 语法通过"
    else
        rf_check 1 "$relative_path 语法错误：$(cat "$rf_test_tmp/syntax.txt")"
    fi
done

printf '\n== 变量插值定界（macOS 自带 bash 3.2 的坑）==\n'
# macOS 自带的 /bin/bash 是 **3.2**：它会把变量名后紧跟的**多字节字符首字节**读进变量名。
# 实测 CI 报过 "message<乱码>: unbound variable"——中文文案里插变量必须写成花括号形式。
# 本机的 bash 5 与 PowerShell 都看不见这个问题，只有 CI 的 macOS 作业能暴露，所以钉在这里。
# 判据按字节：C locale 下 [^ -~] 即 >=0x7F（非可打印 ASCII），不依赖 locale 的多字节处理。
for relative_path in $RF_QUOTING_SOURCES; do
    if LC_ALL=C grep -nE '\$[A-Za-z_][A-Za-z0-9_]*[^ -~]' "$RF_TEST_ROOT/$relative_path" \
        >"$rf_test_tmp/bare-var.txt" 2>/dev/null; then
        rf_check 1 "$relative_path 变量后紧跟中文，要写成花括号定界：$(head -n 1 "$rf_test_tmp/bare-var.txt")"
    else
        rf_check 0 "$relative_path 变量插值都有定界"
    fi
done

printf '\n== 自举常量（改版本必须同步改这里）==\n'
# 让 libs 能自己算出默认的工具目录；正常使用时这几个变量由 start.sh 定义。
RF_RUNTIME_DIR="$rf_test_tmp/runtime"
mkdir -p "$RF_RUNTIME_DIR"
# shellcheck source=../macos/lib/common.sh
. "$RF_TEST_ROOT/scripts/macos/lib/common.sh"
# shellcheck source=../macos/lib/python.sh
. "$RF_TEST_ROOT/scripts/macos/lib/python.sh"
# shellcheck source=../macos/lib/node.sh
. "$RF_TEST_ROOT/scripts/macos/lib/node.sh"

rf_expect_equal "$RF_PYTHON_MIN_MAJOR.$RF_PYTHON_MIN_MINOR" "3.10" "Python 版本窗口下界是 3.10"
rf_expect_equal "$RF_PYTHON_MAX_MAJOR.$RF_PYTHON_MAX_MINOR" "3.13" "Python 版本窗口上界是 3.13"
rf_expect_equal "$RF_NODE_MIN_VERSION" "20.19.0" "Node.js 最低版本是 20.19.0"
rf_expect_equal "$RF_NODE_BOOTSTRAP_VERSION" "24.19.0" "便携版 Node.js 钉在 24.19.0"
rf_expect_equal "$RF_PYTHON_BOOTSTRAP_VERSION" "3.12.14" "便携版 Python 钉在 3.12.14"
rf_expect_equal "$RF_PYTHON_BOOTSTRAP_TAG" "20260901" "便携版 Python 钉在 20260901 这一次发布"
rf_expect_equal "$RF_PYTHON_AARCH64_SHA256" "3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76" "Python aarch64 摘要正确"
rf_expect_equal "$RF_PYTHON_X64_SHA256" "2e31b23f3f1319f707d0e620b48847a0046577541d357276821f9f1b5492e0ba" "Python x64 摘要正确"
rf_expect_equal "$RF_NODE_AARCH64_SHA256" "8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d" "Node.js arm64 摘要正确"
rf_expect_equal "$RF_NODE_X64_SHA256" "d1b5e999db158c62fe8f7267a4476b035d8bd93b1a605bac24a3f0dd166e3316" "Node.js x64 摘要正确"

printf '\n== 下载候选 ==\n'
official_python_url="https://github.com/astral-sh/python-build-standalone/releases/download/20260901/cpython-3.12.14+20260901-aarch64-apple-darwin-install_only.tar.gz"
python_urls=$(rf_build_python_bootstrap_urls arm64)
python_url_count=$(printf '%s\n' "$python_urls" | wc -l | tr -d ' ')
rf_expect_equal "$(printf '%s\n' "$python_urls" | tail -n 1)" "$official_python_url" \
    "便携版 Python 的最后一个候选是 GitHub 官方地址"
if [ "$python_urls" = "$official_python_url" ]; then
    rf_check 1 "便携版 Python 必须先试加速站点（当前只有官方地址一个候选）"
else
    rf_check 0 "便携版 Python 先试加速站点，官方放最后"
fi
# 上游 python-build-standalone 用的是 aarch64（不是 arm64）。这条以前写的是 arm64，
# 等于把"拼出来的资产名在上游不存在"当成了规范——CI 上三个源各 404 一次才发现。
rf_expect_equal "$(printf '%s\n' "$python_urls" | grep -c 'aarch64-apple-darwin')" "$python_url_count" \
    "便携版 Python 的每个候选都指向上游口径的 aarch64 包"
rf_expect_equal "$(printf '%s\n' "$python_urls" | grep -c 'arm64-apple-darwin')" "0" \
    "便携版 Python 的候选里没有上游不存在的 arm64 命名"
rf_expect_equal "$(printf '%s\n' "$python_urls" | grep -c '^https://')" "$python_url_count" \
    "便携版 Python 的每个候选都用 https"

node_urls=$(rf_build_node_bootstrap_urls arm64)
node_url_count=$(printf '%s\n' "$node_urls" | wc -l | tr -d ' ')
rf_expect_equal "$(printf '%s\n' "$node_urls" | tail -n 1)" \
    "https://nodejs.org/dist/v24.19.0/node-v24.19.0-darwin-arm64.tar.gz" \
    "便携版 Node.js 的最后一个候选是 nodejs.org"
rf_expect_equal "$(printf '%s\n' "$node_urls" | head -n 1 | grep -c 'nodejs\.org')" "0" \
    "便携版 Node.js 先试国内镜像"
rf_expect_equal "$(printf '%s\n' "$node_urls" | grep -c 'node-v24.19.0-darwin-arm64.tar.gz$')" "$node_url_count" \
    "便携版 Node.js 的每个候选都指向同一个包"
rf_expect_equal "$(printf '%s\n' "$node_urls" | grep -c '^https://')" "$node_url_count" \
    "便携版 Node.js 的每个候选都用 https"

printf '\n== 架构识别 ==\n'
# 用同名函数遮蔽 uname，避免依赖真实的处理器架构。
uname() { echo "arm64"; }
rf_expect_equal "$(detect_macos_arch)" "arm64" "arm64 映射为 Node 的 arm64"
uname() { echo "x86_64"; }
rf_expect_equal "$(detect_macos_arch)" "x64" "x86_64 映射为 Node 的 x64"

printf '\n== 版本比较 ==\n'
if rf_version_ge "20.19.0" "20.19.0"; then rf_check 0 "20.19.0 >= 20.19.0"; else rf_check 1 "20.19.0 >= 20.19.0"; fi
if rf_version_ge "20.19.1" "20.19.0"; then rf_check 0 "20.19.1 >= 20.19.0"; else rf_check 1 "20.19.1 >= 20.19.0"; fi
if rf_version_ge "22.0.0" "20.19.0"; then rf_check 0 "22.0.0 >= 20.19.0"; else rf_check 1 "22.0.0 >= 20.19.0"; fi
if rf_version_ge "20.18.9" "20.19.0"; then rf_check 1 "20.18.9 < 20.19.0"; else rf_check 0 "20.18.9 < 20.19.0"; fi
if rf_version_ge "19.99.99" "20.19.0"; then rf_check 1 "19.99.99 < 20.19.0"; else rf_check 0 "19.99.99 < 20.19.0"; fi

printf '\n== 虚拟环境版本窗口 ==\n'
venv_config="$rf_test_tmp/pyvenv.cfg"
printf 'home = /opt/tools/python\nversion = 3.12.14\n' >"$venv_config"
if rf_venv_version_supported "$venv_config"; then rf_check 0 "3.12 的 venv 可以复用"; else rf_check 1 "3.12 的 venv 可以复用"; fi
printf 'home = /opt/tools/python\nversion = 3.10.21\n' >"$venv_config"
if rf_venv_version_supported "$venv_config"; then rf_check 0 "3.10 的 venv 可以复用"; else rf_check 1 "3.10 的 venv 可以复用"; fi
printf 'home = /opt/tools/python\nversion = 3.13.15\n' >"$venv_config"
if rf_venv_version_supported "$venv_config"; then rf_check 0 "3.13 的 venv 可以复用"; else rf_check 1 "3.13 的 venv 可以复用"; fi
printf 'home = /opt/tools/python\nversion = 3.14.7\n' >"$venv_config"
if rf_venv_version_supported "$venv_config"; then rf_check 1 "3.14 的 venv 必须被拒绝"; else rf_check 0 "3.14 的 venv 必须被拒绝"; fi
printf 'home = /opt/tools/python\nversion = 3.9.6\n' >"$venv_config"
if rf_venv_version_supported "$venv_config"; then rf_check 1 "3.9 的 venv 必须被拒绝"; else rf_check 0 "3.9 的 venv 必须被拒绝"; fi
printf 'home = /opt/tools/python\n' >"$venv_config"
if rf_venv_version_supported "$venv_config"; then rf_check 1 "缺少 version 行必须被拒绝"; else rf_check 0 "缺少 version 行必须被拒绝"; fi
if rf_venv_version_supported "$rf_test_tmp/no-such-cfg"; then rf_check 1 "配置文件不存在必须被拒绝"; else rf_check 0 "配置文件不存在必须被拒绝"; fi

printf '\n== Node 运行时判定 ==\n'
mkdir -p "$rf_test_tmp/nodebin"
# 版本号写进桩脚本本身，而不是用环境变量：被测函数调用桩时不会再带上我们的环境。
make_version_stub() {
    stub_path=$1
    stub_output=$2
    {
        printf '#!/bin/sh\n'
        printf 'echo "%s"\n' "$stub_output"
    } >"$stub_path"
    chmod +x "$stub_path"
}
old_node="$rf_test_tmp/nodebin/old-node"
minimum_node="$rf_test_tmp/nodebin/min-node"
stub_npm="$rf_test_tmp/nodebin/npm"
make_version_stub "$old_node" "v20.18.0"
make_version_stub "$minimum_node" "v20.19.0"
make_version_stub "$stub_npm" "11.0.0"

if rf_node_runtime_candidate_ok "$old_node" "$stub_npm"; then
    rf_check 1 "低于 20.19.0 的 Node 必须被拒绝"
else
    rf_check 0 "低于 20.19.0 的 Node 必须被拒绝"
fi
if rf_node_runtime_candidate_ok "$minimum_node" "$stub_npm"; then
    rf_check 0 "20.19.0 且带 npm 必须被接受"
else
    rf_check 1 "20.19.0 且带 npm 必须被接受"
fi
if rf_node_runtime_candidate_ok "$minimum_node" "$rf_test_tmp/nodebin/no-such-npm"; then
    rf_check 1 "缺 npm 必须被拒绝"
else
    rf_check 0 "缺 npm 必须被拒绝"
fi

# 这些用例依赖 BSD 风格的 ps（-o args= / -o lstart=）与 pgrep。macOS 上都有；
# Windows 的 Git Bash 上都没有。缺能力时明确跳过，而不是把环境差异报成代码缺陷
# ——否则这个测试在本机跑会永久飘红，真正的红灯就被淹没了。
rf_probe_process_capability() {
    command -v pgrep >/dev/null 2>&1 || return 1
    sleep 60 >/dev/null 2>&1 &
    probe_pid=$!
    probe_args=$(process_command_line "$probe_pid")
    probe_signature=$(process_start_signature "$probe_pid")
    kill "$probe_pid" 2>/dev/null
    wait "$probe_pid" 2>/dev/null
    [ -n "$probe_args" ] && [ -n "$probe_signature" ]
}

if rf_probe_process_capability; then
    printf '\n== 进程记录：只认自己启动的那个进程 ==\n'
    sleep 300 >/dev/null 2>&1 &
    test_pid=$!
    record_path="$rf_test_tmp/payload.pid"
    save_process_record "$test_pid" "$record_path"
    rf_expect_equal "$(process_record_field "$record_path" "process_id")" "$test_pid" "记录里的 PID 可以读回"
    rf_expect_equal "$(process_record_field "$record_path" "start_signature")" "$(process_start_signature "$test_pid")" \
        "记录里的启动签名与进程一致"
    if process_record_match "$record_path" "sleep"; then
        rf_check 0 "命令行匹配时记录命中"
    else
        rf_check 1 "命令行匹配时记录命中"
    fi
    if process_record_match "$record_path" "uvicorn"; then
        rf_check 1 "命令行不匹配时记录必须落空"
    else
        rf_check 0 "命令行不匹配时记录必须落空"
    fi

    # PID 复用：同一个 PID、不同的启动时刻。拒绝这一条正是"绝不误杀无关进程"的保证。
    save_process_record "$test_pid" "$rf_test_tmp/reused.pid"
    sed 's/^start_signature=.*/start_signature=Thu Jan  1 00:00:00 1970/' \
        "$rf_test_tmp/reused.pid" >"$rf_test_tmp/reused-stale.pid"
    if process_record_match "$rf_test_tmp/reused-stale.pid" "sleep"; then
        rf_check 1 "启动时刻对不上时必须拒绝"
    else
        rf_check 0 "启动时刻对不上时必须拒绝"
    fi
    if process_record_match "$rf_test_tmp/no-such-record.pid" "sleep"; then
        rf_check 1 "记录不存在时必须拒绝"
    else
        rf_check 0 "记录不存在时必须拒绝"
    fi
    printf 'process_id=999999999\n' >"$rf_test_tmp/dead.pid"
    if process_record_match "$rf_test_tmp/dead.pid" "sleep"; then
        rf_check 1 "PID 不存在时必须拒绝"
    else
        rf_check 0 "PID 不存在时必须拒绝"
    fi

    stop_recorded_process "test sleep" "$record_path" "sleep"
    if kill -0 "$test_pid" 2>/dev/null; then
        rf_check 1 "stop_recorded_process 应当停掉进程"
    else
        rf_check 0 "stop_recorded_process 应当停掉进程"
    fi
    if [ -f "$record_path" ]; then
        rf_check 1 "stop_recorded_process 应当删掉记录"
    else
        rf_check 0 "stop_recorded_process 应当删掉记录"
    fi

    # 记录与进程对不上时必须**不动**它，并保留记录让用户自己判断。
    sleep 300 >/dev/null 2>&1 &
    survivor_pid=$!
    cp "$rf_test_tmp/reused-stale.pid" "$rf_test_tmp/mismatch.pid"
    stop_recorded_process "mismatched" "$rf_test_tmp/mismatch.pid" "sleep" 2>/dev/null
    if kill -0 "$survivor_pid" 2>/dev/null; then
        rf_check 0 "记录不匹配时不得停止进程"
    else
        rf_check 1 "记录不匹配时不得停止进程"
    fi
    if [ -f "$rf_test_tmp/mismatch.pid" ]; then
        rf_check 0 "记录不匹配时保留记录文件"
    else
        rf_check 1 "记录不匹配时保留记录文件"
    fi
    kill "$survivor_pid" 2>/dev/null
    wait "$survivor_pid" 2>/dev/null

    printf '\n== 进程树停止 ==\n'
    # 前端那棵树是 npm -> node -> esbuild，只杀最上面一个会让端口一直占着。
    /bin/sh -c 'sleep 300 & sleep 300' >/dev/null 2>&1 &
    tree_pid=$!
    sleep 1
    tree_children=$(pgrep -P "$tree_pid" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$tree_children" -ge 1 ]; then
        rf_check 0 "测试进程树有 $tree_children 个子进程"
    else
        rf_check 1 "测试进程树没有子进程，这项测试本身失效"
    fi
    stop_process_tree "$tree_pid" TERM
    sleep 1
    tree_survivors=0
    for child in $(pgrep -P "$tree_pid" 2>/dev/null); do
        tree_survivors=$((tree_survivors + 1))
    done
    if kill -0 "$tree_pid" 2>/dev/null; then
        tree_survivors=$((tree_survivors + 1))
    fi
    rf_expect_equal "$tree_survivors" "0" "stop_process_tree 停掉了整棵树"
else
    rf_skip "本机的 ps 不支持 -o args=/-o lstart=，或没有 pgrep（Windows 的 Git Bash 就是这样），跳过进程记录与进程树用例；它们在 macOS CI 上会真正执行。"
fi

printf '\n== 日志尾巴 ==\n'
log_path="$rf_test_tmp/backend.stderr.log"
printf '\nINFO started\n\nRuntimeError: incomplete installation\n' >"$log_path"
rf_expect_equal "$(log_tail "$log_path" | wc -l | tr -d ' ')" "2" "log_tail 丢掉空行"
rf_expect_equal "$(log_tail "$log_path" 1)" "RuntimeError: incomplete installation" "log_tail 保留最后一行"
rf_expect_equal "$(log_tail "$rf_test_tmp/no-such.log" | wc -l | tr -d ' ')" "0" "日志不存在时返回空而不是报错"

printf '\n== 下载校验 ==\n'
good_file="$rf_test_tmp/good.bin"
printf 'resumeforge' >"$good_file"
good_sha=$(sha256_of "$good_file")
rf_expect_equal "$(printf '%s' "$good_sha" | wc -c | tr -d ' ')" "64" "sha256_of 输出 64 位十六进制摘要"

# 用 file:// 让 curl 走一次完整的下载路径。个别环境下 curl 不支持 file://，
# 那就跳过这两项而不是误报失败。
if download_file "file://$good_file" "$rf_test_tmp/probe.bin" 2>/dev/null; then
    if download_verified "$rf_test_tmp/target.bin" "$good_sha" "测试包" "0" "file://$good_file"; then
        rf_check 0 "摘要匹配时接受下载结果"
    else
        rf_check 1 "摘要匹配时接受下载结果"
    fi
    if download_verified "$rf_test_tmp/target2.bin" \
        "0000000000000000000000000000000000000000000000000000000000000000" \
        "测试包" "0" "file://$good_file" 2>/dev/null; then
        rf_check 1 "摘要不匹配时必须拒绝下载结果"
    else
        rf_check 0 "摘要不匹配时必须拒绝下载结果"
    fi
else
    rf_skip "当前环境的 curl 不支持 file://，跳过下载校验用例"
fi

printf '\n'
if [ "$rf_test_failures" -eq 0 ]; then
    printf 'macOS 启动链测试全部通过。\n'
    exit 0
fi
printf 'macOS 启动链测试失败 %d 项。\n' "$rf_test_failures"
exit 1

#!/bin/bash
# ResumeForge 停止器（macOS）。
#
# 与 Windows 侧 stop.cmd / Stop-ResumeForge.ps1 对应：按 PID 记录停掉后端与前端。
# 只停"记录对得上的"进程——PID 存在、命令行匹配、启动时刻签名一致，三者缺一不可，
# 所以 PID 被复用或记录过期时不会误杀无关程序。
#
# 用法：双击项目根目录的 stop.command，或 bash scripts/macos/stop.sh

set -euo pipefail

RF_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RF_PROJECT_ROOT=$(cd "$RF_SCRIPT_DIR/../.." && pwd)
RF_RUNTIME_DIR="$RF_PROJECT_ROOT/runtime"

# shellcheck source=lib/common.sh
. "$RF_SCRIPT_DIR/lib/common.sh"

# 与 start.sh 保持一致：这几个片段是"这确实是我们启动的进程"的特征。
RF_BACKEND_COMMAND_PATTERN='uvicorn app.main:app'
RF_FRONTEND_COMMAND_PATTERN='run dev.*--strictPort'

RF_BACKEND_RECORD="$RF_RUNTIME_DIR/backend.macos.pid"
RF_FRONTEND_RECORD="$RF_RUNTIME_DIR/frontend.macos.pid"

rf_stop_one() {
    display_name=$1
    record=$2
    pattern=$3

    if [ ! -f "$record" ]; then
        log_info "${display_name}：没有找到运行记录（可能本来就没启动）。"
        return 0
    fi

    if ! process_record_match "$record" "$pattern"; then
        recorded_pid=$(process_record_field "$record" "process_id")
        log_warn "${display_name}：记录与当前进程对不上，**没有**停止任何进程。"
        log_warn "记录里的 PID 是 ${recorded_pid}。如果确认那还是简历通的进程，可以手动停止："
        log_warn "    kill ${recorded_pid}"
        log_warn "如果这个 PID 已经被系统分配给别人了（PID 会被复用），删掉记录即可："
        log_warn "    rm -f $record"
        return 0
    fi

    stop_recorded_process "$display_name" "$record" "$pattern"
}

log_info "正在停止 ResumeForge..."
rf_stop_one "backend" "$RF_BACKEND_RECORD" "$RF_BACKEND_COMMAND_PATTERN"
rf_stop_one "frontend" "$RF_FRONTEND_RECORD" "$RF_FRONTEND_COMMAND_PATTERN"
printf '\n'
log_ok "已完成。数据都在 data/ 目录里，没有被动过。"

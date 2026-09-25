#!/bin/bash
# 简历通（ResumeForge）macOS 停止入口 —— 在 Finder 里双击这个文件即可。
# 也可以在终端里执行：bash stop.command

cd "$(dirname "${BASH_SOURCE[0]:-$0}")" || exit 1

bash "scripts/macos/stop.sh" "$@"
status=$?

if [ "$status" -ne 0 ]; then
    printf '\n按回车键关闭这个窗口。\n'
    read -r _
fi
exit "$status"

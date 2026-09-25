#!/bin/bash
# 简历通（ResumeForge）macOS 更新入口 —— 在 Finder 里双击这个文件即可。
#
# 只更新程序文件：data/（数据库、数据集、备份）与 .env 永远不会被覆盖。
# 建议先双击 stop.command 停掉服务再更新。
#
# 也可以在终端里执行：bash update.command --dry-run   （先看看会做什么）

cd "$(dirname "${BASH_SOURCE[0]:-$0}")" || exit 1

bash "scripts/macos/update.sh" "$@"
status=$?

if [ "$status" -ne 0 ]; then
    printf '\n按回车键关闭这个窗口。\n'
    read -r _
fi
exit "$status"

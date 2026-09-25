#!/bin/bash
# 简历通（ResumeForge）macOS 启动入口 —— 在 Finder 里双击这个文件即可。
#
# 双击时系统会用「终端」打开它。如果双击没反应（例如解压工具丢掉了可执行位），
# 在「终端」里进入项目目录后执行下面这行，效果完全一样：
#     bash start.command
#
# 首次打开时，如果 macOS 提示"无法打开，因为 Apple 无法检查它是否包含恶意软件"：
# 在 Finder 里**右键点它 → 打开**，再在弹窗里点一次「打开」。只需做一次。
# 原因见 README 的「macOS 用户看这里」，与代码本身无关。

cd "$(dirname "${BASH_SOURCE[0]:-$0}")" || exit 1

bash "scripts/macos/start.sh" "$@"
status=$?

if [ "$status" -ne 0 ]; then
    printf '\n按回车键关闭这个窗口。\n'
    read -r _
fi
exit "$status"

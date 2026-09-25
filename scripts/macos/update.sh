#!/bin/bash
# ResumeForge 更新器（macOS）。
#
# 与 Windows 侧 scripts/Update-ResumeForge.ps1 对应，只更新**程序文件**。
# 用户数据在 data/（数据库、数据集、备份）和 .env 里，这两个位置永远不会被覆盖；
# runtime/、backend/.venv、frontend/node_modules 同样保留——它们要么是本地环境，
# 要么是重装一次要几分钟的产物。
#
# 两种模式：
#   * 目录是 git 检出的（存在 .git 且有 git）  -> git pull --ff-only
#   * 普通解压目录                            -> 下载仓库 zip 并覆盖程序文件
#
# 用法：双击项目根目录的 update.command，或
#   bash scripts/macos/update.sh [--dry-run] [--skip-dependencies] [--archive 路径]

set -euo pipefail

RF_SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RF_PROJECT_ROOT=$(cd "$RF_SCRIPT_DIR/../.." && pwd)
RF_RUNTIME_DIR="$RF_PROJECT_ROOT/runtime"

RF_REPOSITORY=${RESUMEFORGE_UPDATE_REPO:-magicapple123/ResumeForge}
RF_ARCHIVE_URL="https://github.com/${RF_REPOSITORY}/archive/refs/heads/main.zip"

RF_DRY_RUN=0
RF_SKIP_DEPENDENCIES=0
RF_ARCHIVE_PATH=""
RF_RESTART=0

: "${RF_TOOLS_DIR:=$RF_RUNTIME_DIR/tools}"

# shellcheck source=lib/common.sh
. "$RF_SCRIPT_DIR/lib/common.sh"
# shellcheck source=lib/node.sh
. "$RF_SCRIPT_DIR/lib/node.sh"

RF_DOWNLOAD_TIMEOUT_SECONDS=1800

# 属于用户或本地环境的名字，一律不覆盖。
RF_EXCLUDED_NAMES='data runtime .git .env node_modules .venv dist __pycache__ .pytest_cache coverage'

rf_usage() {
    cat <<'USAGE'
用法：update.command [选项]

选项：
  --dry-run              只说明会做什么，不改动任何文件
  --skip-dependencies    跳过依赖同步
  --archive PATH         用本地已下载的 zip 更新（而不是联网获取）
  --restart              更新完成后尝试打开 start.command
  -h, --help             显示这段说明
USAGE
}

rf_parse_arguments() {
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --dry-run)
                RF_DRY_RUN=1
                shift
                ;;
            --skip-dependencies)
                RF_SKIP_DEPENDENCIES=1
                shift
                ;;
            --archive)
                [ "$#" -ge 2 ] || die "--archive 后面缺少文件路径。"
                RF_ARCHIVE_PATH=$2
                shift 2
                ;;
            --restart)
                RF_RESTART=1
                shift
                ;;
            -h | --help)
                rf_usage
                exit 0
                ;;
            *)
                die "无法识别的参数：$1" "执行 update.command --help 可以看到全部可用选项。"
                ;;
        esac
    done
}

rf_is_excluded() {
    for excluded in $RF_EXCLUDED_NAMES; do
        if [ "$1" = "$excluded" ]; then
            return 0
        fi
    done
    return 1
}

# 递归合并复制程序文件。"$src"/.[!.]* 用来覆盖隐藏文件；没有隐藏文件时
# glob 不展开，[ -e ] 会把它挡掉。
rf_copy_program_files() {
    src=$1
    dst=$2
    mkdir -p "$dst"
    for entry in "$src"/* "$src"/.[!.]*; do
        [ -e "$entry" ] || continue
        name=$(basename "$entry")
        if rf_is_excluded "$name"; then
            continue
        fi
        if [ -d "$entry" ]; then
            rf_copy_program_files "$entry" "$dst/$name"
        else
            cp -f "$entry" "$dst/$name"
        fi
    done
}

rf_prepare_staging() {
    RF_STAGING="$RF_RUNTIME_DIR/update-$(date '+%Y%m%d-%H%M%S')"
    mkdir -p "$RF_STAGING"
}

# 把下载或指定的压缩包解开，并把解出来的顶层目录路径写进 RF_EXTRACTED。
rf_extract_archive() {
    archive_path=$1
    if ! unzip -q -o "$archive_path" -d "$RF_STAGING"; then
        die "解压更新包失败：$archive_path" \
            "确认文件完整（重新下载一次），或改用 --archive 指定另一个文件。"
    fi
    RF_EXTRACTED=""
    for entry in "$RF_STAGING"/*; do
        if [ -d "$entry" ]; then
            RF_EXTRACTED=$entry
            break
        fi
    done
    if [ -z "$RF_EXTRACTED" ]; then
        die "更新包里没有找到任何目录。" \
            "到 https://github.com/${RF_REPOSITORY}/releases 手动下载完整安装包。"
    fi
}

# 依赖同步：venv 与 node_modules 都在才做，否则让下次 start 自己处理。
rf_sync_dependencies() {
    if [ "$RF_SKIP_DEPENDENCIES" -eq 1 ]; then
        log_info "==> 已跳过依赖同步（--skip-dependencies）"
        return 0
    fi

    requirements="$RF_PROJECT_ROOT/backend/requirements.txt"
    venv_python="$RF_PROJECT_ROOT/backend/.venv/bin/python3"
    if [ -f "$requirements" ] && [ -x "$venv_python" ]; then
        log_info "==> 正在同步后端依赖"
        if ! "$venv_python" -m pip install --disable-pip-version-check -r "$requirements"; then
            log_warn "后端依赖同步失败，但程序文件已经更新。下次启动会再试一次。"
        fi
    else
        log_info "    没有找到后端的虚拟环境；下次启动时会自动创建。"
    fi

    if [ -f "$RF_PROJECT_ROOT/frontend/package.json" ] &&
        [ -d "$RF_PROJECT_ROOT/frontend/node_modules" ] &&
        rf_find_system_node_runtime; then
        log_info "==> 正在同步前端依赖（npm ci）"
        if ! (cd "$RF_PROJECT_ROOT/frontend" && "$RF_NPM_PATH" ci --no-audit --no-fund); then
            log_warn "前端依赖同步失败，但程序文件已经更新。下次启动会再试一次。"
        fi
    else
        log_info "    前端依赖不完整或本机没有 Node；下次启动时会自动处理。"
    fi
}

rf_main() {
    rf_parse_arguments "$@"

    log_info "ResumeForge 更新器"
    log_info "项目目录：$RF_PROJECT_ROOT"
    if [ "$RF_DRY_RUN" -eq 1 ]; then
        log_warn "演练模式：不会改动任何文件。"
    fi

    if [ -n "$RF_ARCHIVE_PATH" ]; then
        if [ ! -f "$RF_ARCHIVE_PATH" ]; then
            die "找不到更新包：$RF_ARCHIVE_PATH"
        fi
        if [ "$RF_DRY_RUN" -eq 1 ]; then
            log_warn "会用本地更新包 $RF_ARCHIVE_PATH 覆盖程序文件（data、.env、runtime 会保留）。"
        else
            log_info "==> 正在准备本地更新包"
            rf_prepare_staging
            rf_extract_archive "$RF_ARCHIVE_PATH"
            log_info "==> 正在复制程序文件（data、.env、runtime 会保留）"
            rf_copy_program_files "$RF_EXTRACTED" "$RF_PROJECT_ROOT"
            log_dim "    解压出来的内容保留在：$RF_STAGING"
        fi
    elif [ -d "$RF_PROJECT_ROOT/.git" ] && command_exists git; then
        if [ "$RF_DRY_RUN" -eq 1 ]; then
            log_warn "会执行 git pull --ff-only（目录是 git 检出的）。"
        else
            log_info "==> 正在拉取最新代码（git pull --ff-only）"
            if ! git -C "$RF_PROJECT_ROOT" pull --ff-only; then
                die "git pull 失败。" \
                    "常见原因是本地有未提交的改动、或分支有冲突。" \
                    "怎么办：在项目目录里先执行 git status 看清楚，处理完再重试；" \
                    "或者删掉 .git 目录改用普通解压目录的更新方式。"
            fi
        fi
    elif [ "$RF_DRY_RUN" -eq 1 ]; then
        log_warn "会下载 $RF_ARCHIVE_URL 并覆盖 $RF_PROJECT_ROOT 的程序文件。"
        log_dim "    data、.env、runtime、.venv、node_modules 会保留。"
    else
        log_info "==> 正在下载最新代码包"
        rf_prepare_staging
        archive="$RF_STAGING/resumeforge.zip"
        if ! download_file "$RF_ARCHIVE_URL" "$archive"; then
            die "下载更新包失败：$RF_ARCHIVE_URL" \
                "怎么办：" \
                "  1) 用浏览器打开 https://github.com/${RF_REPOSITORY}/releases 手动下载安装包，" \
                "     再用 update.command --archive 路径 来更新；" \
                "  2) 需要代理时，先在终端里 export HTTPS_PROXY=http://127.0.0.1:端口 再重试。"
        fi
        rf_extract_archive "$archive"
        log_info "==> 正在复制程序文件（data、.env、runtime 会保留）"
        rf_copy_program_files "$RF_EXTRACTED" "$RF_PROJECT_ROOT"
        log_dim "    解压出来的内容保留在：$RF_STAGING"
    fi

    if [ "$RF_DRY_RUN" -ne 1 ]; then
        rf_sync_dependencies
    fi

    printf '\n'
    if [ "$RF_DRY_RUN" -eq 1 ]; then
        log_warn "演练结束：没有下载、复制或安装任何东西。"
        return 0
    fi

    log_ok "更新完成。"
    log_ok "用 start.command 重新启动即可；data/ 里的数据没有被改动。"
    if [ "$RF_RESTART" -eq 1 ]; then
        log_info "==> 正在重新启动简历通"
        if [ -f "$RF_PROJECT_ROOT/start.command" ]; then
            open "$RF_PROJECT_ROOT/start.command"
        else
            log_warn "没有找到 start.command，未能自动重启。"
        fi
    fi
}

# 只有直接执行时才跑主流程，理由同 start.sh。
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    rf_main "$@"
fi

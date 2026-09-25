# ResumeForge macOS 启动链：Python 解释器的查找与自举。
#
# 设计原则与 Windows 侧一致：**不要求用户先装任何东西**。
#   1. 先用机器上已有的解释器（PATH、Homebrew、pyenv、本启动器上次装好的便携版）；
#   2. 都不行就下载一份**便携版 CPython**（python-build-standalone 的 install_only 包），
#      解压到 runtime/tools/ 里直接用。
#
# 为什么不走 python.org 的 .pkg：那个安装器**需要管理员密码**（installer -pkg 必须 sudo）。
# 一个"双击就能用"的启动器不该在最开头弹管理员授权；便携版完全在用户目录里，
# 删掉项目目录就等于卸载干净。
#
# 版本窗口：与 Windows 侧同一组常量（3.10 ~ 3.13）。backend/requirements.txt 的钉版
# 没有 Python 3.14 的轮子，放宽上界等于让用户去编译 pydantic-core（需要 Rust）。
# 有意**不**把 /usr/bin/python3 当候选：macOS 自带的那条是 Xcode 命令行工具的
# 转调桩，命令行工具没装时运行它会**弹出一个图形安装提示**——在一个无人值守的
# 启动脚本里弹窗是最糟的失败方式；而且它对应的是 3.9，本来就不在窗口里。

: "${RF_PYTHON_MIN_MAJOR:=3}"
: "${RF_PYTHON_MIN_MINOR:=10}"
: "${RF_PYTHON_MAX_MAJOR:=3}"
: "${RF_PYTHON_MAX_MINOR:=13}"
: "${RF_PYTHON_BOOTSTRAP_VERSION:=3.12.14}"
: "${RF_PYTHON_BOOTSTRAP_TAG:=20260901}"
# 便携版 CPython 的摘要写死在仓库里，不来自任何镜像：镜像只能"慢或旧"，不能替换内容。
: "${RF_PYTHON_AARCH64_SHA256:=3ee3ee547cedfeb7c2b16b2b7156039f7b470bb8f857e226fd3d2eb11db83c76}"
: "${RF_PYTHON_X64_SHA256:=2e31b23f3f1319f707d0e620b48847a0046577541d357276821f9f1b5492e0ba}"
: "${RF_PYTHON_BOOTSTRAP_APPROX_MB:=25}"
: "${RF_TOOLS_DIR:=$RF_RUNTIME_DIR/tools}"
# 官方 release 直链在国内经常很慢，先试两个 GitHub 加速前缀，官方放最后。
# 每个候选都要过上面那对摘要，所以加速站无法替换内容——它只能"帮你搬"或"搬得慢"。
: "${RF_PYTHON_MIRROR_BASES:=https://ghproxy.net/https://github.com https://gh-proxy.com/https://github.com}"

# 支持的版本区间，用于面向用户的文案，避免文案与常量漂移。
rf_python_window() {
    printf '%s.%s-%s.%s' \
        "$RF_PYTHON_MIN_MAJOR" "$RF_PYTHON_MIN_MINOR" \
        "$RF_PYTHON_MAX_MAJOR" "$RF_PYTHON_MAX_MINOR"
}

rf_python_handle_text() {
    printf 'Python %s' "$(rf_python_window)"
}

# 给定解释器路径，判断是否落在窗口内。探针是"什么都不做，只退出码说话"，
# 所以它不会安装、不会联网、不会写文件。
rf_python_is_supported() {
    candidate=$1
    [ -n "$candidate" ] || return 1
    [ -x "$candidate" ] || return 1
    "$candidate" -c "import sys; raise SystemExit(0 if (${RF_PYTHON_MIN_MAJOR}, ${RF_PYTHON_MIN_MINOR}) <= sys.version_info[:2] <= (${RF_PYTHON_MAX_MAJOR}, ${RF_PYTHON_MAX_MINOR}) else 1)" \
        >/dev/null 2>&1
}

rf_python_reported_version() {
    "$1" -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>/dev/null
}

# 依次探测候选，找到第一个落在窗口内的解释器，路径写入 RF_PYTHON。
# 返回 0 表示找到。
rf_find_system_python() {
    RF_PYTHON=""

    candidates=""
    # 1) PATH 上带版本号的名字先试：它们比裸 python3 更可能正好是窗口内的版本。
    for name in python3.13 python3.12 python3.11 python3.10 python3; do
        if command_exists "$name"; then
            candidates="$candidates $(command -v "$name")"
        fi
    done
    # 2) Homebrew（Apple 芯片与 Intel 两种前缀）与 pyenv 的常见位置。
    #    Explorer/Finder 启动的进程不一定继承 shell 的 PATH，所以必须显式列。
    for prefix in /opt/homebrew /usr/local; do
        for minor in 13 12 11 10; do
            candidates="$candidates $prefix/opt/python@3.$minor/bin/python3.$minor"
        done
        candidates="$candidates $prefix/bin/python3"
    done
    if [ -n "${HOME:-}" ] && [ -d "$HOME/.pyenv/versions" ]; then
        for pyenv_python in "$HOME"/.pyenv/versions/3.1[0-3]*/bin/python3; do
            candidates="$candidates $pyenv_python"
        done
    fi
    # 3) 本启动器上一次装好的便携版。
    for portable_python in "$RF_TOOLS_DIR"/python-*/bin/python3; do
        candidates="$candidates $portable_python"
    done

    for candidate in $candidates; do
        # 保留符号链接的真实路径，后面 pyvenv.cfg 的 home 指向它。
        if rf_python_is_supported "$candidate"; then
            RF_PYTHON=$candidate
            return 0
        fi
        # 找到名字却版本不对（例如机器上只有 3.14）时说出来，别让用户以为没找到。
        if [ -x "$candidate" ]; then
            reported=$(rf_python_reported_version "$candidate")
            if [ -n "$reported" ]; then
                log_dim "    跳过 ${candidate}（版本 ${reported}，不在 $(rf_python_window) 内）"
            fi
        fi
    done
    return 1
}

# 便携版 CPython 下载地址表，一行一个（调用方按空白拆开即可）。
rf_build_python_bootstrap_urls() {
    arch=$1
    # 架构名要换成**上游口径**：python-build-standalone 用的是 aarch64 / x86_64，
    # 而本仓库内部的架构名（与 Node 发行包一致）是 arm64 / x64。少了这一步，
    # 拼接出来的资产名在上游不存在——CI 上就是三个源各 404 一次然后整体失败。
    case "$arch" in
        arm64) upstream_arch=aarch64 ;;
        x64) upstream_arch=x86_64 ;;
        *) upstream_arch=$arch ;;
    esac
    archive="cpython-${RF_PYTHON_BOOTSTRAP_VERSION}+${RF_PYTHON_BOOTSTRAP_TAG}-${upstream_arch}-apple-darwin-install_only.tar.gz"
    upstream="astral-sh/python-build-standalone/releases/download/${RF_PYTHON_BOOTSTRAP_TAG}/${archive}"

    for base in $RF_PYTHON_MIRROR_BASES; do
        printf '%s/%s\n' "$base" "$upstream"
    done
    printf 'https://github.com/%s\n' "$upstream"
}

rf_python_bootstrap_sha256() {
    case "$1" in
        arm64) printf '%s\n' "$RF_PYTHON_AARCH64_SHA256" ;;
        x64) printf '%s\n' "$RF_PYTHON_X64_SHA256" ;;
        *) return 1 ;;
    esac
}

# 下载并解压便携版 CPython。成功后 RF_PYTHON 指向它。
# install_only 包的顶层目录固定叫 python/，所以解压后要搬一层。
rf_install_portable_python() {
    arch=$1
    expected_sha=$(rf_python_bootstrap_sha256 "$arch") || \
        die "没有为架构 ${arch} 准备便携版 Python。" \
            "这通常意味着脚本里的架构判断出了变化，请把这个报错发到项目的 GitHub Issues。"

    target_dir="$RF_TOOLS_DIR/python-${RF_PYTHON_BOOTSTRAP_VERSION}-macos-${arch}"
    target_python="$target_dir/bin/python3"
    if rf_python_is_supported "$target_python"; then
        RF_PYTHON=$target_python
        return 0
    fi

    mkdir -p "$RF_TOOLS_DIR"
    staging=$(mktemp -d "$RF_TOOLS_DIR/python-bootstrap-XXXXXX") || \
        die "无法在 $RF_TOOLS_DIR 下创建临时目录。" \
            "确认项目目录可写（没有被设为只读、也没有被安全软件锁定）。"

    archive_path="$staging/python.tar.gz"
    urls=$(rf_build_python_bootstrap_urls "$arch")

    # shellcheck disable=SC2086  # 需要按空白拆成多个候选 URL
    if ! download_verified "$archive_path" "$expected_sha" \
        "便携版 $(rf_python_handle_text)" "$RF_PYTHON_BOOTSTRAP_APPROX_MB" $urls; then
        rm -rf "$staging"
        die "所有下载源都没能拿到便携版 Python。" \
            "可能原因：网络不通、公司代理，或者 GitHub Releases 被拦。" \
            "怎么办（按顺序试）：" \
            "  1) 用浏览器打开 https://github.com/astral-sh/python-build-standalone/releases 确认能否访问；" \
            "  2) 需要代理时，先在终端里 export HTTPS_PROXY=http://127.0.0.1:端口 再重试；" \
            "  3) 也可以自己装一个 $(rf_python_handle_text)（python.org 的 .pkg 或 Homebrew 都行），" \
            "     装好后重新双击 start.command。"
    fi

    log_info "校验通过，正在解压便携版 Python..."
    if ! tar -xzf "$archive_path" -C "$staging"; then
        rm -rf "$staging"
        die "解压便携版 Python 失败（压缩包可能不完整）。" \
            "删掉 runtime/tools 里以 python-bootstrap- 开头的目录后重新双击 start.command。"
    fi
    if [ ! -x "$staging/python/bin/python3" ]; then
        rm -rf "$staging"
        die "解压出来的便携版 Python 里没有 bin/python3。" \
            "请把这条报错发到项目的 GitHub Issues。"
    fi

    rm -rf "$target_dir"
    mv "$staging/python" "$target_dir"
    rm -rf "$staging"

    if ! rf_python_is_supported "$target_python"; then
        die "便携版 Python 装好了，但它无法运行。" \
            "在终端里执行下面这行看看完整报错，并把结果发到 GitHub Issues：" \
            "  $target_python -V"
    fi

    # macOS 首次运行外来可执行文件时会做签名校验；curl 下载的文件不带隔离属性，
    # 但如果用户手工解压过 zip，这里顺手清一次，避免 Gatekeeper 把启动挡在门口。
    xattr -dr com.apple.quarantine "$target_dir" 2>/dev/null || true

    RF_PYTHON=$target_python
    return 0
}

# 确保有一个可用的系统级解释器。成功后 RF_PYTHON 可执行。
rf_ensure_system_python() {
    if rf_find_system_python; then
        return 0
    fi

    arch=$(detect_macos_arch)
    log_info "没有找到受支持的 $(rf_python_handle_text)，正在自动准备一个便携版..."
    rf_install_portable_python "$arch"
    return 0
}

# 读取 pyvenv.cfg 里的 version 行，判断既有虚拟环境是否由窗口内的解释器创建。
# 用别的版本建的 venv 永远装不上钉死的轮子，复用它只会让每次启动都以同一种方式失败，
# 所以这种情况要把它挪开（不是删除）再重建。
rf_venv_version_supported() {
    config_path=$1
    [ -f "$config_path" ] || return 1
    raw=$(sed -n 's/^[[:space:]]*version[[:space:]]*=[[:space:]]*//p' "$config_path" | head -n 1)
    [ -n "$raw" ] || return 1
    major=$(printf '%s' "$raw" | cut -d. -f1)
    minor=$(printf '%s' "$raw" | cut -d. -f2)
    case "$major$minor" in
        *[!0-9]* | "") return 1 ;;
    esac
    if [ "$major" -lt "$RF_PYTHON_MIN_MAJOR" ] || [ "$major" -gt "$RF_PYTHON_MAX_MAJOR" ]; then
        return 1
    fi
    if [ "$major" -eq "$RF_PYTHON_MIN_MAJOR" ] && [ "$minor" -lt "$RF_PYTHON_MIN_MINOR" ]; then
        return 1
    fi
    if [ "$major" -eq "$RF_PYTHON_MAX_MAJOR" ] && [ "$minor" -gt "$RF_PYTHON_MAX_MINOR" ]; then
        return 1
    fi
    return 0
}

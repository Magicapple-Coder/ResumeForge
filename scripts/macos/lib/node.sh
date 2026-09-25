# ResumeForge macOS 启动链：Node.js / npm 的查找与自举。
#
# 为什么需要它：这个项目的前端开发服务器由 Node 跑，而 macOS **不自带 Node**。
# 用户装好之后不该还需要知道 npm 是什么，所以这里和 Windows 侧一样，缺了就自动
# 下载一份**便携版 Node** 到 runtime/tools/ 里——不写 /usr/local、不弹管理员密码、
# 不动用户已有的 nvm/Homebrew。
#
# 版本上界没有钉：Node 是向前兼容的，比要求的更新没有问题；下界 20.19.0 来自
# Vite 6 的 engines 要求（frontend/package.json 的 engines 字段与它一致）。

: "${RF_NODE_MIN_VERSION:=20.19.0}"
: "${RF_NODE_BOOTSTRAP_VERSION:=24.19.0}"
# 摘要是仓库里的常量，不来自镜像——镜像只能"慢或旧"，不能替换内容。
: "${RF_NODE_AARCH64_SHA256:=8294b7aa9b03997481c06babf1e8b270c859358f27da57a11509afe537ac381d}"
: "${RF_NODE_X64_SHA256:=d1b5e999db158c62fe8f7267a4476b035d8bd93b1a605bac24a3f0dd166e3316}"
: "${RF_NODE_BOOTSTRAP_APPROX_MB:=47}"
: "${RF_NODE_MIRROR_BASES:=https://mirrors.huaweicloud.com/nodejs https://cdn.npmmirror.com/binaries/node https://mirrors.cloud.tencent.com/nodejs-release}"

# 给定 node 可执行文件，打印版本号（去掉 v 前缀），失败返回非零。
rf_node_reported_version() {
    [ -n "$1" ] || return 1
    [ -x "$1" ] || return 1
    raw=$("$1" --version 2>/dev/null | head -n 1) || return 1
    raw=${raw#v}
    case "$raw" in
        '' | *[!0-9.]*) return 1 ;;
    esac
    printf '%s\n' "$raw"
}

# 一个候选运行时必须同时具备可用的 node 与 npm，且版本达标。
# 只看目录存在是不够的：Homebrew 的 node 与 npm 可能来自不同 tap（nvm 切到一半、
# 或 node 装了但 npm 的全局链接没建），那种情况下启动器会在"前端启动超时"上失败，
# 报错却指向后端——这里提前把它挡掉。
rf_node_runtime_candidate_ok() {
    node_path=$1
    npm_path=$2

    [ -x "$npm_path" ] || return 1
    version=$(rf_node_reported_version "$node_path") || return 1
    rf_version_ge "$version" "$RF_NODE_MIN_VERSION" || return 1

    npm_version=$("$npm_path" --version 2>/dev/null | head -n 1)
    case "$npm_version" in
        [0-9]*.[0-9]*.[0-9]*) return 0 ;;
        *) return 1 ;;
    esac
}

# 依次探测候选目录，找到第一个 node 与 npm 同目录且都合格的运行时。
# 成功时设置 RF_NODE_PATH、RF_NPM_PATH、RF_NODE_VERSION 并返回 0。
rf_find_system_node_runtime() {
    RF_NODE_PATH=""
    RF_NPM_PATH=""
    RF_NODE_VERSION=""

    candidate_dirs=""

    # PATH 上显式找到的 node 所在目录优先；npm 必须与它同目录。
    if command_exists node; then
        candidate_dirs="$candidate_dirs $(dirname "$(command -v node)")"
    fi

    # Finder 启动的进程不一定继承 shell 的 PATH，所以常见安装位置必须显式列出。
    candidate_dirs="$candidate_dirs /opt/homebrew/bin /usr/local/bin"
    if [ -n "${HOME:-}" ]; then
        for nvm_bin in "$HOME"/.nvm/versions/node/*/bin; do
            candidate_dirs="$candidate_dirs $nvm_bin"
        done
    fi
    # 本启动器上一次装好的便携版。
    for portable_bin in "$RF_TOOLS_DIR"/node-v*-darwin-*/bin; do
        candidate_dirs="$portable_bin $candidate_dirs"
    done

    for candidate_dir in $candidate_dirs; do
        [ -d "$candidate_dir" ] || continue
        if rf_node_runtime_candidate_ok "$candidate_dir/node" "$candidate_dir/npm"; then
            RF_NODE_PATH="$candidate_dir/node"
            RF_NPM_PATH="$candidate_dir/npm"
            RF_NODE_VERSION=$(rf_node_reported_version "$RF_NODE_PATH")
            return 0
        fi
    done
    return 1
}

rf_build_node_bootstrap_urls() {
    arch=$1
    archive="node-v${RF_NODE_BOOTSTRAP_VERSION}-darwin-${arch}.tar.gz"
    for base in $RF_NODE_MIRROR_BASES; do
        printf '%s/v%s/%s\n' "$base" "$RF_NODE_BOOTSTRAP_VERSION" "$archive"
    done
    printf 'https://nodejs.org/dist/v%s/%s\n' "$RF_NODE_BOOTSTRAP_VERSION" "$archive"
}

rf_node_bootstrap_sha256() {
    case "$1" in
        arm64) printf '%s\n' "$RF_NODE_AARCH64_SHA256" ;;
        x64) printf '%s\n' "$RF_NODE_X64_SHA256" ;;
        *) return 1 ;;
    esac
}

# 下载并解压便携版 Node。成功后 RF_NODE_PATH / RF_NPM_PATH 指向它。
rf_install_portable_node() {
    arch=$1
    expected_sha=$(rf_node_bootstrap_sha256 "$arch") || \
        die "没有为架构 ${arch} 准备便携版 Node.js。" \
            "请把这条报错发到项目的 GitHub Issues。"

    archive_base="node-v${RF_NODE_BOOTSTRAP_VERSION}-darwin-${arch}"
    target_dir="$RF_TOOLS_DIR/$archive_base"
    if rf_node_runtime_candidate_ok "$target_dir/bin/node" "$target_dir/bin/npm"; then
        RF_NODE_PATH="$target_dir/bin/node"
        RF_NPM_PATH="$target_dir/bin/npm"
        RF_NODE_VERSION=$(rf_node_reported_version "$RF_NODE_PATH")
        return 0
    fi

    mkdir -p "$RF_TOOLS_DIR"
    staging=$(mktemp -d "$RF_TOOLS_DIR/node-bootstrap-XXXXXX") || \
        die "无法在 $RF_TOOLS_DIR 下创建临时目录。" \
            "确认项目目录可写（没有被设为只读、也没有被安全软件锁定）。"

    archive_path="$staging/node.tar.gz"
    urls=$(rf_build_node_bootstrap_urls "$arch")

    # shellcheck disable=SC2086  # 需要按空白拆成多个候选 URL
    if ! download_verified "$archive_path" "$expected_sha" \
        "便携版 Node.js $RF_NODE_BOOTSTRAP_VERSION" "$RF_NODE_BOOTSTRAP_APPROX_MB" $urls; then
        rm -rf "$staging"
        die "所有下载源都没能拿到 Node.js 运行时。" \
            "可能原因：网络不通、公司代理，或者镜像站被拦。" \
            "怎么办（按顺序试）：" \
            "  1) 用浏览器打开 https://mirrors.huaweicloud.com/nodejs/ 确认能否访问；" \
            "  2) 需要代理时，先在终端里 export HTTPS_PROXY=http://127.0.0.1:端口 再重试；" \
            "  3) 也可以自己到 https://nodejs.org/ 装好 Node.js ${RF_NODE_MIN_VERSION} 或更新版本，" \
            "     装好后重新双击 start.command。"
    fi

    log_info "校验通过，正在解压便携版 Node.js..."
    if ! tar -xzf "$archive_path" -C "$staging"; then
        rm -rf "$staging"
        die "解压便携版 Node.js 失败（压缩包可能不完整）。" \
            "删掉 runtime/tools 里以 node-bootstrap- 开头的目录后重新双击 start.command。"
    fi

    if [ ! -d "$staging/$archive_base" ]; then
        rm -rf "$staging"
        die "下载到的 Node.js 压缩包里没有预期的目录 ${archive_base}。" \
            "请把这条报错发到项目的 GitHub Issues。"
    fi

    rm -rf "$target_dir"
    mv "$staging/$archive_base" "$target_dir"
    rm -rf "$staging"

    if ! rf_node_runtime_candidate_ok "$target_dir/bin/node" "$target_dir/bin/npm"; then
        die "便携版 Node.js 装好了，但 node/npm 无法使用。" \
            "在终端里执行下面两行看看完整报错，并把结果发到 GitHub Issues：" \
            "  $target_dir/bin/node --version" \
            "  $target_dir/bin/npm --version"
    fi

    xattr -dr com.apple.quarantine "$target_dir" 2>/dev/null || true

    RF_NODE_PATH="$target_dir/bin/node"
    RF_NPM_PATH="$target_dir/bin/npm"
    RF_NODE_VERSION=$(rf_node_reported_version "$RF_NODE_PATH")
    return 0
}

# 确保有一个可用的 Node/npm。成功后 RF_NODE_PATH、RF_NPM_PATH、RF_NODE_VERSION 可用。
rf_ensure_node_runtime() {
    if rf_find_system_node_runtime; then
        return 0
    fi

    arch=$(detect_macos_arch)
    log_info "没有找到可用的 Node.js/npm（需要 ${RF_NODE_MIN_VERSION} 或更新版本），正在自动准备一个便携版..."
    rf_install_portable_node "$arch"
    return 0
}

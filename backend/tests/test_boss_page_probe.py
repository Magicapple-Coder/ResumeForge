"""页面探针与选择器的契约测试。

**为什么这两个 bug 值得单独钉住**：它们都不是"解析错了"，而是"**判早了**"和"**看错了**"，
症状却是同一个——采集整个失效或整批失败，而错误信息指向完全无关的地方。

1. **就绪判定被站点的导航链接提前触发**。`SELECTOR_SEARCH_READY` 里那条
   `a[href*="/job_detail/"]` 会命中页头的「职位搜索」导航项（`href` 正好是
   `https://www.zhipin.com/job_detail/`，没有岗位 id、也不以 `.html` 结尾）。它比岗位卡片
   **先**渲染（实测 0.66s vs 卡片 2s+），于是"页面已就绪"在 0.9s 就被判真、网络订阅窗口
   随之关闭——joblist 接口此时还没发出，**永远收不到**。整条"网络优先"路径静默失效，
   退回 DOM 又抓到那条导航链接本身，采到的"岗位"标题是「职位搜索」。

2. **登录/验证码判定不看可见性**。BOSS 把登录弹窗的整套模板（`.sign-form` 等 6 个）写在
   页面标记里、默认隐藏，岗位详情页尤其明显。用 `!!document.querySelector(LOGIN)` 判定的话，
   **每打开一个详情页都会被判成"需要登录"**：采集在抓完列表、开始补详情时当场失败，
   而用户其实是登录着的。

两条都无法用"喂一份 payload"测出来——它们发生在**页面里**。所以这里断言的是**生成的脚本
本身**：必须用可见性判定、必须把导航链接排除在外。这类断言在仓库里已有先例
（例如"前端生产代码里不得写死站点名"）。
"""
from app.services.sites.boss_page import (
    SELECTOR_JOB_LINK,
    SELECTOR_SEARCH_READY,
    _page_probe_script,
    _readiness_script,
)
from app.services.sites.boss_apply import (
    _entry_script,
    _greeting_state_script,
    _submit_state_script,
)


def _probe_scripts() -> dict[str, str]:
    """所有会判定"是否被登录墙/验证码拦住"的页面脚本。"""
    return {
        "readiness": _readiness_script(SELECTOR_SEARCH_READY),
        "page-state": _page_probe_script(),
        "apply-entry": _entry_script("rf:x", click=False),
        "greeting-state": _greeting_state_script(),
        "submit-state": _submit_state_script("你好"),
    }


def test_every_blocker_check_requires_visibility():
    """拦截判定必须"看得见才算数"。

    隐藏的登录弹窗模板不是拦截；把它当成拦截会让每一次采集/投递都在中途失败，而用户
    完全不知道自己哪里做错了。
    """
    for name, script in _probe_scripts().items():
        assert "shown(CAPTCHA)" in script or "captcha" not in script, name
        assert "shown(LOGIN)" in script or "login_required" not in script, name
        # 旧的写法一个都不许留：它正是误报的来源。
        assert "!!document.querySelector(LOGIN)" not in script, name
        assert "!!document.querySelector(CAPTCHA)" not in script, name


def test_the_visibility_helper_looks_at_rendered_boxes():
    """`shown()` 用 `getClientRects()`——与采集脚本里判断卡片可见性的是同一个判据。"""
    script = _readiness_script(SELECTOR_SEARCH_READY)
    assert "const shown = (sel)" in script
    assert "getClientRects().length" in script


def test_the_empty_state_also_requires_visibility():
    """空态同理：站点若把空态容器当模板藏在页面里，只看存在与否会让**每一次**搜索都被
    判成"确实没搜到"，于是安静地返回 0 条——正是这套测试开头点名的危险形态。"""
    script = _readiness_script(SELECTOR_SEARCH_READY)
    assert "shown(EMPTY)" in script
    assert "!!document.querySelector(EMPTY)" not in script


def test_the_job_link_selector_requires_a_real_job_page():
    """岗位链接必须以 `.html` 结尾。

    这是唯一能把「职位搜索」导航项（`/job_detail/`，无 id）与真实岗位
    （`/job_detail/<id>.html`）区分开的地方；放宽回去就等于把上面第 1 个 bug 放回来。
    """
    assert 'a[href*="/job_detail/"]' in SELECTOR_JOB_LINK, "兜底仍要认链接形状"
    assert '[href$=".html"]' in SELECTOR_JOB_LINK, "必须排除没有 .html 的导航链接"
    # 就绪判定复用同一个常量，所以这两条不可能各自漂移。
    assert SELECTOR_JOB_LINK in SELECTOR_SEARCH_READY

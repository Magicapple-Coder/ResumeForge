<div align="center">

<img src="docs/images/icon.png" width="88" alt="简历通 ResumeForge 图标" />

# 简历通 ResumeForge

[![CI](https://github.com/magicapple123/ResumeForge/actions/workflows/ci.yml/badge.svg)](https://github.com/magicapple123/ResumeForge/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/magicapple123/ResumeForge?label=release&color=2f81f7)](https://github.com/magicapple123/ResumeForge/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/magicapple123/ResumeForge?style=flat&logo=github)](https://github.com/magicapple123/ResumeForge/stargazers)
[![Python](https://img.shields.io/badge/Python-3.10--3.13-3776AB?logo=python&logoColor=white)](docs/user-guide.md)
[![Node.js](https://img.shields.io/badge/Node.js-20.19%2B-339933?logo=nodedotjs&logoColor=white)](docs/user-guide.md)
[![Tests](https://img.shields.io/badge/tests-2%2C700%2B%20passing-success)](.github/workflows/ci.yml)

**本地优先的 AI 简历工作台：不注册、不登录，数据只存在你自己电脑上的一个文件里。**

<h3>
<a href="https://magicapple123.github.io/ResumeForge-official/demo.html">▶ 在线体验（免安装）</a>
　·　
<a href="https://magicapple123.github.io/ResumeForge-official/docs.html">📖 使用文档</a>
　·　
<a href="https://magicapple123.github.io/ResumeForge-official/">🏠 官网</a>
</h3>

当前版本：`0.11.0` · [Release 页面](https://github.com/magicapple123/ResumeForge/releases) · [完整使用指南](docs/user-guide.md) · [架构设计](docs/architecture.md)

</div>

> 在线体验是一个**只读演示版**：界面是真的、数据是虚构的、AI 输出是预录回放。想真的生成、真的导出、真的投递，按下面的[快速开始](#-快速开始)在本机跑起来——第一次双击 `start.cmd` 会自动装好环境。

---

## 简历通能干什么

一条完整的链路，从看岗位到拿到 offer，每一步都有对应功能，每一步的产出都能回头修正上一步：

<p align="center">
  <img src="docs/images/what-it-does.png" alt="简历通能干什么：找到并读懂岗位 → 判断匹不匹配 → 写出站得住的简历 → 导出与交付 → 投递与跟进 → 面试与复盘" width="1000">
</p>

它解决的是一类很具体的问题：**求职期间的资料是散的**。JD 躺在浏览器收藏夹里，简历文件有七八个版本叫 `简历-最终版2.docx`，投递进度记在备忘录，面试问到的问题面试完就忘了，改了三遍简历也不记得哪一版投给了哪家公司。

更要紧的是另一个问题：**AI 会替你把简历写得很漂亮，也会替你编。** 简历工具最危险的行为不是排版难看，而是把你没做过的事写进去——面试官追问两句就露馅。所以 ResumeForge 把「事实」从「表述」里拆出来单独管：生成结果里的学校 / 公司 / 项目名会与资料库逐条比对，不一致时给**防虚构警告**；正文还留着【待补】标记时导出会被拦下并指出具体位置。

## 为什么值得用

市面上的简历工具大多要你先交出账号和数据，再决定要不要收你钱。简历通反过来：

| | 简历通 ResumeForge | 常见的在线简历工具 |
| --- | --- | --- |
| **要不要注册登录** | 不要。装完即用，没有账号体系 | 先注册、先登录、先绑定手机 |
| **简历和资料存在哪** | 你自己电脑上的一个 SQLite 文件，可随时拷走 | 对方的服务器，导出要走会员 |
| **要不要钱** | 永久开源免费（MIT），**没有会员、没有付费墙、没有导出次数限制** | 免费版限制模板 / 导出 / AI 次数 |
| **AI 怎么用** | 按**每个岗位的 JD** 单独筛选事实、单独生成一版 | 通用模板 + 套话，一份改多处用 |
| **会不会替你编** | 有「事实台账」挡着：只有你确认过的事实才参与生成 | 无 |
| **投递要不要管** | 内置自动投递台 + 求职进度 + 提醒 + 内推 + 统计 | 基本不管，投完靠自己记 |
| **断网能不能用** | 解析、检查、预览、全部导出都离线可用；不配模型也能用大部分功能 | 必须联网 |
| **能不能自己改** | 源码开放，可自建、可改、可二次开发 | 闭源 |

还有几件同样重要、但不太好放进表格的事：

- **不访问招聘网站，除非你亲手点了那个按钮。** 默认全部在本机完成；「投递台」是唯一会主动访问外部站点的链路，必须由你显式配置 + 显式点击开始，**不做无人值守运行**。
- **不保存招聘网站密码、Cookie、令牌或验证码。** 扫码登录在你自己打开的浏览器窗口里完成，应用不读取也不落盘登录态。
- **匹配度不给百分比评分。** 分数会让人误以为它能决定投递结果，而它不能。结论只有五类：`已匹配 / 表达缺口 / 证据不足 / 真实缺口 / 待确认`，每一类都能直接指导你改简历。
- **还在维护。** 有 CI、有 2,700+ 个用例、有数据库迁移链与升级方案——见[更新而不丢失数据](#-更新而不丢失数据)。

## 界面速览

截图全部来自**真实运行**的应用，数据是内置的**虚构示例**（「张示例 / 示例科技有限公司 / example.com」），不含任何真实用户资料。

**16 个入口按真实使用顺序分组**，顺序本身就是一次导览：

<p align="center">
  <img src="docs/images/anim-nav.webp" alt="用左侧导航依次切换岗位广场、简历中心、投递台、求职进度、求职统计、模拟面试、求职助手、事实台账、知识库与工作台" width="820">
</p>

**首页**：快捷入口按「找岗位 / 做简历 / 投递跟进 / 面试准备 / 我的数据 / 系统」组织，近期提醒卡片按紧急度分色：

<p align="center">
  <img src="docs/images/home.png" alt="简历通首页：快捷入口、近期提醒与待办" width="900">
</p>

**AI 是按岗位生成的，不是套模板**：挑一个岗位，定档位、篇幅与模板。生成时会从你的资料与经历总结里按 JD 筛选排序，**原始资料不会被修改**：

<p align="center">
  <img src="docs/images/crop-ai-resume-options.png" alt="为「市场运营专员」生成简历的弹窗：当前模型、岗位适配与内容美化档位（轻度 / 均衡 / 深度）、篇幅与版式、字号与补充要求" width="900">
</p>

生成完它会自动做两件事。一是**版式诊断**：下面这张图里正文占了 105%、超出所选页数，它直接给出收紧顺序与一键「自动一页」。二是**防虚构校验**：把结果与你的资料库逐条比对，「400 人、7.2%、6.1%、1.1 个」这些资料里没有的量化结果被**点名要求人工核对**——模型编出来的东西不会悄悄留在简历里：

<p align="center">
  <img src="docs/images/crop-ai-resume-result.png" alt="AI 生成结果弹窗：版式诊断提示占用 105% 并给出「自动一页」，防虚构校验指出实习/工作经历出现资料未提供的量化结果「400 人、7.2%、6.1%、1.1 个」，下方为 A4 预览与导出入口" width="900">
</p>

**AI 定制简历的 A4 成品**（服务端用系统中文字体渲染，PDF 可直接下载，也可以走浏览器打印）：

<p align="center">
  <img src="docs/images/resume-a4.png" alt="A4 简历成品：单页版式、区块标题带强调色、技能标签带框" width="600">
</p>

**一个框搜遍全站**：岗位、简历、内推、提醒、面经、事实台账、资料箱与助手技能一起搜，不用先想「这东西在哪个模块」：

<p align="center">
  <img src="docs/images/anim-search.webp" alt="在首页全局搜索框输入「市场运营」，同时列出匹配的岗位、简历、内推、提醒、面经、资料箱与助手技能" width="880">
</p>

**岗位广场**：手动录入、粘贴原文、贴截图、传 pdf/docx 都能识别成可编辑草稿；技能标签保存时自动提取：

<p align="center">
  <img src="docs/images/jobs.png" alt="岗位广场：技能标签、来源标注、收藏与筛选" width="900">
</p>

**岗位详情的匹配度分析**：逐条对照 JD 给出五类结论，每条都附 JD 原文与你自己的证据；找不到依据时如实写「资料中未提供」，**全程不出现百分比评分**：

<p align="center">
  <img src="docs/images/job-detail.png" alt="岗位详情抽屉：职位描述、任职要求、技能标签，与底部动作条「岗位需求解读 / 匹配度分析 / 加入投递台」" width="900">
</p>

<p align="center">
  <img src="docs/images/crop-job-match.png" alt="岗位匹配度分析结果：准入结论「需确认」、硬性门槛「硬性条件待确认」，以及逐条的「已匹配 / 证据不足」结论、招聘原文与依据" width="900">
</p>

**助手会先查你的库再回答**——台账里的主张、面经、面试深挖记录都查得到，而且**未经你同意不改任何数据**（下面这轮回答里它明确说「你说一声我再动，未经你同意我不改简历」）：

<p align="center">
  <img src="docs/images/anim-assistant.webp" alt="在求职助手里问「我这份简历里，哪条说法最容易被面试官追问？」，助手逐字回答并引用事实台账、面经与面试深挖记录" width="880">
</p>

<table>
<tr>
<td width="50%"><img src="docs/images/resumes.png" alt="简历中心"><br><sub><b>简历中心</b>：多份简历、来源区分、收藏、备注、版式与篇幅控制</sub></td>
<td width="50%"><img src="docs/images/apply.png" alt="自动投递台"><br><sub><b>自动投递台</b>：采集 → 匹配 → 显式确认 → 自动投递，四步流程写在页面顶部</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/tracker.png" alt="求职进度"><br><sub><b>求职进度</b>：一家公司一个岗位一条记录，粘邮件 / 截图识别进展，先预览再写入</sub></td>
<td width="50%"><img src="docs/images/analytics.png" alt="求职统计"><br><sub><b>求职统计</b>：转化与卡点、时间与节奏、渠道与去向、简历与健康度</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/claims.png" alt="事实台账"><br><sub><b>事实台账</b>：事实、表述、承担程度与个人边界分开管</sub></td>
<td width="50%"><img src="docs/images/interview.png" alt="模拟面试"><br><sub><b>模拟面试</b>：逐轮追问，结束后给维度评分与改进建议</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/assistant.png" alt="求职助手"><br><sub><b>求职助手</b>：能查库、能引用资料、只在明确要求时写数据</sub></td>
<td width="50%"><img src="docs/images/settings.png" alt="设置"><br><sub><b>设置</b>：16 个模型预设、数据集与软件更新</sub></td>
</tr>
</table>

**导出与脱敏**：PDF / Word / Markdown / 纯文本 / JSON / HTML 任选，可加水印；一键脱敏遮住姓名、电话、邮箱、公司与学校后再导出：

<p align="center">
  <img src="docs/images/crop-resume-export.png" alt="简历预览页脚：质量检测、导出选项、一键脱敏、离线分享、下载 PDF、更多格式" width="900">
</p>

<p align="center">
  <img src="docs/images/anim-export.webp" alt="打开简历预览，依次点开更多格式、一键脱敏与离线分享" width="880">
</p>

**投递台操作动图**——勾选岗位 → 点「开始投递」→ 确认本批次范围。**在你点下去之前，它不会打开任何招聘网站**：

<p align="center">
  <img src="docs/images/anim-apply.webp" alt="在投递台勾选岗位、点开始投递并看到批次确认，再切到自动采集页" width="880">
</p>

<details>
<summary><b>更多界面</b>（点击展开：简历预览、资料箱、知识库、工作台、回收站）</summary>

<br>

<table>
<tr>
<td width="50%"><img src="docs/images/resume-preview.png" alt="简历预览与导出"><br><sub><b>简历预览</b>：A4 版式可缩放拖动，版面诊断给单页占用率与建议顺序</sub></td>
<td width="50%"><img src="docs/images/materials.png" alt="资料箱"><br><sub><b>资料箱</b>：证书、作品、链接与笔记，可带附件，点卡片看详情</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/knowledge.png" alt="知识库"><br><sub><b>知识库</b>：面经总结、简历技巧与求职策略，正文支持 Markdown 预览</sub></td>
<td width="50%"><img src="docs/images/skills.png" alt="工作台"><br><sub><b>工作台</b>：助手技能与简历模板，可自制、可导入 HTML</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/trash.png" alt="回收站"><br><sub><b>回收站</b>：十类内容删除后先进回收站，可多选批量恢复或彻底删除</sub></td>
<td width="50%"><img src="docs/images/guide.png" alt="内置使用指南"><br><sub><b>使用指南</b>：首次启动自动弹出，之后随时可查</sub></td>
</tr>
</table>

**细节裁切**：

<table>
<tr>
<td width="50%"><img src="docs/images/crop-jobs-row.png" alt="岗位表格一行"><br><sub>行内操作收进「更多操作」，一屏能多看几行</sub></td>
<td width="50%"><img src="docs/images/crop-home-search.png" alt="全局搜索结果"><br><sub>搜索一次命中八个模块</sub></td>
</tr>
<tr>
<td width="50%"><img src="docs/images/crop-claims-row.png" alt="事实台账一行"><br><sub>台账一条：原始事实、简历表述、承担程度与个人边界</sub></td>
<td width="50%"><img src="docs/images/crop-tracker-parse.png" alt="从通知导入进展"><br><sub>粘邮件 / 截图识别进展，先预览「会发生什么」再确认写入</sub></td>
</tr>
</table>

</details>

## ✨ 功能特性

<details>
<summary><b>全部功能一览（43 项，点击展开）</b></summary>

<br>

| 模块 | 说明 |
| --- | --- |
| 📋 岗位管理 | 粘贴招聘信息自动解析成草稿；**一次粘贴多份会拆分并逐条确认**；技能标签与来源自动标注 |
| 🗂 备选岗位 | 还没核对的招聘信息先存这里，之后一键导入正式岗位（助手也能代导） |
| 📥 拖拽导入 | 岗位识别、附件、照片、模板 HTML、数据集备份等都能从资源管理器直接拖进来 |
| 🎤 模拟面试 | 设定岗位、难度与面试官风格后逐轮作答，会点评追问；结束给维度评分与改进建议 |
| 🎯 个性化题库 | 按岗位生成**基础 / 项目深挖 / 反问 HR** 三类题，可单题出参考答案；真实面试题可反推改简历 |
| 🧰 工作台 | 「助手技能」与「简历模板」两页，可自制、可从内置复制改、可导入 HTML 并实时预览 |
| 👤 个人资料库 | 基本信息、四类经历、技能与获奖；每条经历可附 Markdown / TXT 总结 |
| 🖼 简历照片 | 最多存 8 张，点缩略图切换用哪张；**留在本机，不发送给模型** |
| 🧾 事实台账 | 每条说法记下事实、表述、承担程度与边界；**只有「已确认」的参与生成**，未确认的显式避开 |
| 🔎 面试深挖 | 按台账逐条压力测试，**标准在你看到问题之前就定下**；用「已验证 / 部分验证 / 未验证 / 存在矛盾」代替分数 |
| 📦 资料箱 | 证书、作品、链接与笔记集中管理，可带附件，点卡片看详情；助手可读取引用 |
| 🤖 AI 定制简历 | 按 JD 筛选事实流式生成；可选美化强度、篇幅（1–3 页 A4）、字号与模板（内置 6 种） |
| ✍️ 自行编写简历 | 从个人资料预填后自由修改，编辑时旁边保留岗位职责与要求供对照 |
| ✍️ 简历写作增强 | **STAR 量化改写**、**话术生成器**、**多风格润色**、**中英互译**、**版本差异对比**（本地计算） |
| 🛡 质量与合规检查 | 查重 / 敏感词 / 夸大风险 / 深挖风险 / 合规 / ATS 本地检测，与事实台账联动 |
| 📚 简历历史 | 生成与手写的简历都自动留存，可收藏、按来源筛选、加备注、重新导出 |
| 🔗 岗位关联 | 一个岗位可关联多份简历，岗位与简历之间双向可跳转 |
| ⭐ 收藏夹 | 分页集中查看收藏的岗位与简历，可跳详情或取消收藏 |
| 💡 岗位需求解读 | 依据招聘原文生成结构化需求总结、原文证据与通用准备建议 |
| 🎯 岗位匹配度分析 | 逐条对照 JD 给五类结论与投递建议，附原文与证据；**不显示百分比评分** |
| 📊 匹配度参考分 | 0–100 参考分与 5 个分项，**仅作展示辅助、不参与投递准入**，带免责说明 |
| 🎯 求职进度 | 一家公司一条记录走完「已投递 → 筛选中 → 测评 → 面试 → Offer」；粘邮件 / 截图识别进展，先预览再写入 |
| 🗓 日历提醒 | 投递、面试、内推等日程可设提醒，按**紧急度分色**（逾期 / 24 小时 / 3 天），支持列表与月历 |
| 🤝 内推管理 | 记录内推人、内推码与备注图片，按状态跟进并统计**内推转化率** |
| 📈 求职数据看板 | 四个主题：转化与卡点、时间与节奏、渠道与去向、简历与健康度；趋势可选近 1 / 3 / 6 月 |
| 🧠 面经知识库 | 沉淀真实面试经验（公司 / 岗位 / 题目 / 复盘），可检索、点卡片看全文 |
| 📖 知识库 | 面经总结、简历技巧、求职策略等成文内容，带分类标签与 Markdown 预览；助手可检索增改 |
| 🚀 自动投递台 | 按关键词 / 城市自动采集（站点筛选条件整条搬进来，后台跑）；确认过的岗位排队后驱动本机浏览器投递，**只接纳来源在招聘网站内的岗位** |
| 💬 AI 求职助手 | 流式问答，可关联岗位 / 简历 / 资料与联网搜索；能查提醒、内推、面经、统计等，**只在明确要求时写数据** |
| 🧩 助手技能 | 新建、导入、编辑技能（提示词 + 知识文件），启用后约束助手作答风格 |
| 🗒 会话管理 | 会话可重命名 / 置顶 / 收藏 / 分组 / 归档，可导出 Markdown 或存进资料箱 |
| 🌐 通用简历 | 生成或手写**不针对任何岗位**的跨行业简历，各方向经历都保留，可多份 |
| 🖼 截图与文档识别 | 岗位与资料识别支持截图与 pdf / docx（Ctrl+V 贴图，最多 4 个、合计 ≤ 5 MB），文字在本机提取 |
| 📄 多格式导出 | PDF **可直接下载**（服务端渲染）；Word / Markdown / txt / JSON / HTML 无损导出；支持水印与**一键脱敏** |
| 📦 离线分享包 | 打包成脱敏 HTML / PDF + 只读快照 + 评论回传文件，可选「只读 / 可评论」 |
| 🏪 本地模板市场 | 互联网大厂 / 国企事业单位 / 外企 / 应届校园四套预设，各给「样式 + 版式 + 字号」建议组合 |
| 🏠 首页 | 快捷入口按使用顺序组织成 7 个去处；近期提醒卡片内嵌紧凑月历 |
| 🖱 界面细节 | 行操作收进「更多操作」；列表与卡片**点一下就看详情**（Enter 同样可开）；日期改为日历点选 |
| 🔍 全局搜索 | 一个框同时搜岗位、简历、内推、提醒、面经、台账、资料箱与助手技能 |
| 🛡 防虚构校验 | 生成结果里的学校 / 公司 / 项目名自动与资料库比对，不一致时给出警告 |
| 🔄 检查与更新 | 设置页可检查新版本、新建 / 导出 / 导入数据集；`update.cmd` 一键更新，`uninstall.cmd` 卸载 |
| ♻️ 回收站 | 十类内容删除后先进回收站，可批量恢复或彻底删除；只有二次确认才真正销毁 |
| 🔑 你的 Key 你做主 | 内置 16 个服务预设（DeepSeek / Claude / 豆包 / OpenAI / Ollama …），可取可用模型、调高级参数，并可切换接口协议 |

</details>

## 🚀 快速开始

```powershell
git clone https://github.com/magicapple123/ResumeForge.git
cd ResumeForge
```

**环境要求**：Windows 10/11、Python 3.10 – 3.13、Node.js ≥ 20.19.0。后两项**没装也行**——一键启动器会用 `winget` 或官方便携包自动准备好。

> Python 3.14 暂不支持：锁定的后端依赖还没有对应的 cp314 轮子，装的时候会退化成源码编译并失败。

### 一键启动（推荐）

在项目根目录**双击 `start.cmd`**。首次运行会自动创建虚拟环境、装齐前后端依赖、启动两个服务并打开浏览器：

```text
http://127.0.0.1:5173
```

之后每次双击 `start.cmd` 即可，不需要分别启动前后端。要完全关闭服务，双击 `stop.cmd`，或点侧栏底部的**退出**。

> 首次启动最常见的问题是依赖装不上，**基本都是网络原因**（默认走官方 PyPI / npm，国内经常超时）。启动器会在失败时用中文写明原因和下一步，照它说的做即可；最快的一条是换国内镜像重装后端依赖：
>
> ```powershell
> backend\.venv\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple -r backend\requirements.txt
> ```
>
> 前端同理，在 `frontend` 目录执行 `npm install --registry=https://registry.npmmirror.com`。启动失败时窗口**不会**自动关，可以从容读完提示再截图反馈。

想把应用从这台电脑上清掉，双击 `uninstall.cmd`：它删除启动器生成的东西（`.venv`、`node_modules`、`dist`、`runtime/` 与各类缓存），**保留** `backend\data` 与 `backend\.env`，并且**不会删源码和文档**。

### 配置大模型（可选）

打开左侧 **设置 → 编辑设置**，选一个内置预设（自动填好接口地址与模型名）或「自定义模型（OpenAI 兼容）」，填 API Key 后点「测试连接」即可。内置 16 个预设，覆盖 DeepSeek、Claude（Anthropic 原生协议）、豆包、Kimi、通义、智谱、MiniMax、硅基流动、OpenRouter、OpenAI、Gemini、Grok、Groq、Mistral、Ollama、LM Studio。

> **不配模型也能用**：岗位解析、资料解析、匹配度五类结论、写作增强里的版本对比、质量与合规检查、全部导出格式都是**本地规则**，离线可用。只有需要「生成」的动作（AI 定制简历、岗位解读、模拟面试、求职助手、面试深挖）才需要模型；用 Ollama / LM Studio 这类本地模型时，连生成也不出本机。

### 手动启动（开发、排错或 macOS / Linux）

<details>
<summary>展开：后端 / 前端的分步命令与测试命令</summary>

<br>

```powershell
cd backend

# 创建虚拟环境并安装运行依赖
py -3 -m venv .venv
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe -m pip install -r requirements.txt

# 启动服务（默认 http://127.0.0.1:8000，接口文档见 /docs）
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

macOS / Linux 用 `.venv/bin/python` 替换上面的 Windows 路径；Git Bash 用 `export PYTHONUTF8=1`。

```powershell
cd frontend
npm ci
npm run dev        # http://localhost:5173，已配置 /api 代理到 8000 端口
```

运行测试：

```powershell
cd backend
.venv\Scripts\python.exe -m ruff check .
.venv\Scripts\python.exe -m pytest --cov=app --cov-config=../pyproject.toml

cd ../frontend
npm test && npm run lint && npm run typecheck && npm run build
```

当前规模：后端 **162 个测试文件 / 2,157 个用例**（覆盖率门槛 80%），前端 **91 个测试文件 / 580+ 用例**。GitHub Actions 在 Linux 与 Windows 上重复执行关键检查。

</details>

更完整的字段说明、隐私边界、升级与回滚、AI 故障排查，见[官网使用文档](https://magicapple123.github.io/ResumeForge-official/docs.html)。

## 🏗 架构与数据边界

前后端分离，前端统一通过同源 `/api` 访问后端（开发由 Vite 代理，生产需要由 Web 服务器托管 `frontend/dist`，把 `/api` 反向代理到 FastAPI，并把非静态文件的前端路由回退到 `index.html`）：

<p align="center">
  <img src="docs/images/architecture.png" alt="简历通架构图：React 前端 → 同源 /api → FastAPI 后端 → 本地 SQLite / 你配置的模型服务商 / 本机浏览器" width="1000">
</p>

几条贯穿全项目的设计取舍，读代码前先知道可以少走弯路：

- **一个逻辑只有一份实现**：投递准入只有 `models/apply.py::admission_of`，行操作菜单只有 `components/common/RowActions`，卡片详情只有 `RecordDetail`，助手的能力地图由 `services/feature_catalog.py` 运行时渲染。
- **并发守卫下沉到 SQL**：批次状态用条件 `UPDATE ... WHERE status = ?` 原子推进，不用「先读后判再写」。
- **外部输入一律不可信**：岗位描述、粘贴文本与上传文件都按不可信输入处理，不做系统指令执行。
- **不用 `create_all` 掩盖迁移问题**：数据库由 Alembic revision 管理，新增表 / 列必须写迁移与降级脚本。

完整设计（含决策记录、扩展点与数据模型）见 [docs/architecture.md](docs/architecture.md)，另有[项目导航图](docs/PROJECT_MAP.md)用于从功能倒查代码位置。

## 🔐 数据、隐私与边界

这个工具会碰到你的身份证号、手机号、公司名和简历原文，所以边界写在最前面：

- **默认全部留在本机。** 业务数据存在 `backend/data/resume_forge.db` 这**一个** SQLite 文件里（附件、照片、经历参考文件也在库内），不经过任何第三方服务；导出、渲染、PDF 生成都在本机完成。
- **只有你主动配置并触发的动作才会发出请求。** 发送对象是「你自己填地址和密钥」的模型服务商，内容仅限完成该次生成所需的最小资料；**照片不会发送给模型**。
- **不保存招聘网站密码、Cookie、令牌或验证码。** 自动投递走 CDP 连接你自己登录的浏览器（独立用户目录），扫码登录由你在浏览器窗口里完成。
- **不硬编码密钥。** 仓库、`.env.example` 与代码里没有任何真实密钥；`.env`、数据库、照片、简历与导出文件都被 `.gitignore` 忽略。Windows 上 API Key 用系统 DPAPI 加密后落库（密文绑定当前用户与机器）。
- **分享给别人时可一键脱敏。** 离线分享包只包含脱敏 HTML/PDF + 只读快照，不含真实敏感信息。
- **默认只监听回环地址。** 这是一个**单用户**本地工具，不要把它暴露到局域网或公网——它没有账号体系，暴露即等于把数据库交给别人。

发现疑似安全问题时请遵循 [SECURITY.md](SECURITY.md)，不要在公开 Issue 中披露可利用细节。

## 🔄 更新而不丢失数据

岗位、资料、简历、助手历史与模型配置默认保存在 `backend/data/resume_forge.db`，可选的服务端环境变量在 `backend/.env`，两者都被 Git 忽略，`git pull` 不会覆盖。

- **最省事的备份**：**设置 → 数据集 → 导出当前数据集**。照片、经历参考文件与助手附件都在这个库里，所以导出的 zip 就是完整的一份；换电脑时在新装的应用里「导入备份为新数据集」还原即可（备份不含 API Key，切换后需重填）。
- **一键更新（Windows）**：双击 `update.cmd`。它只替换程序文件，`data/`、`.env`、`runtime/` 一律不动；`-DryRun` 只预览，`-SkipDependencies` 只拉代码不装依赖。
- **更新不会动数据库**：Alembic 迁移在下次启动时自动执行，迁移前会在 `backend/data/backups/` 写一份备份。应用内**设置 → 软件更新**可直接检查新版本。

不要使用 `git clean -fdx`，也不要删除整个项目目录后直接覆盖。完整的升级、压缩包更新与回滚步骤见 [docs/upgrading.md](docs/upgrading.md)。

## ❓ FAQ

**必须联网才能用吗？**
不需要。除「投递台」的采集 / 投递链路与你主动触发的 AI 生成外，其余功能全部离线可用；用 Ollama / LM Studio 这类本地模型时，连 AI 生成也不出本机。

**支持哪些岗位？只有 IT 岗吗？**
面向所有岗位。示例数据刻意用的是市场运营，技能词表覆盖跨行业专业能力、办公与业务工具、证书资质等分类，模板市场也包含国企、外企与应届校园场景。

**AI 会不会把我的简历写飞？**
三道闸：事实台账里只有「已确认」的条目会作为事实参与生成；未确认的说法会被显式避开；生成结果里的学校 / 公司 / 项目名会与资料库比对，不一致时给出警告。正文还留着【待补】标记时导出会被直接拦下并指出位置。

**匹配度为什么不给分数？**
因为分数会让人误以为它能决定投递结果。五类结论说明的是「为什么」，可以直接指导改简历；0–100 的「匹配度参考分」只是展示辅助，**不参与投递准入**，并且带免责说明。

**多个岗位、多份简历会不会乱？**
一个岗位可以关联多份简历，一份简历也能看到它的目标岗位；简历中心可按来源（AI 生成 / 用户编写）与「有无岗位」筛选，收藏夹集中放重点，回收站兜住误删。

**为什么只能本机用？**
因为它没有账号体系与权限模型，业务数据（含身份证号、手机号这类个人信息）也没有加密存储。要多人共用需要先补上认证、TLS 与审计，这不是当前版本的目标。

## 💬 交流与反馈

- **QQ 群 `922830167`** —— 交流使用体验、提需求、报问题，欢迎来聊：

<p align="center">
  <img src="docs/images/qq-group.png" alt="简历通 QQ 群 922830167 二维码" width="300">
</p>

- **Bug 与需求**：用 [Issue 模板](.github/ISSUE_TEMPLATE) 提交，附上版本号、系统与复现步骤。
- **安全问题**：请走私密渠道（见 [SECURITY.md](SECURITY.md)），不要在公开 Issue 里披露可利用细节。

## 📖 文档

**普通用户**直接看官网的[使用文档界面](https://magicapple123.github.io/ResumeForge-official/docs.html)（排版友好、可搜索）；**开发者**看仓库里的源码文档：

| 文档 | 内容 |
| ---- | ---- |
| [使用指南](docs/user-guide.md) | 每个功能的字段说明、操作步骤与隐私边界（最完整的一份） |
| [项目导航图](docs/PROJECT_MAP.md) | 从功能倒查代码位置的地图，想改某功能先看这份 |
| [面试讲解指南](docs/INTERVIEW_GUIDE.md) | 怎么把项目讲清楚、讲出深度（亮点与高频追问） |
| [架构设计](docs/architecture.md) | 分层、数据模型、决策记录、扩展点 |
| [升级与回滚](docs/upgrading.md) | 版本升级、压缩包更新、数据备份与回滚 |
| [AI 故障排查](docs/ai-troubleshooting.md) | 模型连接、超时、输出异常与常见报错 |
| [提示词调优](docs/prompt-tuning.md) | 各生成链路用的提示词与调整方法 |
| [变更记录](CHANGELOG.md) | 每个版本改了什么 |
| [贡献指南](CONTRIBUTING.md) | 开发环境、提交规范、测试要求 |

## 🤝 参与贡献

欢迎 Issue 与 Pull Request。开始之前请读 [CONTRIBUTING.md](CONTRIBUTING.md) 与 [AGENTS.md](AGENTS.md)（后者是仓库的长期维护规则，包含「一处逻辑只留一份实现」「新增迁移要同步更新测试」这类会直接影响你 PR 能否通过的约定）。

- 修 bug 请先补一个能复现的测试，再改实现；
- 用户可见的行为变化请同步更新 README、`docs/user-guide.md`、应用内使用指南与 `CHANGELOG.md`；
- 新增数据表或列必须写 Alembic 迁移与降级脚本，并补「表集合前后不变」的断言；
- 提交信息遵循 Conventional Commits（`feat:` / `fix:` / `docs:` …）。

这个项目采用 [Contributor Covenant](CODE_OF_CONDUCT.md) 行为准则。

## 🗺 路线图

已完成的主线：岗位与资料 → 简历生成 / 编写 → 多格式导出 → 投递与进度 → 面试准备。近期方向：

- [ ] 更多招聘网站适配（站点适配器是可插拔的：加一个站点只需新增一个类并注册一行）
- [ ] 简历与岗位的批量对照视图（一次看多份岗位的匹配结论）
- [ ] 导出 Word 模板的自定义边界检查（当前只做格式校验）
- [ ] 更细的「投递 → 面试」转化分析（依赖新的状态历史表）

想影响优先级的话，在 Issue 里说清你的使用场景比「希望支持 X」更有用。

## 📄 许可证

[MIT](LICENSE) © 2026 magicapple123

## ⭐ Star 历史

如果这个项目帮你少踩了一个坑，给个 Star 会让我知道它值得继续维护。

[![Star History Chart](https://api.star-history.com/svg?repos=magicapple123/ResumeForge&type=Date)](https://star-history.com/#magicapple123/ResumeForge&Date)

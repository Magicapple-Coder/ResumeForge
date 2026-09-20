"""BOSS 直聘的文本还原：把被"反爬混淆"过的页面文本还原成正常中文。

BOSS 会在页面文本上做两类混淆，两者都会直接污染采集结果（岗位名、薪资、JD）：

1. **字体反爬**。数字被映射到 Unicode 私用区——``U+E030``~``U+E039`` 依次对应 ``0``~``9``
   ——DOM 里读出来的 ``textContent`` 就是这些码位，界面上显示成方框（用户看到的
   "全栈工程师-K" 就是 "23-26K" 被吃掉数字后的样子）。另外常用汉字会被换成**康熙部首**
   （``⼯`` ``⽤`` ``⽅`` ``⽣`` ``⾏``），这一层用 Unicode 的 **NFKC 归一化**就能还原
   （已实测：``⼯``→``工``、``⽉``→``月``）。
2. **水印 token**。在中文词中间插入自家品牌词（``boss`` / ``kanzhun`` / ``直聘``），用来在
   网上搜到被抄走的文案：``本boss科`` / ``业boss务`` / ``使kanzhun用`` / ``长直聘期``。

水印的移除规则是本模块最容易写错的地方，所以定得很窄：**只有当 token 夹在汉字之间
（或出现在文本开头且后面紧跟汉字）时才删**。理由是品牌名本身就含这两个词——
``BOSS直聘`` / ``Boss直聘`` 必须原样保留（有测试钉住）。小写 ``boss`` 才是水印：品牌名不会
写成全小写。

本模块只做**纯文本处理**（无网络、无浏览器、无数据库），因此可以逐条离线测。
"""
from __future__ import annotations

import re
import unicodedata

# 私用区数字：U+E030+i ↔ 字符 "i"。已用真实采集数据验证过（"全栈工程师\ue032\ue033-" → "23-"）。
_PRIVATE_USE_DIGITS = {chr(0xE030 + digit): str(digit) for digit in range(10)}

# **只对这几个区**做 NFKC 折叠，而**不是**对整段文本做 NFKC。
#
# 这一点是实测出来的：整段 NFKC 会把中文全角标点一并折成半角（`：`→`:`、`（`→`(`），
# 而中文 JD 里那些标点本来就该是全角——为了修几个异体字而把整篇标点改掉，是明显的得不偿失。
# 所以这里只认"字体反爬会用到的那几个区"：康熙部首、CJK 部首补充、CJK 兼容表意文字。
_FOLD_RANGES = (
    (0x2E80, 0x2EFF),  # CJK 部首补充
    (0x2F00, 0x2FDF),  # 康熙部首（实测：⼯→工、⽤→用、⽅→方、⽉→月）
    (0xF900, 0xFAFF),  # CJK 兼容表意文字
)

# 水印候选。**必须小写**——品牌名写作 BOSS/Boss，只有小写才是注入的水印。
_WATERMARK_TOKENS = ("boss", "kanzhun", "直聘")
# 夹在汉字之间、或位于文本开头且后接汉字时才算水印。
_WATERMARK_PATTERN = re.compile(
    r"(?:(?<=[\u4e00-\u9fff])|^)(?:" + "|".join(_WATERMARK_TOKENS) + r")(?=[\u4e00-\u9fff])"
)

# 零宽与格式化字符：NFKC 不会去掉 ZWSP，但它们会污染文本与去重比较。
_INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u2028\u2029\ufeff\u2060]")
# 连续空白压成一个空格（横向），连续空行压成一个空行（纵向）。
_HORIZONTAL_SPACES = re.compile(r"[ \t\u00a0\u3000]+")
_BLANK_LINES = re.compile(r"\n{3,}")

# 薪资文本的形态：15-25K / 8-21K·13薪 / 100-230元/天 / 200元/月 / 面议。
_SALARY_RANGE = r"\d+(?:\.\d+)?\s*[-~–—至]\s*\d+(?:\.\d+)?"
_SALARY_SINGLE = r"\d+(?:\.\d+)?"
_SALARY_UNIT = r"(?:[Kk]|元\s*/\s*[天月时周]|元/天|元/月|元/时|万)"
_SALARY_MONTHS = r"(?:\s*[·・]\s*\d+\s*薪)?"
_SALARY_BODY = rf"(?:{_SALARY_RANGE}\s*{_SALARY_UNIT}|{_SALARY_SINGLE}\s*{_SALARY_UNIT}|面议){_SALARY_MONTHS}"
_SALARY_ONLY = re.compile(rf"^{_SALARY_BODY}$")
_SALARY_SUFFIX = re.compile(rf"\s*({_SALARY_BODY})\s*$")

# 「任职要求」这一段的可能小标题。**按出现位置取最早的一个**，而不是按本表的顺序——
# 文案里先后顺序不固定，按表顺序会让"岗位职责在前、任职要求在后"被切反。
# 标题后常紧跟「：」/「:」（全角半角都有），``str.find`` 按前缀命中，所以不用把带冒号的
# 变体各写一遍。
_REQUIREMENT_HEADINGS = (
    "任职要求",
    "岗位要求",
    "职位要求",
    "任职资格",
    "任职条件",
    "资格要求",
    "技能要求",
    "能力要求",
    "我们希望你",
    "我们希望您",
)
# 「职位描述」这一段的可能小标题。本身不是切分点，而是"描述段确实存在"的证据：
# 当要求类标题出现得太靠前（不足 ``_MIN_DESCRIPTION_BEFORE_REQUIREMENTS``）时，只有
# 描述段里存在这类标题，才认为"前面有职责、后面有要求"是真实的，否则整篇留在描述里。
_DESCRIPTION_HEADINGS = ("岗位职责", "工作内容", "职位描述", "职责描述", "岗位描述", "职位介绍")
# 标题前面可能出现的开括号：往前吞掉它们，让要求段从 `【任职要求】` 完整开头。
_HEADING_OPENERS = "【〔「《（(＜<"

# 切分点之前至少要有这么多字，否则视为"整篇都是要求、没有职责段"，不做切分。
_MIN_DESCRIPTION_BEFORE_REQUIREMENTS = 30


def _fold_radical(char: str) -> str:
    """把一个异体字折回常用汉字；不在目标区、或折不动时原样返回。

    **宁可保留一个异体字，也不要破坏文本**：折成多字符的一律不采用。
    """
    code = ord(char)
    if not any(low <= code <= high for low, high in _FOLD_RANGES):
        return char
    folded = unicodedata.normalize("NFKC", char)
    return folded if len(folded) == 1 and folded != char else char


def normalize_text(value: object) -> str:
    """还原被混淆的文本：部首折叠 + 私用区数字 + 去水印 + 空白归一。

    幂等：对已经正常的文本再跑一次不会改动任何内容（水印规则要求 token 紧贴汉字，
    正常中文里很少出现这种组合，且 ``BOSS直聘`` 这类品牌名按小写规则被排除）。
    """
    text = str(value if value is not None else "")
    if not text:
        return ""
    text = "".join(_fold_radical(char) for char in text)
    text = text.translate(str.maketrans(_PRIVATE_USE_DIGITS))
    text = _WATERMARK_PATTERN.sub("", text)
    text = _INVISIBLE_CHARS.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HORIZONTAL_SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def looks_like_salary(value: object) -> bool:
    """这段文本本身是不是一个薪资（``15-25K`` / ``100-230元/天`` / ``面议``）。

    用来判断"卡片里的薪资元素取到的是不是薪资"——取错了（取到一个同时含岗位名的容器）
    时不至于把岗位名当成薪资写进库里。
    """
    return bool(_SALARY_ONLY.match(normalize_text(value)))


def split_title_salary(value: object) -> tuple[str, str]:
    """把"岗位名 + 薪资"粘连的文本拆开 → ``(岗位名, 薪资)``。

    BOSS 新版列表把岗位名与薪资放在**同一个链接里**（``<a class="job-name">全栈工程师23-26K</a>``），
    于是单独取"标题"会连薪资一起吃进来（用户反馈的 "全栈工程师-K" 就是这种粘连 + 数字被字体反爬
    吃掉的双重结果）。这里按"尾部是不是薪资"来切；切不出前缀时**原样返回**，绝不产出一个空标题。
    """
    text = normalize_text(value)
    if not text:
        return "", ""
    match = _SALARY_SUFFIX.search(text)
    if match is None:
        return text, ""
    title = text[: match.start()].strip(" \t·・-—–~、,，:：")
    if not title:
        # 整段就是一个薪资：保留在标题位，不要造出空标题。
        return text, ""
    return title, match.group(1).strip()


def split_job_sections(value: object) -> tuple[str, str]:
    """把 JD 全文按小标题切成 ``(职位描述, 任职要求)``。

    接口只给一整段 ``postDescription``，而界面上「职位描述」与「任职要求」是两个字段——
    以前一律整段塞进描述、要求留空，用户看到的就是"两件事被混在一起"。
    这里按真实存在的小标题切：取**最早出现**的要求类标题作为切分点，之前是描述、之后是要求。

    两条健壮化规则：

    - 要求类标题出现得太靠前时，原本一律不切（避免把"整篇只有要求"切出空描述）；现在只要
      描述段里存在「岗位职责 / 工作内容 / 职位描述」这类**描述段标题**，就说明前面确实有职责段，
      即使描述段偏短也照切——否则"岗位职责：…\n任职要求：…"这种紧凑 JD 会整个挤进职位描述。
    - 无任何要求类标题时保持原样：全文留在描述里（没有可切的分界，硬切只会更糟）。
    """
    text = normalize_text(value)
    if not text:
        return "", ""
    cut = _earliest_heading_index(text)
    if cut is None:
        return text, ""
    description = text[:cut].strip()
    requirements = text[cut:].strip()
    if not description:
        return text, ""
    # 切分点太靠前（描述段不足阈值）时，只有"描述段里确实有描述类标题"才认可这次切分；
    # 否则视为"整篇只有要求"，全文留在描述里——不产出一个空「职位描述」。
    if cut < _MIN_DESCRIPTION_BEFORE_REQUIREMENTS and not _has_description_heading(description):
        return text, ""
    return description, requirements


def _earliest_heading_index(text: str) -> int | None:
    found = [text.find(heading) for heading in _REQUIREMENT_HEADINGS]
    indexes = [index for index in found if index >= 0]
    if not indexes:
        return None
    return _widen_to_heading_start(text, min(indexes))


def _has_description_heading(text: str) -> bool:
    """描述段里是否存在「岗位职责 / 工作内容 / 职位描述」这类描述类标题。"""
    return any(text.find(heading) >= 0 for heading in _DESCRIPTION_HEADINGS)


def _widen_to_heading_start(text: str, index: int) -> int:
    """把切分点往前挪到"标题真正开始的地方"。

    标题常写作 ``【任职要求】`` / ``〔任职要求〕``，而关键字命中位置是 ``任``——直接在关键字处
    切，要求段就会以孤零零的 ``】`` 开头、描述段末尾也多一个 ``【``。往前吞掉紧邻的括号与空白。
    """
    while index > 0 and (text[index - 1].isspace() or text[index - 1] in _HEADING_OPENERS):
        index -= 1
    return index


__all__ = [
    "looks_like_salary",
    "normalize_text",
    "split_job_sections",
    "split_title_salary",
]

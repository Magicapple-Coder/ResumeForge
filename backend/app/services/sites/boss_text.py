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
from dataclasses import dataclass

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
# 「其他招聘信息」这一段的可能小标题（对应 ``Job.additional_info``）：福利、公司/团队介绍
# 这类既不属于职责也不属于要求的补充内容。**刻意不收「加分项」**——那通常写在要求段里，
# 收进来会把要求段截断。
_ADDITIONAL_HEADINGS = (
    "其他招聘信息",
    "其他信息",
    "其他说明",
    "福利待遇",
    "薪酬福利",
    "公司介绍",
    "公司简介",
    "团队介绍",
)
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


@dataclass(frozen=True)
class JobSections:
    """JD 全文里切出来的三段；切不出来的段落是空串（内容仍留在前一段，不会丢）。"""

    description: str = ""
    requirements: str = ""
    additional: str = ""


def split_job_sections(value: object) -> tuple[str, str]:
    """把 JD 全文按小标题切成 ``(职位描述, 任职要求)`` 两段。

    两段的旧口径保留给只需要这两项的调用方；三段（含「其他招聘信息」）走
    :func:`split_job_fields`，本函数是它的薄包装。
    """
    sections = split_job_fields(value)
    return sections.description, sections.requirements


def split_job_fields(value: object) -> JobSections:
    """把 JD 全文按小标题切成 ``职位描述 / 任职要求 / 其他招聘信息`` 三段。

    接口只给一整段 ``postDescription``，而界面上这是三个字段——以前一律整段塞进描述、
    另外两个留空，用户看到的就是"几件事被混在一起"。

    切法：找出所有**像小标题**的位置（见 :func:`_looks_like_heading`），按它们在原文里的
    先后逐段归属；切不出来的段落就是空串，**内容仍完整留在前一段里，不会丢**。

    三条健壮化规则：

    - 要求类标题出现得太靠前（前面不足 ``_MIN_DESCRIPTION_BEFORE_REQUIREMENTS`` 字）时，
      只有"前面确实有描述类标题"才认可这次切分；否则视为"整篇都是要求"、一段都不切，
      不产出一个空的「职位描述」。
    - 无任何小标题时全文留在描述里（没有可切的分界，硬切只会更糟）。
    - 同一段的小标题重复出现时，各段内容按原文顺序并进同一段，不覆盖、不丢。
    """
    text = normalize_text(value)
    if not text:
        return JobSections()
    cuts = _heading_cuts(text)
    if not cuts:
        return JobSections(description=text)

    requirement_indexes = [index for index, kind in cuts if kind == "requirements"]
    if (
        requirement_indexes
        and requirement_indexes[0] < _MIN_DESCRIPTION_BEFORE_REQUIREMENTS
        and not _has_description_heading(text[: requirement_indexes[0]])
    ):
        return JobSections(description=text)

    chunks: dict[str, list[str]] = {"description": [], "requirements": [], "additional": []}
    lead = text[: cuts[0][0]].strip()
    if lead:
        chunks["description"].append(lead)
    for position, (index, kind) in enumerate(cuts):
        end = cuts[position + 1][0] if position + 1 < len(cuts) else len(text)
        chunk = text[index:end].strip()
        if chunk:
            chunks[kind].append(chunk)
    # 描述段为空（全文以要求类/其他类标题开头，例如只有一段「福利待遇」）：与「整篇只有
    # 要求」同一处理——全文留在描述里。一个空的「职位描述」比不切更难看，也不丢内容。
    if not chunks["description"]:
        return JobSections(description=text)
    return JobSections(
        description="\n".join(chunks["description"]).strip(),
        requirements="\n".join(chunks["requirements"]).strip(),
        additional="\n".join(chunks["additional"]).strip(),
    )


# 小标题的**前边界**：行首、句末标点。这是"像标题"与"正文里恰好出现的词"的分界。
_SECTION_BOUNDARIES = "。；;！!？?.\n\r"
# 前边界只有空白/开括号（弱边界）时，标题后面要紧跟这些才算"长得像标题"。
_HEADING_TAIL_CHARS = "：:"


def _looks_like_heading(text: str, index: int, heading: str) -> bool:
    """这个位置是**小标题的开头**，还是正文里恰好出现的标题词？

    实测反例（真实采集数据，字节跳动 · 后端开发实习生电商安全 TikTok Shop）：
    ``为符合岗位要求的同学提供…`` 里的「岗位要求」是要求类标题词，却夹在句子中间。
    旧实现只看"关键词出现在哪"，于是从那里切：描述被截成
    ``岗位职责：日常实习：面向全体在校生，为符合`` 一句半，而真正的「任职要求」连同
    整篇正文一起进了要求段——两个字段都读不成话。

    规则：小标题必须**另起一段**——前面是行首或句末标点；前边界只有空白/开括号这种
    弱边界时，后面还得紧跟冒号，用来排掉「…符合岗位要求 我们希望你…」这类正文。
    """
    cursor = index
    while cursor > 0 and (text[cursor - 1].isspace() or text[cursor - 1] in _HEADING_OPENERS):
        cursor -= 1
    if cursor == 0 or text[cursor - 1] in _SECTION_BOUNDARIES:
        return True
    after = text[index + len(heading) : index + len(heading) + 1]
    return after in _HEADING_TAIL_CHARS


def _heading_cuts(text: str) -> list[tuple[int, str]]:
    """按位置从早到晚列出**像标题**的小标题切点：``(位置, 段名)``。

    段名是 ``description`` / ``requirements`` / ``additional``。每种标题串只认它**第一个
    像标题**的出现——同一串在别处再出现（多半是正文里的用词）不再重复切。位置相同或更靠前的
    候选取最早的那一个，避免「任职资格要求」这类嵌套标题切出两个紧挨的切点。
    """
    cuts: list[tuple[int, str]] = []
    for kind, headings in (
        ("description", _DESCRIPTION_HEADINGS),
        ("requirements", _REQUIREMENT_HEADINGS),
        ("additional", _ADDITIONAL_HEADINGS),
    ):
        for heading in headings:
            start = 0
            while (index := text.find(heading, start)) >= 0:
                start = index + 1
                if _looks_like_heading(text, index, heading):
                    cuts.append((_widen_to_heading_start(text, index), kind))
                    break
    cuts.sort()
    deduped: list[tuple[int, str]] = []
    for index, kind in cuts:
        if deduped and index <= deduped[-1][0]:
            continue
        deduped.append((index, kind))
    return deduped


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
    "JobSections",
    "looks_like_salary",
    "normalize_text",
    "split_job_fields",
    "split_job_sections",
    "split_title_salary",
]

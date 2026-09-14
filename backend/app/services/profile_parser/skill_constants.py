"""技能等级识别规则。"""

import re


_SKILL_LEVEL_RE = re.compile(
    r"^(熟练掌握|熟练使用|熟练|精通|掌握|熟悉|了解|入门|精通使用|proficient|advanced|intermediate|beginner|basic)$",
    re.IGNORECASE,
)
_SKILL_LEADING_LEVEL_RE = re.compile(
    r"^(?P<level>熟练掌握|熟练使用|熟练|精通|掌握|熟悉|了解|入门|精通使用|proficient|advanced|intermediate|beginner|basic)\s*[:：、,，]?\s*(?P<skills>.+)$",
    re.IGNORECASE,
)

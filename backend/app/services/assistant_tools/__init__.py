"""求职助手可调用的工具：读项目数据，以及新增/修改。

**边界（用户已确认）**：助手能新增和修改，但**不提供任何删除类工具**——模型无论
如何都造不成不可逆损失。设置里的模型配置与数据集管理也不在工具里：那两个端点有
回环强制校验，工具化等于绕过它。

写工具的参数一律交给现成的 Pydantic schema 校验（`JobCreate` / `JobUpdate` /
`ProfileUpdate`），与 HTTP 接口共用同一套约束，不另写一份。

按职责拆分：``_types``（Tool/ToolResult/联网搜索描述）、``_shared``（跨域 helper 与
常量）、``_registry``（注册表与执行入口）、``job_tools`` / ``data_tools`` /
``report_tools`` / ``search_tools``（按域拆分的 handler）。对外只从这里导入。
"""
from ._registry import _TOOLS, execute_tool, execute_tool_async, tool_definitions, tool_names
from ._shared import (  # noqa: F401 - 历史导出，测试经 assistant_tools.X 访问
    MAX_ASSISTANT_SKILL_FILE_CHARS,
    MAX_ASSISTANT_SKILL_FILES,
    MAX_ASSISTANT_SKILL_TOTAL_CHARS,
)
from ._types import Tool, ToolResult, web_search_description

__all__ = [
    "ToolResult",
    "Tool",
    "_TOOLS",
    "execute_tool",
    "execute_tool_async",
    "tool_definitions",
    "tool_names",
    "web_search_description",
]

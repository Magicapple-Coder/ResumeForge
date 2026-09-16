"""ResumeForge 后端应用包。"""

from .preflight import ensure_runtime_resources

# 先检查随包资源，再让任何子模块被导入：压缩包不完整时，用户应该看到一句"缺什么、
# 怎么办"，而不是 app/services/... 里的一条导入栈（依赖顺序，不能把调用改成延后）。
ensure_runtime_resources()

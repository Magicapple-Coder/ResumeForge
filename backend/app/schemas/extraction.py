"""岗位/个人资料识别接口共用的小结构。"""

from pydantic import BaseModel, ConfigDict, Field

# 一次识别允许的图片张数。与助手附件保持一致，界面上一眼能数完。
MAX_EXTRACTION_IMAGE_COUNT = 4
# 回传给前端展示的「识别到的原文」上限。这只是给人看的辅助信息，截断即可，
# 不参与字段校验（真正用于校验的转写在服务层，不受这个上限影响）。
MAX_RECOGNIZED_TEXT_CHARS = 20_000
# data URL 的字符上限：4 张 2 MB 图片编码后的长度，再多一定超限，
# 在解码之前就挡住，省得为一段注定不合法的 base64 分配内存。
MAX_IMAGE_DATA_CHARS = 4 * ((2 * 1024 * 1024 + 2) // 3) + 64


class ExtractionImageInput(BaseModel):
    """识别接口收到的一张图片。

    形状与助手附件一致（name/mime_type/data），但单独定义而不是复用
    ``AssistantAttachmentInput``：识别的契约比助手窄，也不该让
    ``schemas/job.py`` 反过来依赖 ``schemas/assistant.py``。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="", max_length=100)
    data: str = Field(min_length=1, max_length=MAX_IMAGE_DATA_CHARS)

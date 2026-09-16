"""岗位/个人资料识别接口共用的小结构。"""

from pydantic import BaseModel, ConfigDict, Field

# 一次识别允许的图片张数、文档份数。与助手附件保持一致，界面上一眼能数完；
# 两者还会共用同一份合计额度（见 attachments.assert_attachment_budget）。
MAX_EXTRACTION_IMAGE_COUNT = 4
MAX_EXTRACTION_DOCUMENT_COUNT = 4
# 回传给前端展示的「识别到的原文」上限。这只是给人看的辅助信息，截断即可，
# 不参与字段校验（真正用于校验的转写在服务层，不受这个上限影响）。
MAX_RECOGNIZED_TEXT_CHARS = 20_000
# data URL 的字符上限：4 张 2 MB 图片编码后的长度，再多一定超限，
# 在解码之前就挡住，省得为一段注定不合法的 base64 分配内存。
MAX_IMAGE_DATA_CHARS = 4 * ((2 * 1024 * 1024 + 2) // 3) + 64
# 文档走同一套体积约定，字符上限也按同一公式算。
MAX_DOCUMENT_DATA_CHARS = 4 * ((2 * 1024 * 1024 + 2) // 3) + 64


class _ExtractionAttachmentInput(BaseModel):
    """识别接口收到的图片或文档。

    形状与助手附件一致（name/mime_type/data），但单独定义而不是复用
    ``AssistantAttachmentInput``：识别的契约比助手窄，也不该让
    ``schemas/job.py`` 反过来依赖 ``schemas/assistant.py``。

    图片与文档的入参形状、体积约定完全相同，共用这个基类只是避免两处字段定义各自
    漂移；两者仍然是不同的类型，请求里也是两个字段（``images`` / ``documents``），
    因为后端对它们的处理方式完全不同：图片交给多模态模型，文档在本机提取文字。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(default="", max_length=100)
    data: str = Field(min_length=1)


class ExtractionImageInput(_ExtractionAttachmentInput):
    """识别接口收到的一张图片（截图）。"""

    data: str = Field(min_length=1, max_length=MAX_IMAGE_DATA_CHARS)


class ExtractionDocumentInput(_ExtractionAttachmentInput):
    """识别接口收到的一份文档（PDF/DOCX），文字由后端在本机提取。"""

    data: str = Field(min_length=1, max_length=MAX_DOCUMENT_DATA_CHARS)

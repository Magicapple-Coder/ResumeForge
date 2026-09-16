/**
 * 附件与文件的纯函数：限值、类型判定与读取。
 *
 * 助手附件和岗位/资料识别都用这一份。限值必须与后端 `services/attachments.py`
 * 保持一致——前端先拦一道只是为了少一次往返，服务端才是权威。
 */

/** 一次请求最多几个附件。 */
export const MAX_ATTACHMENT_COUNT = 4;
/** 单个附件的字节上限。 */
export const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024;
/**
 * 一次请求所有附件的合计上限。
 *
 * 这个数字同时是请求体不超后端 `MAX_REQUEST_BODY_MB` 的保证：base64 会把体积
 * 放大约三分之一，5 MB 编码后约 6.7 MB，仍在默认的 8 MB 之内。
 */
export const MAX_TOTAL_ATTACHMENT_BYTES = 5 * 1024 * 1024;

export const IMAGE_MIME_BY_EXTENSION: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  jpe: "image/jpeg",
  jfif: "image/jpeg",
  webp: "image/webp",
  gif: "image/gif",
  bmp: "image/bmp",
  tif: "image/tiff",
  tiff: "image/tiff",
};

/**
 * 文档：文字由后端在本机提取，前端只负责把原始文件读成 data URL。
 *
 * `docx` 的 MIME 必须与后端 `attachments.DOCX_MIME` 一致；浏览器给出的就是这个
 * 长串（少数环境给空值或 `application/octet-stream`，见 `classifyAttachment`）。
 */
export const DOCUMENT_MIME_BY_EXTENSION: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
};

/**
 * 浏览器能直接渲染的图片格式。
 *
 * TIFF 不在这里：只有 Safari 认它，其他浏览器会把预览显示成破图。这类图片提交后
 * 由后端转成 PNG，但提交前的前端预览没法救，所以退化成文件名标签。
 */
const PREVIEWABLE_IMAGE_MIMES = new Set([
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "image/bmp",
]);

const TEXT_MIMES_BY_EXTENSION: Record<string, ReadonlySet<string>> = {
  txt: new Set(["text/plain"]),
  md: new Set(["text/markdown", "text/plain"]),
  json: new Set(["application/json", "text/json", "text/plain"]),
  csv: new Set(["text/csv", "application/csv", "text/plain"]),
};
const TEXT_CANONICAL_MIME_BY_EXTENSION: Record<string, string> = {
  txt: "text/plain",
  md: "text/markdown",
  json: "application/json",
  csv: "text/csv",
};

/** 有些系统给不出准确 MIME，这几种按"没声明"处理。 */
const BLANK_DECLARED_MIMES = new Set(["", "application/octet-stream"]);

export interface AttachmentClassification {
  kind: "text" | "image" | "document";
  mimeType: string;
}

function fileExtension(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
}

function acceptFrom(extensions: string[]): string {
  return extensions.map((extension) => `.${extension}`).join(",");
}

/** 文本类附件的扩展名串。 */
export const TEXT_ACCEPT = acceptFrom(Object.keys(TEXT_MIMES_BY_EXTENSION));
/** 图片扩展名串（含会被后端转码的 bmp/tiff）。 */
export const IMAGE_ACCEPT = acceptFrom(Object.keys(IMAGE_MIME_BY_EXTENSION));
/** 文档扩展名串。 */
export const DOCUMENT_ACCEPT = acceptFrom(Object.keys(DOCUMENT_MIME_BY_EXTENSION));
/** 识别弹窗接受的类型：截图与文档（文本直接粘在输入框里）。 */
export const RECOGNITION_ACCEPT = `${IMAGE_ACCEPT},${DOCUMENT_ACCEPT}`;
/** 助手附件接受的类型：文本 + 图片 + 文档。 */
export const ASSISTANT_ACCEPT = `${TEXT_ACCEPT},${IMAGE_ACCEPT},${DOCUMENT_ACCEPT}`;

export function canPreviewImage(mimeType: string): boolean {
  return PREVIEWABLE_IMAGE_MIMES.has(mimeType.split(";", 1)[0].trim().toLowerCase());
}

/**
 * 按**扩展名**判定类型，并要求它与浏览器给出的 MIME 一致。
 *
 * 不信任 `File.type`：它由系统映射决定，改名或换机器就可能变。两边不一致说明
 * 文件本身可疑，直接拒绝而不是挑一个信。
 */
export function classifyAttachment(file: File): AttachmentClassification | null {
  const extension = fileExtension(file.name);
  const declaredMime = file.type.split(";", 1)[0].trim().toLowerCase();
  const imageMime = IMAGE_MIME_BY_EXTENSION[extension];
  if (imageMime) {
    return declaredMime === imageMime ? { kind: "image", mimeType: imageMime } : null;
  }

  const documentMime = DOCUMENT_MIME_BY_EXTENSION[extension];
  if (documentMime) {
    const declaredIsAcceptable =
      BLANK_DECLARED_MIMES.has(declaredMime) || declaredMime === documentMime;
    return declaredIsAcceptable ? { kind: "document", mimeType: documentMime } : null;
  }

  const textMimes = TEXT_MIMES_BY_EXTENSION[extension];
  if (textMimes && (!declaredMime || textMimes.has(declaredMime))) {
    return {
      kind: "text",
      mimeType: declaredMime || TEXT_CANONICAL_MIME_BY_EXTENSION[extension],
    };
  }
  return null;
}

export function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("读取附件失败"));
    reader.readAsDataURL(file);
  });
}

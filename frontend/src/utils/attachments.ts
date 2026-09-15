/**
 * 附件与图片的纯函数：限值、类型判定与读取。
 *
 * 助手附件和岗位/资料识别都用这一份。限值必须与后端 `services/attachments.py`
 * 保持一致——前端先拦一道只是为了少一次往返，服务端才是权威。
 */

/** 一次请求最多几张/几个附件。 */
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
  webp: "image/webp",
  gif: "image/gif",
};

export const IMAGE_MIME_TYPES = Object.values(IMAGE_MIME_BY_EXTENSION);

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

export interface AttachmentClassification {
  kind: "text" | "image";
  mimeType: string;
}

function fileExtension(name: string): string {
  return name.split(".").pop()?.toLowerCase() ?? "";
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

/** 供 `<input accept>` / antd `Upload accept` 使用的图片扩展名串。 */
export const IMAGE_ACCEPT = Object.keys(IMAGE_MIME_BY_EXTENSION)
  .map((extension) => `.${extension}`)
  .join(",");

/**
 * 识别用的文件暂存：选择、粘贴、移除与限额。
 *
 * 岗位识别和个人资料识别共用。截图与文档（pdf/docx）在提交前只存在于前端，读取成
 * data URL 后随 JSON 一起发给后端——与助手附件同一条路子（仓库里没有 multipart）。
 * 文档的文字提取在后端完成，前端只负责把原始文件传过去。
 */

import { App } from "antd";
import { useCallback, useRef, useState } from "react";
import {
  DOCUMENT_MIME_BY_EXTENSION,
  IMAGE_MIME_BY_EXTENSION,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
  classifyAttachment,
  readAsDataUrl,
} from "../utils/attachments";

export interface StagedFile {
  id: number;
  name: string;
  mime_type: string;
  /** 识别只收截图与文档；文本文件请直接粘进输入框。 */
  kind: "image" | "document";
  /** base64 data URL，直接进请求体。 */
  data: string;
  size: number;
}

/** 剪贴板给的 blob 可能没有文件名，按 MIME 补一个。 */
const EXTENSION_BY_MIME: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
  "image/bmp": "bmp",
  "image/tiff": "tif",
};

function withUsableName(file: File, index: number): File {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_MIME_BY_EXTENSION[extension] || DOCUMENT_MIME_BY_EXTENSION[extension]) return file;
  const suffix = EXTENSION_BY_MIME[file.type] ?? "png";
  return new File([file], `clipboard-${index + 1}.${suffix}`, { type: file.type });
}

function clipboardImages(clipboardData: DataTransfer | null): File[] {
  if (!clipboardData) return [];
  const files: File[] = [];
  for (const item of Array.from(clipboardData.items ?? [])) {
    if (item.kind !== "file" || !item.type.startsWith("image/")) continue;
    const file = item.getAsFile();
    if (file) files.push(withUsableName(file, files.length));
  }
  return files;
}

/** 把暂存区里的文件按类型拆成请求体需要的两组入参（图片与文档是两个字段）。 */
export function attachmentInputs(files: StagedFile[], kind: StagedFile["kind"]) {
  return files
    .filter((file) => file.kind === kind)
    .map(({ name, mime_type, data }) => ({ name, mime_type, data }));
}

export function useRecognitionFiles() {
  const { message } = App.useApp();
  const [files, setFiles] = useState<StagedFile[]>([]);
  const [reading, setReading] = useState(false);
  // 先占位再读：并发选入多个文件时，后面的判断必须看得到前面已经占掉的额度。
  const usageRef = useRef({ count: 0, bytes: 0 });
  const sequenceRef = useRef(0);

  const addFiles = useCallback(
    async (incoming: File[]) => {
      const accepted: File[] = [];
      let occupied = usageRef.current;

      for (const file of incoming) {
        if (occupied.count >= MAX_ATTACHMENT_COUNT) {
          message.warning(`最多只能添加 ${MAX_ATTACHMENT_COUNT} 个文件`);
          break;
        }
        const classification = classifyAttachment(file);
        if (!classification || classification.kind === "text") {
          message.warning(
            `「${file.name}」不是受支持的截图或文档（png/jpg/webp/gif/bmp/tiff、pdf/docx）`,
          );
          continue;
        }
        if (file.size > MAX_ATTACHMENT_BYTES) {
          message.warning(`「${file.name}」超过 2 MB`);
          continue;
        }
        if (occupied.bytes + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
          message.warning("文件总大小不能超过 5 MB");
          continue;
        }
        accepted.push(file);
        occupied = {
          count: occupied.count + 1,
          bytes: occupied.bytes + file.size,
        };
      }

      if (accepted.length === 0) return;
      usageRef.current = occupied;

      setReading(true);
      try {
        const staged = await Promise.all(
          accepted.map(async (file) => {
            const classification = classifyAttachment(file);
            return {
              id: ++sequenceRef.current,
              name: file.name,
              mime_type: classification?.mimeType ?? "image/png",
              kind: (classification?.kind ?? "image") as StagedFile["kind"],
              data: await readAsDataUrl(file),
              size: file.size,
            };
          }),
        );
        setFiles((current) => [...current, ...staged]);
      } catch (error) {
        // 读取失败要把占位还回去，否则额度会被白白吃掉
        usageRef.current = {
          count: usageRef.current.count - accepted.length,
          bytes: usageRef.current.bytes - accepted.reduce((sum, file) => sum + file.size, 0),
        };
        message.error(error instanceof Error ? error.message : "读取文件失败");
      } finally {
        setReading(false);
      }
    },
    [message],
  );

  const removeFile = useCallback((id: number) => {
    setFiles((current) => {
      const target = current.find((item) => item.id === id);
      if (target) {
        usageRef.current = {
          count: Math.max(0, usageRef.current.count - 1),
          bytes: Math.max(0, usageRef.current.bytes - target.size),
        };
      }
      return current.filter((item) => item.id !== id);
    });
  }, []);

  const clear = useCallback(() => {
    usageRef.current = { count: 0, bytes: 0 };
    setFiles([]);
  }, []);

  const onPaste = useCallback(
    (event: React.ClipboardEvent<HTMLElement>) => {
      const pasted = clipboardImages(event.clipboardData);
      // 只在确实剪贴到图片时拦截，否则会把正常的文本粘贴吃掉
      if (pasted.length === 0) return;
      event.preventDefault();
      void addFiles(pasted);
    },
    [addFiles],
  );

  return { files, reading, addFiles, removeFile, clear, onPaste };
}

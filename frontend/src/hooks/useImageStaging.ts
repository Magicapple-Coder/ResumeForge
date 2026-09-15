/**
 * 识别用的图片暂存：选择、粘贴、移除与限额。
 *
 * 岗位识别和个人资料识别共用。图片在提交前只存在于前端，读取成 data URL 后随
 * JSON 一起发给后端——与助手附件同一条路子（仓库里没有 multipart）。
 */

import { App } from "antd";
import { useCallback, useRef, useState } from "react";
import {
  IMAGE_MIME_BY_EXTENSION,
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
  classifyAttachment,
  readAsDataUrl,
} from "../utils/attachments";

export interface StagedImage {
  id: number;
  name: string;
  mime_type: string;
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
};

function withUsableName(file: File, index: number): File {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (IMAGE_MIME_BY_EXTENSION[extension]) return file;
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

export function useImageStaging() {
  const { message } = App.useApp();
  const [images, setImages] = useState<StagedImage[]>([]);
  const [reading, setReading] = useState(false);
  // 先占位再读：并发选入多张时，后面的判断必须看得到前面已经占掉的额度。
  const usageRef = useRef({ count: 0, bytes: 0 });
  const sequenceRef = useRef(0);

  const addFiles = useCallback(
    async (files: File[]) => {
      const accepted: File[] = [];
      let occupied = usageRef.current;

      for (const file of files) {
        if (occupied.count >= MAX_ATTACHMENT_COUNT) {
          message.warning(`最多只能添加 ${MAX_ATTACHMENT_COUNT} 张图片`);
          break;
        }
        const classification = classifyAttachment(file);
        if (!classification || classification.kind !== "image") {
          message.warning(`「${file.name}」不是受支持的图片（png/jpg/webp/gif）`);
          continue;
        }
        if (file.size > MAX_ATTACHMENT_BYTES) {
          message.warning(`「${file.name}」超过 2 MB`);
          continue;
        }
        if (occupied.bytes + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
          message.warning("图片总大小不能超过 5 MB");
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
          accepted.map(async (file) => ({
            id: ++sequenceRef.current,
            name: file.name,
            mime_type: classifyAttachment(file)?.mimeType ?? "image/png",
            data: await readAsDataUrl(file),
            size: file.size,
          })),
        );
        setImages((current) => [...current, ...staged]);
      } catch (error) {
        // 读取失败要把占位还回去，否则额度会被白白吃掉
        usageRef.current = {
          count: usageRef.current.count - accepted.length,
          bytes: usageRef.current.bytes - accepted.reduce((sum, file) => sum + file.size, 0),
        };
        message.error(error instanceof Error ? error.message : "读取图片失败");
      } finally {
        setReading(false);
      }
    },
    [message],
  );

  const removeImage = useCallback((id: number) => {
    setImages((current) => {
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
    setImages([]);
  }, []);

  const onPaste = useCallback(
    (event: React.ClipboardEvent<HTMLElement>) => {
      const files = clipboardImages(event.clipboardData);
      // 只在确实剪贴到图片时拦截，否则会把正常的文本粘贴吃掉
      if (files.length === 0) return;
      event.preventDefault();
      void addFiles(files);
    },
    [addFiles],
  );

  return { images, reading, addFiles, removeImage, clear, onPaste };
}

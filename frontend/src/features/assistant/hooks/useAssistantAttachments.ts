/** 求职助手附件读取、容量预留和待发送状态。 */

import { App } from "antd";
import type { MutableRefObject } from "react";
import { useCallback, useRef, useState } from "react";
import {
  MAX_ATTACHMENT_BYTES,
  MAX_ATTACHMENT_COUNT,
  MAX_TOTAL_ATTACHMENT_BYTES,
  classifyAttachment,
  readAsDataUrl,
  type PendingAttachment,
} from "../assistantUtils";

interface Options {
  mountedRef: MutableRefObject<boolean>;
}

export function useAssistantAttachments({ mountedRef }: Options) {
  const { message } = App.useApp();
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentReads, setAttachmentReads] = useState(0);
  const attachmentsRef = useRef<PendingAttachment[]>([]);
  const attachmentSequenceRef = useRef(0);
  const attachmentReadsRef = useRef(0);
  const attachmentUsageRef = useRef({ count: 0, bytes: 0 });

  const clearAttachments = useCallback(() => {
    attachmentsRef.current = [];
    attachmentUsageRef.current = { count: attachmentReadsRef.current, bytes: 0 };
    setAttachments([]);
  }, []);

  const removeAttachment = useCallback((attachmentId: number) => {
    const attachment = attachmentsRef.current.find((item) => item.id === attachmentId);
    if (!attachment) return;
    const next = attachmentsRef.current.filter((item) => item.id !== attachmentId);
    attachmentsRef.current = next;
    attachmentUsageRef.current = {
      count: Math.max(attachmentReadsRef.current, attachmentUsageRef.current.count - 1),
      bytes: Math.max(0, attachmentUsageRef.current.bytes - attachment.size),
    };
    setAttachments(next);
  }, []);

  const addAttachment = useCallback(
    async (file: File) => {
      const classification = classifyAttachment(file);
      if (!classification) {
        message.warning("附件扩展名与文件类型不一致，或格式不受支持");
        return;
      }
      if (attachmentUsageRef.current.count >= MAX_ATTACHMENT_COUNT) {
        message.warning(`每条消息最多添加 ${MAX_ATTACHMENT_COUNT} 个附件`);
        return;
      }
      if (file.size > MAX_ATTACHMENT_BYTES) {
        message.warning(`单个附件不能超过 ${MAX_ATTACHMENT_BYTES / 1024 / 1024} MB`);
        return;
      }
      if (attachmentUsageRef.current.bytes + file.size > MAX_TOTAL_ATTACHMENT_BYTES) {
        message.warning(`附件总大小不能超过 ${MAX_TOTAL_ATTACHMENT_BYTES / 1024 / 1024} MB`);
        return;
      }
      attachmentUsageRef.current = {
        count: attachmentUsageRef.current.count + 1,
        bytes: attachmentUsageRef.current.bytes + file.size,
      };
      attachmentReadsRef.current += 1;
      setAttachmentReads((current) => current + 1);
      try {
        const data =
          classification.kind === "image" ? await readAsDataUrl(file) : await file.text();
        if (!mountedRef.current) return;
        const attachment: PendingAttachment = {
          id: ++attachmentSequenceRef.current,
          name: file.name,
          mime_type: classification.mimeType,
          data,
          size: file.size,
          kind: classification.kind,
        };
        const next = [...attachmentsRef.current, attachment];
        attachmentsRef.current = next;
        setAttachments(next);
      } catch (error) {
        attachmentUsageRef.current = {
          count: Math.max(0, attachmentUsageRef.current.count - 1),
          bytes: Math.max(0, attachmentUsageRef.current.bytes - file.size),
        };
        message.error(error instanceof Error ? error.message : "读取附件失败");
      } finally {
        attachmentReadsRef.current = Math.max(0, attachmentReadsRef.current - 1);
        if (mountedRef.current) setAttachmentReads((current) => Math.max(0, current - 1));
      }
    },
    [message, mountedRef],
  );

  return {
    attachments,
    attachmentsRef,
    attachmentReads,
    attachmentReadsRef,
    clearAttachments,
    removeAttachment,
    addAttachment,
  };
}

/** 求职助手流式发送、停止、乐观消息和刷新收尾。 */

import type { MutableRefObject } from "react";
import { useCallback, useRef, useState } from "react";
import { sendAssistantMessage } from "../../../api/assistant";
import type { AssistantSource, AssistantStreamEvent } from "../../../types";
import type { PendingAttachment } from "../assistantUtils";

interface Options {
  activeIdRef: MutableRefObject<number | null>;
  reloadConversations: () => Promise<unknown>;
  loadDetail: (id: number) => Promise<void>;
  createConversation: () => Promise<number | null>;
  clearAttachments: () => void;
  attachmentReadsRef: MutableRefObject<number>;
  attachmentsRef: MutableRefObject<PendingAttachment[]>;
  mountedRef: MutableRefObject<boolean>;
  jobId: number | undefined;
  resumeId: number | undefined;
  includeProfile: boolean;
  webSearch: boolean;
}

export function useAssistantStream({
  activeIdRef,
  reloadConversations,
  loadDetail,
  createConversation,
  clearAttachments,
  attachmentReadsRef,
  attachmentsRef,
  mountedRef,
  jobId,
  resumeId,
  includeProfile,
  webSearch,
}: Options) {
  const [sending, setSending] = useState(false);
  const [sendingConversationId, setSendingConversationId] = useState<number | null>(null);
  const [pendingUserText, setPendingUserText] = useState("");
  const [pendingUserAttachments, setPendingUserAttachments] = useState<PendingAttachment[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [streamingSources, setStreamingSources] = useState<AssistantSource[]>([]);
  const [progressText, setProgressText] = useState("");
  const [streamError, setStreamError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  const sendingRef = useRef(false);

  const stop = useCallback(() => abortRef.current?.abort(), []);

  const send = useCallback(
    async (text: string, clearContent: () => void) => {
      const trimmedText = text.trim();
      if (
        (!trimmedText && attachmentsRef.current.length === 0) ||
        sendingRef.current ||
        attachmentReadsRef.current > 0
      ) {
        return;
      }
      sendingRef.current = true;
      setSending(true);
      const conversationId = activeIdRef.current ?? (await createConversation());
      if (!conversationId) {
        sendingRef.current = false;
        setSending(false);
        return;
      }
      const attachmentPayload = attachmentsRef.current.map(({ name, mime_type, data }) => ({
        name,
        mime_type,
        data,
      }));
      const optimisticAttachments = [...attachmentsRef.current];
      clearContent();
      setPendingUserText(trimmedText || "[附件]");
      setPendingUserAttachments(optimisticAttachments);
      setStreamingText("");
      setStreamingSources([]);
      setProgressText("");
      setStreamError("");
      setSendingConversationId(conversationId);
      clearAttachments();
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        await sendAssistantMessage(
          conversationId,
          {
            content: trimmedText,
            job_id: jobId,
            resume_id: resumeId,
            include_profile: includeProfile,
            web_search: webSearch,
            attachments: attachmentPayload,
          },
          (event: AssistantStreamEvent) => {
            if (abortRef.current !== controller) return;
            if (event.type === "delta") setStreamingText((current) => current + event.text);
            if (event.type === "progress") setProgressText(event.message);
            if (event.type === "sources") {
              setStreamingSources(event.sources);
              if (event.error) setProgressText(event.error);
            }
            if (event.type === "error") setStreamError(event.message);
            if (event.type === "start") void reloadConversations();
          },
          controller.signal,
        );
      } catch (error) {
        if (!controller.signal.aborted) {
          setStreamError(error instanceof Error ? error.message : "发送消息失败");
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        sendingRef.current = false;
        if (mountedRef.current) {
          setSending(false);
          setPendingUserText("");
          setPendingUserAttachments([]);
          setStreamingText("");
          const refreshes: Promise<unknown>[] = [reloadConversations()];
          if (activeIdRef.current === conversationId) refreshes.push(loadDetail(conversationId));
          await Promise.all(refreshes);
        }
      }
    },
    [
      activeIdRef,
      attachmentReadsRef,
      attachmentsRef,
      clearAttachments,
      createConversation,
      includeProfile,
      jobId,
      loadDetail,
      mountedRef,
      reloadConversations,
      resumeId,
      webSearch,
    ],
  );

  return {
    sending,
    sendingConversationId,
    pendingUserText,
    pendingUserAttachments,
    streamingText,
    streamingSources,
    progressText,
    streamError,
    abortRef,
    send,
    stop,
  };
}

/** 求职助手流式发送、停止、乐观消息和刷新收尾。 */

import type { MutableRefObject } from "react";
import { useCallback, useRef, useState } from "react";
import { sendAssistantMessage } from "../../../api/assistant";
import type {
  AssistantSource,
  AssistantSourceNumber,
  AssistantStreamEvent,
  AssistantToolCall,
  ReasoningEffort,
} from "../../../types";
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
  reasoningEffort: ReasoningEffort;
  /** 当前引用的消息 id；发送时随请求带上，之后清空。 */
  quotedMessageId: number | null;
  clearQuote: () => void;
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
  reasoningEffort,
  quotedMessageId,
  clearQuote,
}: Options) {
  const [sending, setSending] = useState(false);
  const [sendingConversationId, setSendingConversationId] = useState<number | null>(null);
  const [pendingUserText, setPendingUserText] = useState("");
  // 正在发送的这条消息还没有服务端时间戳，用它被发出的时刻顶上。
  const [pendingSentAt, setPendingSentAt] = useState("");
  const [pendingUserAttachments, setPendingUserAttachments] = useState<PendingAttachment[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [streamingReasoning, setStreamingReasoning] = useState("");
  const [streamingSources, setStreamingSources] = useState<AssistantSource[]>([]);
  const [streamingSourceMap, setStreamingSourceMap] = useState<AssistantSourceNumber[]>([]);
  const [streamingTools, setStreamingTools] = useState<AssistantToolCall[]>([]);
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
      // 引用只对这一次提问有效：发出去就清掉，避免用户以为下一条也带着引用。
      clearQuote();
      setPendingUserText(trimmedText || "[附件]");
      setPendingSentAt(new Date().toISOString());
      setPendingUserAttachments(optimisticAttachments);
      setStreamingText("");
      setStreamingReasoning("");
      setStreamingSources([]);
      setStreamingSourceMap([]);
      setStreamingTools([]);
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
            reasoning_effort: reasoningEffort,
            quoted_message_id: quotedMessageId,
            attachments: attachmentPayload,
          },
          (event: AssistantStreamEvent) => {
            if (abortRef.current !== controller) return;
            if (event.type === "delta") setStreamingText((current) => current + event.text);
            if (event.type === "reasoning")
              setStreamingReasoning((current) => current + event.text);
            if (event.type === "progress") setProgressText(event.message);
            if (event.type === "sources") {
              setStreamingSources(event.sources);
              setStreamingSourceMap(event.source_map ?? []);
              if (event.error) setProgressText(event.error);
            }
            if (event.type === "tool") {
              // 显式挑字段，而不是解构剔除 type：仓库的 lint 不允许未使用的变量。
              setStreamingTools((current) => [
                ...current,
                {
                  name: event.name,
                  arguments: event.arguments,
                  summary: event.summary,
                  link: event.link,
                  ok: event.ok,
                  error: event.error,
                  changed: event.changed,
                },
              ]);
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
          setStreamingReasoning("");
          setStreamingTools([]);
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
      clearQuote,
      createConversation,
      includeProfile,
      jobId,
      loadDetail,
      mountedRef,
      quotedMessageId,
      reasoningEffort,
      reloadConversations,
      resumeId,
      webSearch,
    ],
  );

  return {
    sending,
    sendingConversationId,
    pendingUserText,
    pendingSentAt,
    pendingUserAttachments,
    streamingText,
    streamingReasoning,
    streamingSources,
    streamingSourceMap,
    streamingTools,
    progressText,
    streamError,
    abortRef,
    send,
    stop,
  };
}

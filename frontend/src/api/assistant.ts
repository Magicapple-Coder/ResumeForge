/** AI 求职助手：会话历史、附件和流式消息。 */
import type {
  AssistantAttachmentInput,
  AssistantConversationBrief,
  AssistantConversationDetail,
  AssistantConversationForkPayload,
  AssistantStreamEvent,
  ReasoningEffort,
} from "../types";
import { request } from "./client";
import { consumeSSE } from "./stream";

export function listAssistantConversations(): Promise<AssistantConversationBrief[]> {
  return request("/assistant/conversations?limit=100");
}

/**
 * 新建会话。`welcome: true` 时后端会附上一条内置引导消息——首次进入助手页、
 * 还没有任何会话时用它生成"默认引导对话"。
 */
export function createAssistantConversation(
  title = "",
  options: { welcome?: boolean } = {},
): Promise<AssistantConversationBrief> {
  return request("/assistant/conversations", {
    method: "POST",
    body: JSON.stringify({ title, welcome: options.welcome ?? false }),
  });
}

export function getAssistantConversation(id: number): Promise<AssistantConversationDetail> {
  return request(`/assistant/conversations/${id}`);
}

export function renameAssistantConversation(
  id: number,
  title: string,
): Promise<AssistantConversationBrief> {
  return request(`/assistant/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function updateAssistantConversation(
  id: number,
  patch: {
    title?: string;
    pinned?: boolean;
    favorite?: boolean;
    archived?: boolean;
    group_name?: string;
  },
): Promise<AssistantConversationBrief> {
  return request(`/assistant/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

/** 「在新对话中继续」：复制这段会话最近的上下文到一段新会话。 */
export function forkAssistantConversation(
  id: number,
  payload: AssistantConversationForkPayload = {},
): Promise<AssistantConversationDetail> {
  return request(`/assistant/conversations/${id}/fork`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteAssistantConversation(id: number): Promise<void> {
  return request(`/assistant/conversations/${id}`, { method: "DELETE" });
}

export function sendAssistantMessage(
  id: number,
  payload: {
    content: string;
    job_id?: number | null;
    resume_id?: number | null;
    include_profile?: boolean;
    web_search?: boolean;
    reasoning_effort?: ReasoningEffort;
    attachments?: AssistantAttachmentInput[];
  },
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return consumeSSE(`/api/assistant/conversations/${id}/messages`, payload, onEvent, signal);
}

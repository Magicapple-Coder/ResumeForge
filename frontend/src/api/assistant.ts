/** AI 求职助手：会话历史、附件和流式消息。 */
import type {
  AssistantAttachmentInput,
  AssistantConversationBrief,
  AssistantConversationDetail,
  AssistantStreamEvent,
} from "../types";
import { request } from "./client";
import { consumeSSE } from "./stream";

export function listAssistantConversations(): Promise<AssistantConversationBrief[]> {
  return request("/assistant/conversations?limit=100");
}

export function createAssistantConversation(title = ""): Promise<AssistantConversationBrief> {
  return request("/assistant/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
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
  patch: { title?: string; pinned?: boolean; favorite?: boolean },
): Promise<AssistantConversationBrief> {
  return request(`/assistant/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
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
    attachments?: AssistantAttachmentInput[];
  },
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return consumeSSE(`/api/assistant/conversations/${id}/messages`, payload, onEvent, signal);
}

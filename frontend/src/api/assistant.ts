/** AI 求职助手：会话历史、附件和流式消息。 */
import type {
  AssistantAttachmentInput,
  AssistantConversationBrief,
  AssistantConversationDetail,
  AssistantConversationForkPayload,
  AssistantStreamEvent,
  ReasoningEffort,
} from "../types";
import type { Material } from "../types";
import { ApiError, getFilenameFromDisposition, request, extractError } from "./client";
import { consumeSSE } from "./stream";

export function listAssistantConversations(): Promise<AssistantConversationBrief[]> {
  return request("/assistant/conversations?limit=100");
}

/** 导出格式：Markdown（可读可贴）、纯文本（去掉标记）、JSON（结构化，便于再加工）。 */
export type ConversationExportFormat = "md" | "txt" | "json";

/** 导出对话为文件；返回 blob 与服务端建议的文件名。 */
export async function exportConversation(
  id: number,
  format: ConversationExportFormat = "md",
): Promise<{ blob: Blob; filename: string }> {
  // 裸 fetch：响应是文件内容，不是 JSON。
  const resp = await fetch(`/api/assistant/conversations/${id}/export?format=${format}`);
  if (!resp.ok) throw new ApiError(await extractError(resp), resp.status);
  return {
    blob: await resp.blob(),
    filename:
      getFilenameFromDisposition(resp.headers.get("Content-Disposition")) ??
      `conversation.${format}`,
  };
}

/**
 * 把一段对话存进资料箱。
 *
 * 存进去的是一份可读的对话记录，助手之后能读它、总结它，或按用户要求整理进个人资料。
 */
export function conversationToMaterial(
  id: number,
  payload: { title?: string; category?: string; note?: string } = {},
): Promise<Material> {
  return request(`/assistant/conversations/${id}/to-material`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
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

/**
 * 删除单条消息。
 *
 * 引用它的消息不会被级联删除：引用块是快照，删掉原消息后引用仍然可读。
 */
export function deleteAssistantMessage(conversationId: number, messageId: number): Promise<void> {
  return request(`/assistant/conversations/${conversationId}/messages/${messageId}`, {
    method: "DELETE",
  });
}

/**
 * 一次删除多条消息（多选模式走这里）。
 *
 * 单独走批量接口而不是循环调单条：后端在一个事务里删完并校验会话归属，中途失败不会
 * 留下"删了一半"的状态。一次最多 200 条。
 */
export function deleteAssistantMessages(
  conversationId: number,
  messageIds: number[],
): Promise<{ deleted: number }> {
  return request(`/assistant/conversations/${conversationId}/messages/delete`, {
    method: "POST",
    body: JSON.stringify({ message_ids: messageIds }),
  });
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
    /** 引用某条历史消息追问；被引用内容的快照会存进消息里。 */
    quoted_message_id?: number | null;
    attachments?: AssistantAttachmentInput[];
  },
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  return consumeSSE(`/api/assistant/conversations/${id}/messages`, payload, onEvent, signal);
}

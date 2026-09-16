/** AI 求职助手会话、消息和流式事件类型。 */

export interface AssistantConversationBrief {
  id: number;
  title: string;
  pinned: boolean;
  favorite: boolean;
  created_at: string;
  updated_at: string;
}

export interface AssistantAttachment {
  name: string;
  mime_type: string;
  /** document：pdf/docx，正文已由后端在本机提取进 `text`。 */
  kind: "text" | "image" | "document";
  size_bytes: number;
  text: string;
  data_url: string;
  /** 提取过程中的说明（例如内容过长只取了前一部分）。 */
  notes: string[];
}

export interface AssistantSource {
  title: string;
  url: string;
  snippet: string;
}

/** 助手调用过一次工具的记录；写在助手消息的 context 里，供历史回看。 */
export interface AssistantToolCall {
  name: string;
  arguments: Record<string, unknown>;
  summary: string;
  link: string;
  ok: boolean;
  error: string;
}

export interface AssistantMessage {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  attachments: AssistantAttachment[];
  context: {
    job_id?: number | null;
    resume_id?: number | null;
    include_profile?: boolean;
    web_search?: boolean;
    sources?: AssistantSource[];
    tool_calls?: AssistantToolCall[];
  };
  status: "pending" | "complete" | "error" | "cancelled";
  error: string;
  model: string;
  created_at: string;
}

export interface AssistantConversationDetail extends AssistantConversationBrief {
  messages: AssistantMessage[];
}

export interface AssistantAttachmentInput {
  name: string;
  mime_type: string;
  data: string;
}

export type AssistantStreamEvent =
  | {
      type: "start";
      user_message_id: number;
      assistant_message_id: number;
      conversation_title: string;
    }
  | { type: "progress"; message: string }
  | { type: "sources"; sources: AssistantSource[]; error: string }
  | ({
      type: "tool";
    } & AssistantToolCall)
  | { type: "delta"; text: string }
  | { type: "done"; message: AssistantMessage }
  | { type: "error"; message: string };

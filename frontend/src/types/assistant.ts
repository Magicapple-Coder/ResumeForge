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
  kind: "text" | "image";
  size_bytes: number;
  text: string;
  data_url: string;
}

export interface AssistantSource {
  title: string;
  url: string;
  snippet: string;
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
  | { type: "delta"; text: string }
  | { type: "done"; message: AssistantMessage }
  | { type: "error"; message: string };

/** AI 求职助手会话、消息和流式事件类型。 */

export interface AssistantConversationBrief {
  id: number;
  title: string;
  pinned: boolean;
  favorite: boolean;
  /** 已归档的会话默认收进「已归档」筛选，不参与置顶排序。 */
  archived: boolean;
  /** 分组名（"移动到项目"）；空串表示未分组。 */
  group_name: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** 会话列表筛选：全部 / 收藏 / 已归档。 */
export type ConversationFilter = "all" | "favorite" | "archived";

/** 思考强度：空串表示不发送该参数，沿用服务商默认。 */
export type ReasoningEffort = "" | "none" | "low" | "medium" | "high";

export const REASONING_EFFORT_OPTIONS: { value: ReasoningEffort; label: string }[] = [
  { value: "", label: "默认" },
  { value: "none", label: "关闭" },
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
];

export interface AssistantConversationForkPayload {
  title?: string;
  message_limit?: number;
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

/** 被引用的那条消息的快照：原消息删掉之后这里仍然可读。 */
export interface AssistantQuotedMessage {
  id: number;
  role: "user" | "assistant";
  excerpt: string;
}

export interface AssistantMessage {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  /** 引用追问：这条消息引用的是哪一条。 */
  quoted_message_id: number | null;
  attachments: AssistantAttachment[];
  context: {
    job_id?: number | null;
    resume_id?: number | null;
    include_profile?: boolean;
    web_search?: boolean;
    sources?: AssistantSource[];
    tool_calls?: AssistantToolCall[];
    quoted?: AssistantQuotedMessage;
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

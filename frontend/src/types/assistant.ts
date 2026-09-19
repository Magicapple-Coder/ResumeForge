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

/**
 * 一次回答里 [来源N] 的「编号 → url」映射条目。
 *
 * 后端在来源**首次收集时**分配全局单调递增编号并持久化到助手消息的
 * `context.source_map`；前端渲染正文里的 [来源N] 时按这个映射解析链接，
 * 而不是拿"去重后的参考来源"数组下标去对——那会跳错来源。
 */
export interface AssistantSourceNumber {
  number: number;
  url: string;
}

/** 助手调用过一次工具的记录；写在助手消息的 context 里，供历史回看。 */
export interface AssistantToolCall {
  name: string;
  arguments: Record<string, unknown>;
  summary: string;
  link: string;
  ok: boolean;
  error: string;
  /**
   * 这次调用是否真的改动了用户的数据（后端 `ToolResult.changed`）。
   *
   * 可选是因为它随功能一起加的：更早存下的历史消息里没有这个字段，缺失按"没改动"处理，
   * 不能据此**主动**声称改动过——这类信息只有后端说了才算数。折叠标题里的「改动了 N 项」
   * 就靠它，所以前端不再自己按工具名猜哪些是写操作（猜一份就会与后端漂移）。
   */
  changed?: boolean;
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
    /** [来源N] 的「编号 → url」映射（可选：更早存下的历史消息里没有它）。 */
    source_map?: AssistantSourceNumber[];
    tool_calls?: AssistantToolCall[];
    /**
     * 模型的思考过程（开启思考强度时才有），供用户点开查看。
     *
     * 后端对它有存储上限，超限会截断并把 `reasoning_truncated` 置真——界面据此在
     * 结尾补一句"已截断"，不假装这就是全部。可选：更早存下的历史消息里没有它。
     */
    reasoning?: string;
    /** 上面的思考过程是否因超过存储上限被截断。 */
    reasoning_truncated?: boolean;
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
  | {
      type: "sources";
      sources: AssistantSource[];
      source_map?: AssistantSourceNumber[];
      error: string;
    }
  | ({
      type: "tool";
    } & AssistantToolCall)
  | { type: "delta"; text: string }
  | { type: "reasoning"; text: string }
  | { type: "done"; message: AssistantMessage }
  | { type: "error"; message: string };

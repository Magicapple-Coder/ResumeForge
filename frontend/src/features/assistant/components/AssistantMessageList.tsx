/** 对话消息、流式回复和加载状态展示。 */

import { Alert, Skeleton, Typography } from "antd";
import type { RefObject } from "react";
import type {
  AssistantConversationDetail,
  AssistantSource,
  AssistantToolCall,
} from "../../../types";
import { formatDateTime } from "../../../utils/format";
import AssistantEmptyState from "./AssistantEmptyState";
import {
  AssistantMessageContent,
  MessageAttachments,
  MessageSources,
  MessageToolCalls,
  StreamingStatus,
} from "./AssistantMessageContent";
import type { PendingAttachment } from "../assistantUtils";
import type { StarterPrompt } from "../assistantTypes";

interface Props {
  detail: AssistantConversationDetail | null;
  showLoading: boolean;
  activeStream: boolean;
  sending: boolean;
  pendingUserText: string;
  /** 正在发送的那条消息的发出时刻（服务端时间戳还没有）。 */
  pendingSentAt: string;
  pendingUserAttachments: PendingAttachment[];
  streamingText: string;
  streamingSources: AssistantSource[];
  streamingTools: AssistantToolCall[];
  progressText: string;
  streamError: string;
  messageEndRef: RefObject<HTMLDivElement>;
  enabledSkillCount: number;
  skillsLoaded: boolean;
  onChoosePrompt: (prompt: StarterPrompt) => void;
  onManageSkills: () => void;
}

export default function AssistantMessageList({
  detail,
  showLoading,
  activeStream,
  sending,
  pendingUserText,
  pendingSentAt,
  pendingUserAttachments,
  streamingText,
  streamingSources,
  streamingTools,
  progressText,
  streamError,
  messageEndRef,
  enabledSkillCount,
  skillsLoaded,
  onChoosePrompt,
  onManageSkills,
}: Props) {
  const historyMessages = detail?.messages ?? [];
  return (
    <div className="assistant-messages" aria-live="polite">
      {showLoading ? (
        <Skeleton active paragraph={{ rows: 6 }} />
      ) : historyMessages.length === 0 && !(sending && activeStream) ? (
        <AssistantEmptyState
          onChoosePrompt={onChoosePrompt}
          enabledSkillCount={enabledSkillCount}
          skillsLoaded={skillsLoaded}
          onManageSkills={onManageSkills}
        />
      ) : (
        historyMessages.map((item) => (
          <article key={item.id} className={`assistant-message assistant-message--${item.role}`}>
            <div className="assistant-message-head">
              <Typography.Text strong>{item.role === "user" ? "你" : "求职助手"}</Typography.Text>
              <Typography.Text type="secondary" className="assistant-message-time">
                {formatDateTime(item.created_at)}
              </Typography.Text>
            </div>
            <AssistantMessageContent content={item.content} />
            <MessageAttachments attachments={item.attachments} />
            <MessageSources sources={item.context.sources ?? []} />
            <MessageToolCalls calls={item.context.tool_calls ?? []} />
            {item.status === "error" && item.error && <Alert type="error" message={item.error} />}
          </article>
        ))
      )}
      {activeStream && (pendingUserText || pendingUserAttachments.length > 0) && (
        <article className="assistant-message assistant-message--user">
          <div className="assistant-message-head">
            <Typography.Text strong>你</Typography.Text>
            <Typography.Text type="secondary" className="assistant-message-time">
              {formatDateTime(pendingSentAt)}
            </Typography.Text>
          </div>
          <AssistantMessageContent content={pendingUserText} />
          <MessageAttachments attachments={pendingUserAttachments} />
        </article>
      )}
      {activeStream && sending && (
        <article className="assistant-message assistant-message--assistant">
          <div className="assistant-message-head">
            <Typography.Text strong>求职助手</Typography.Text>
            <Typography.Text type="secondary" className="assistant-message-time">
              {formatDateTime(pendingSentAt)}
            </Typography.Text>
          </div>
          <AssistantMessageContent content={streamingText || progressText || "正在思考…"} />
          <StreamingStatus
            message={streamingText ? "正在生成回答" : progressText || "正在准备回答"}
          />
          <MessageSources sources={streamingSources} />
          <MessageToolCalls calls={streamingTools} />
        </article>
      )}
      {activeStream && streamError && <Alert type="error" showIcon message={streamError} />}
      <div ref={messageEndRef} />
    </div>
  );
}

/** 求职助手消息输入、上下文选择和附件预览。 */

import { PaperClipOutlined, SendOutlined, StopOutlined } from "@ant-design/icons";
import { Alert, Button, Image, Input, Select, Switch, Tag, Tooltip, Upload } from "antd";
import { MAX_ATTACHMENT_COUNT, type PendingAttachment } from "../assistantUtils";

interface Props {
  content: string;
  attachments: PendingAttachment[];
  sending: boolean;
  attachmentReads: number;
  jobId: number | undefined;
  resumeId: number | undefined;
  includeProfile: boolean;
  webSearch: boolean;
  jobOptions: Array<{ value: number; label: string }>;
  resumeOptions: Array<{ value: number; label: string }>;
  onContentChange: (value: string) => void;
  onJobChange: (value: number | undefined) => void;
  onResumeChange: (value: number | undefined) => void;
  onIncludeProfileChange: (value: boolean) => void;
  onWebSearchChange: (value: boolean) => void;
  onAddAttachment: (file: File) => void;
  onRemoveAttachment: (id: number) => void;
  onSend: () => void;
  onStop: () => void;
}

export default function AssistantComposer({
  content,
  attachments,
  sending,
  attachmentReads,
  jobId,
  resumeId,
  includeProfile,
  webSearch,
  jobOptions,
  resumeOptions,
  onContentChange,
  onJobChange,
  onResumeChange,
  onIncludeProfileChange,
  onWebSearchChange,
  onAddAttachment,
  onRemoveAttachment,
  onSend,
  onStop,
}: Props) {
  return (
    <div className="assistant-composer">
      <div className="assistant-context-controls">
        <div className="assistant-context-selects">
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="关联岗位"
            value={jobId}
            options={jobOptions}
            onChange={onJobChange}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="关联简历"
            value={resumeId}
            options={resumeOptions}
            onChange={onResumeChange}
          />
        </div>
      </div>
      {(attachments.length > 0 || includeProfile) && (
        <Alert type="info" showIcon message="已选择的附件或个人资料会发送给当前配置的模型服务" />
      )}
      {attachments.length > 0 && (
        <div className="assistant-composer-attachments">
          {attachments.map((attachment) =>
            attachment.kind === "image" ? (
              <div key={attachment.id} className="assistant-composer-image-item">
                <Image
                  src={attachment.data}
                  alt={attachment.name}
                  className="assistant-message-image"
                />
                <Button
                  type="text"
                  size="small"
                  danger
                  aria-label={`移除附件 ${attachment.name}`}
                  onClick={() => onRemoveAttachment(attachment.id)}
                >
                  移除
                </Button>
              </div>
            ) : (
              <Tag
                key={attachment.id}
                closable={!sending}
                onClose={() => onRemoveAttachment(attachment.id)}
              >
                {attachment.name}
              </Tag>
            ),
          )}
        </div>
      )}
      <Input.TextArea
        value={content}
        autoSize={{ minRows: 3, maxRows: 8 }}
        disabled={sending}
        placeholder="输入求职、岗位、简历或项目经历相关问题"
        onChange={(event) => onContentChange(event.target.value)}
        onPressEnter={(event) => {
          if (!event.shiftKey) {
            event.preventDefault();
            onSend();
          }
        }}
      />
      <div className="assistant-composer-actions">
        <div className="assistant-composer-utility">
          <Upload
            accept=".txt,.md,.json,.csv,image/png,image/jpeg,image/webp,image/gif"
            multiple
            showUploadList={false}
            disabled={sending || attachmentReads > 0 || attachments.length >= MAX_ATTACHMENT_COUNT}
            beforeUpload={(file) => {
              onAddAttachment(file as File);
              return Upload.LIST_IGNORE;
            }}
          >
            <Tooltip title="添加文本或图片附件">
              <Button
                aria-label="添加附件"
                icon={<PaperClipOutlined />}
                loading={attachmentReads > 0}
                disabled={sending || attachmentReads > 0}
              >
                附件
              </Button>
            </Tooltip>
          </Upload>
          <div className="assistant-context-toggles">
            <label className="assistant-context-toggle">
              <Switch size="small" checked={includeProfile} onChange={onIncludeProfileChange} />
              <span>使用我的资料</span>
            </label>
            <label className="assistant-context-toggle">
              <Switch size="small" checked={webSearch} onChange={onWebSearchChange} />
              <span>联网搜索</span>
            </label>
          </div>
        </div>
        {sending ? (
          <Button danger aria-label="停止生成" icon={<StopOutlined />} onClick={onStop}>
            停止
          </Button>
        ) : (
          <Button
            type="primary"
            aria-label="发送消息"
            icon={<SendOutlined />}
            disabled={attachmentReads > 0 || (!content.trim() && attachments.length === 0)}
            onClick={onSend}
          >
            发送
          </Button>
        )}
      </div>
    </div>
  );
}

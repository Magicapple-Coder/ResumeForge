/** 求职助手消息输入、上下文选择、技能开关与附件预览。 */

import {
  CloseOutlined,
  ExperimentOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileWordOutlined,
  PaperClipOutlined,
  SendOutlined,
  StopOutlined,
} from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Dropdown,
  Image,
  Input,
  Select,
  Switch,
  Tag,
  Tooltip,
  Upload,
} from "antd";
import {
  ASSISTANT_ACCEPT,
  MAX_ATTACHMENT_COUNT,
  canPreviewImage,
  type PendingAttachment,
} from "../assistantUtils";
import type { AssistantQuotedMessage, AssistantSkill } from "../../../types";
import { REASONING_EFFORT_OPTIONS, type ReasoningEffort } from "../../../types";
import FileDropZone from "../../../components/common/FileDropZone";

/** 文档按扩展名区分图标：pdf 和 docx 混在一串标签里时，图标比文件名更好认。 */
function attachmentIcon(attachment: PendingAttachment) {
  if (attachment.kind !== "document") return <FileTextOutlined />;
  return attachment.name.toLowerCase().endsWith(".pdf") ? (
    <FilePdfOutlined />
  ) : (
    <FileWordOutlined />
  );
}

interface Props {
  content: string;
  attachments: PendingAttachment[];
  sending: boolean;
  attachmentReads: number;
  jobId: number | undefined;
  resumeId: number | undefined;
  webSearch: boolean;
  reasoningEffort: ReasoningEffort;
  /** 全部技能（含停用的），用于在下拉里直接开关。 */
  skills: AssistantSkill[];
  skillsLoaded: boolean;
  togglingSkillId: number | null;
  jobOptions: Array<{ value: number; label: string }>;
  resumeOptions: Array<{ value: number; label: string }>;
  onContentChange: (value: string) => void;
  onJobChange: (value: number | undefined) => void;
  onResumeChange: (value: number | undefined) => void;
  onWebSearchChange: (value: boolean) => void;
  onReasoningEffortChange: (value: ReasoningEffort) => void;
  onToggleSkill: (skill: AssistantSkill, enabled: boolean) => void;
  onManageSkills: () => void;
  onAddAttachment: (file: File) => void;
  onRemoveAttachment: (id: number) => void;
  /** 当前引用的消息（右键消息「引用这条继续问」后出现）。 */
  quoted: AssistantQuotedMessage | null;
  onClearQuote: () => void;
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
  webSearch,
  reasoningEffort,
  skills,
  skillsLoaded,
  togglingSkillId,
  jobOptions,
  resumeOptions,
  onContentChange,
  onJobChange,
  onResumeChange,
  onWebSearchChange,
  onReasoningEffortChange,
  onToggleSkill,
  onManageSkills,
  onAddAttachment,
  onRemoveAttachment,
  quoted,
  onClearQuote,
  onSend,
  onStop,
}: Props) {
  const { message } = App.useApp();
  const enabledSkills = skills.filter((skill) => skill.enabled);

  return (
    <FileDropZone
      accept={ASSISTANT_ACCEPT}
      disabled={sending || attachmentReads > 0 || attachments.length >= MAX_ATTACHMENT_COUNT}
      hint="松开即可把文件加进对话"
      onFiles={(dropped) => dropped.forEach((file) => onAddAttachment(file))}
      onRejected={(count) => message.warning(`已忽略 ${count} 个不支持的附件`)}
    >
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
        {quoted ? (
          <div className="assistant-quote-chip">
            <span className="assistant-quote-chip-label">
              引用{quoted.role === "user" ? "你的消息" : "助手的回复"}
            </span>
            <span className="assistant-quote-chip-text">{quoted.excerpt}</span>
            <Button
              type="text"
              size="small"
              aria-label="取消引用"
              className="assistant-quote-chip-close"
              icon={<CloseOutlined />}
              onClick={onClearQuote}
            />
          </div>
        ) : null}
        {attachments.length > 0 && (
          <Alert type="info" showIcon message="已选择的附件或个人资料会发送给当前配置的模型服务" />
        )}
        {attachments.length > 0 && (
          <div className="assistant-composer-attachments">
            {attachments.map((attachment) =>
              attachment.kind === "image" && canPreviewImage(attachment.mime_type) ? (
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
                // 文件名没有长度上限，标签又不换行；截断但把全名放进悬停提示。
                <Tooltip key={attachment.id} title={attachment.name}>
                  <Tag
                    className="assistant-attachment-tag"
                    icon={attachmentIcon(attachment)}
                    closable={!sending}
                    onClose={() => onRemoveAttachment(attachment.id)}
                  >
                    {attachment.name}
                  </Tag>
                </Tooltip>
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
              accept={ASSISTANT_ACCEPT}
              multiple
              showUploadList={false}
              disabled={
                sending || attachmentReads > 0 || attachments.length >= MAX_ATTACHMENT_COUNT
              }
              beforeUpload={(file) => {
                onAddAttachment(file as File);
                return Upload.LIST_IGNORE;
              }}
            >
              <Tooltip title="添加文本、图片或文档附件">
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
            <Dropdown
              trigger={["click"]}
              placement="topLeft"
              menu={{
                // 用真实的 Checkbox 表达"已启用"：菜单自带的高亮在浅色主题下几乎看不出来，
                // 用户会以为点击没生效。这里每项左侧都是可勾选的方框，点整行即切换。
                items: [
                  {
                    key: "hint",
                    label: <span className="assistant-skill-menu-hint">勾选要启用的技能</span>,
                    disabled: true,
                  },
                  { type: "divider" as const },
                  ...skills.map((skill) => ({
                    key: String(skill.id),
                    label: (
                      <span className="assistant-skill-option">
                        <Checkbox checked={skill.enabled} disabled={togglingSkillId === skill.id} />
                        <span className="assistant-skill-option-text">
                          <span className="assistant-skill-option-name">{skill.name}</span>
                          {skill.description ? (
                            <span className="assistant-skill-option-desc">{skill.description}</span>
                          ) : null}
                        </span>
                      </span>
                    ),
                    disabled: togglingSkillId === skill.id,
                  })),
                  { type: "divider" as const },
                  { key: "manage", label: "打开工作台" },
                ],
                onClick: ({ key }) => {
                  if (key === "manage") {
                    onManageSkills();
                    return;
                  }
                  const skill = skills.find((item) => String(item.id) === key);
                  if (skill) onToggleSkill(skill, !skill.enabled);
                },
              }}
              disabled={sending}
            >
              <Tooltip title="点击开关助手技能；勾选表示已启用">
                <Button
                  aria-label="技能"
                  icon={<ExperimentOutlined />}
                  loading={!skillsLoaded}
                  disabled={sending}
                >
                  技能{enabledSkills.length > 0 ? `（${enabledSkills.length}）` : ""}
                </Button>
              </Tooltip>
            </Dropdown>
            <div className="assistant-context-toggles">
              <label className="assistant-context-toggle">
                <Switch size="small" checked={webSearch} onChange={onWebSearchChange} />
                <span>联网搜索</span>
              </label>
              {/* 带文字标签：只放一个「默认」下拉，用户看不出这是在调什么（截图反馈）。 */}
              <Tooltip title="有思考模式的大模型可以在这里调推理强度；不支持该参数的服务商会忽略它">
                <span className="assistant-reasoning-control">
                  <span className="assistant-reasoning-label">思考强度</span>
                  <Select
                    size="small"
                    className="assistant-reasoning-select"
                    value={reasoningEffort}
                    options={REASONING_EFFORT_OPTIONS}
                    disabled={sending}
                    onChange={onReasoningEffortChange}
                    aria-label="思考强度"
                  />
                </span>
              </Tooltip>
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
    </FileDropZone>
  );
}

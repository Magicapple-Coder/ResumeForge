/** 助手消息的安全 Markdown 子集、附件和来源展示。 */

import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  ExportOutlined,
  FilePdfOutlined,
  FileTextOutlined,
  FileWordOutlined,
  PushpinFilled,
  StarFilled,
} from "@ant-design/icons";
import { Collapse, Image, Tag, Tooltip, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type {
  AssistantAttachment,
  AssistantSource,
  AssistantSourceNumber,
  AssistantToolCall,
} from "../../../types";
import {
  attachmentStyle,
  canPreviewImage,
  isMarkdownTableDivider,
  parseMarkdownTableRow,
  renderInlineMarkdown,
} from "../assistantUtils";

/** 文档按扩展名区分图标：pdf 和 docx 混在一串标签里时，图标比文件名更好认。 */
function attachmentIcon(name: string, kind: string) {
  if (kind !== "document") return <FileTextOutlined />;
  return name.toLowerCase().endsWith(".pdf") ? <FilePdfOutlined /> : <FileWordOutlined />;
}

export function AssistantMessageContent({
  content,
  sourceMap,
}: {
  content: string;
  /** [来源N] 的「编号 → url」映射；缺省时正文里的 [来源N] 保持纯文本。 */
  sourceMap?: AssistantSourceNumber[];
}) {
  const lines = content.split(/\r?\n/);
  const blocks: ReactNode[] = [];

  for (let index = 0; index < lines.length; index += 1) {
    const tableHeader = parseMarkdownTableRow(lines[index]);
    if (tableHeader && isMarkdownTableDivider(lines[index + 1] ?? "", tableHeader.length)) {
      const rows: string[][] = [];
      let nextIndex = index + 2;
      while (nextIndex < lines.length) {
        const row = parseMarkdownTableRow(lines[nextIndex]);
        if (!row || row.length !== tableHeader.length) break;
        rows.push(row);
        nextIndex += 1;
      }
      blocks.push(
        <div key={`table-${index}`} className="assistant-markdown-table-wrap" tabIndex={0}>
          <table>
            <thead>
              <tr>
                {tableHeader.map((cell, cellIndex) => (
                  <th key={`header-${cellIndex}`}>{renderInlineMarkdown(cell, sourceMap)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={`row-${rowIndex}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`cell-${rowIndex}-${cellIndex}`}>
                      {renderInlineMarkdown(cell, sourceMap)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      index = nextIndex - 1;
      continue;
    }

    const line = lines[index];
    const heading = line.match(/^#{1,3}\s+(.+)$/);
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/);
    const ordered = line.match(/^\s*(\d+)[.)]\s+(.+)$/);
    if (heading) {
      blocks.push(<h4 key={`heading-${index}`}>{renderInlineMarkdown(heading[1], sourceMap)}</h4>);
      continue;
    }
    if (bullet || ordered) {
      blocks.push(
        <div key={`list-${index}`} className="assistant-markdown-list-item">
          <span aria-hidden="true">{ordered ? `${ordered[1]}.` : "•"}</span>
          <div>{renderInlineMarkdown(bullet?.[1] ?? ordered?.[2] ?? "", sourceMap)}</div>
        </div>,
      );
      continue;
    }
    if (!line.trim()) {
      blocks.push(<div key={`space-${index}`} className="assistant-markdown-spacer" />);
      continue;
    }
    blocks.push(<p key={`paragraph-${index}`}>{renderInlineMarkdown(line, sourceMap)}</p>);
  }

  return <div className="assistant-message-content assistant-message-content--rich">{blocks}</div>;
}

export function StreamingStatus({ message }: { message: string }) {
  return (
    <div className="assistant-streaming-status" role="status">
      <span className="assistant-streaming-dot" aria-hidden="true" />
      <span>{message}</span>
      <span className="assistant-streaming-ellipsis" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </div>
  );
}

export function ConversationTitle({
  title,
  pinned,
  favorite,
  onSelect,
}: {
  title: string;
  pinned: boolean;
  favorite: boolean;
  onSelect: () => void;
}) {
  const titleRef = useRef<HTMLSpanElement>(null);
  const [overflowDistance, setOverflowDistance] = useState(0);

  useEffect(() => {
    const element = titleRef.current;
    if (!element) return;

    const updateOverflowDistance = () => {
      const nextDistance = Math.max(0, element.scrollWidth - element.clientWidth);
      setOverflowDistance((current) => (current === nextDistance ? current : nextDistance));
    };
    updateOverflowDistance();

    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(updateOverflowDistance);
    observer?.observe(element);
    window.addEventListener("resize", updateOverflowDistance);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", updateOverflowDistance);
    };
  }, [title]);

  return (
    <Tooltip title={title} placement="right">
      <button
        type="button"
        className="assistant-conversation-button"
        aria-label={title}
        onClick={onSelect}
      >
        {(pinned || favorite) && (
          <span className="assistant-conversation-flags" aria-hidden="true">
            {pinned && <PushpinFilled />}
            {favorite && <StarFilled />}
          </span>
        )}
        <span
          ref={titleRef}
          className={
            overflowDistance > 0
              ? "assistant-conversation-title is-overflowing"
              : "assistant-conversation-title"
          }
          style={attachmentStyle(overflowDistance)}
        >
          <span>{title}</span>
        </span>
      </button>
    </Tooltip>
  );
}

export function MessageAttachments({
  attachments,
}: {
  attachments: Array<
    AssistantAttachment | { name: string; kind: "text" | "image" | "document"; data: string }
  >;
}) {
  if (!attachments.length) return null;
  const notes = attachments.flatMap((attachment) =>
    "notes" in attachment ? attachment.notes : [],
  );
  return (
    <div className="assistant-message-attachments">
      {attachments.map((attachment, index) => {
        const dataUrl = "data_url" in attachment ? attachment.data_url : attachment.data;
        const mimeType = "mime_type" in attachment ? attachment.mime_type : "";
        if (attachment.kind === "image" && dataUrl && canPreviewImage(mimeType)) {
          return (
            <Image
              key={`${attachment.name}-${index}`}
              src={dataUrl}
              alt={attachment.name}
              className="assistant-message-image"
            />
          );
        }
        return (
          // 文件名是用户给的，长度没有上限；标签本身不换行，不截断就会顶出气泡。
          <Tooltip key={`${attachment.name}-${index}`} title={attachment.name}>
            <Tag
              className="assistant-attachment-tag"
              icon={attachmentIcon(attachment.name, attachment.kind)}
            >
              {attachment.name}
            </Tag>
          </Tooltip>
        );
      })}
      {notes.length > 0 && <span className="assistant-attachment-notes">{notes.join("；")}</span>}
    </div>
  );
}

/**
 * 工具名的中文说法；没列到的直接显示原名。
 *
 * 必须覆盖后端注册的**全部**工具：漏掉的那些会在"助手做了什么"这一行里露出
 * `import_candidate_job` 这样的内部名字，而这一行正是用户用来确认助手改动了什么的地方。
 * 后端新增工具时这里要一起补（`services/assistant_tools.py` 的 `_TOOLS`）。
 */
const TOOL_LABELS: Record<string, string> = {
  get_overview: "查看整体概览",
  list_jobs: "查询岗位",
  get_job: "查看岗位详情",
  list_resumes: "查询简历",
  get_resume: "查看简历详情",
  get_profile: "查看个人资料",
  create_job: "新增岗位",
  update_job: "修改岗位",
  update_profile: "更新个人资料",
  add_profile_entry: "往资料里加一条经历",
  // 资料箱
  list_materials: "查询资料箱",
  get_material: "查看资料详情",
  create_material: "新增资料",
  update_material: "修改资料",
  // 事实台账
  list_claims: "查询事实台账",
  get_claim: "查看台账条目",
  create_claim: "新增台账条目",
  update_claim: "修改台账条目",
  // 备选岗位
  list_candidate_jobs: "查询备选岗位",
  get_candidate_job: "查看备选岗位详情",
  create_candidate_job: "新增备选岗位",
  update_candidate_job: "修改备选岗位",
  import_candidate_job: "把备选岗位导入岗位广场",
  // 面试深挖
  list_drill_sessions: "查询面试深挖记录",
  get_drill_report: "查看深挖复盘",
  // 模拟面试
  list_interview_sessions: "查询模拟面试",
  get_interview_report: "查看面试记录与报告",
  // 技能
  list_skills: "查询助手技能",
  get_skill: "查看技能详情",
  create_skill: "新建助手技能",
  update_skill: "修改助手技能",
  read_skill_knowledge: "查阅技能知识文件",
  // 简历版式与联网
  update_resume_layout: "调整简历版式",
  create_format_template: "新建格式模板",
  update_format_template: "修改格式模板",
  web_search: "联网搜索",
  // 提醒 / 内推 / 面经 / 题库 / 复盘 / 知识库 / 统计 / 分享包（知识审计补齐）
  list_reminders: "查询提醒",
  list_referrals: "查询内推",
  list_interview_experiences: "查询面经",
  list_question_banks: "查询题库历史",
  list_reviews: "查询复盘历史",
  list_knowledge: "查询知识库",
  get_knowledge: "查看知识条目",
  create_knowledge: "新增知识条目",
  update_knowledge: "修改知识条目",
  get_analytics_overview: "查看求职统计",
  list_share_packages: "查询分享包",
  create_reminder: "新增提醒",
};

export function MessageToolCalls({ calls }: { calls: AssistantToolCall[] }) {
  if (!calls.length) return null;
  // 这里原来刻意**不折叠**，理由是"助手动了用户的数据，这件事必须一眼可见"。用户反馈
  // 这串记录每回答一次就铺开一整列、太吵，所以改成默认折叠的折叠面板；但**原来的意图
  // 用折叠标题承接下来**：标题永远可见，且直接写明「改动了 N 项」「N 项失败」——不展开
  // 也能一眼看出它动没动数据、有没有出错，只是把逐条明细挪到展开之后。这样既安静，
  // 又没有把"它改了我的数据"藏进折叠里。
  const changedCount = calls.filter((call) => call.changed).length;
  const failedCount = calls.filter((call) => !call.ok).length;
  return (
    <Collapse
      className="assistant-tool-calls"
      size="small"
      items={[
        {
          key: "tool-calls",
          label: (
            <span className="assistant-tool-calls-label">
              {`助手做了什么（${calls.length}）`}
              {changedCount > 0 && (
                <Typography.Text type="warning" className="assistant-tool-calls-flag">
                  · 改动了 {changedCount} 项
                </Typography.Text>
              )}
              {failedCount > 0 && (
                <Typography.Text type="danger" className="assistant-tool-calls-flag">
                  · {failedCount} 项失败
                </Typography.Text>
              )}
            </span>
          ),
          children: (
            <ul>
              {calls.map((call, index) => (
                <li key={`${call.name}-${index}`}>
                  {call.ok ? <CheckCircleOutlined /> : <CloseCircleOutlined />}
                  <Typography.Text strong style={{ marginLeft: 6 }}>
                    {TOOL_LABELS[call.name] ?? call.name}
                  </Typography.Text>
                  {call.ok ? (
                    <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                      {call.summary}
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="danger" style={{ marginLeft: 8 }}>
                      失败：{call.error}
                    </Typography.Text>
                  )}
                  {call.ok && call.link && (
                    // 用 href 而不是 router Link：这个组件也会被单独渲染在测试里。
                    <Typography.Link href={call.link} style={{ marginLeft: 8 }}>
                      前往查看
                    </Typography.Link>
                  )}
                </li>
              ))}
            </ul>
          ),
        },
      ]}
    />
  );
}

/**
 * 模型的思考过程；开启思考强度后才有内容。
 *
 * 照抄 `MessageSources` 的折叠面板模式：**默认折叠**（不传 `defaultActiveKey`），
 * 标题「思考过程」，用户点开即可查看。**没有内容时整块不渲染**——这是安全降级：
 * 不开思考、或更早存下的历史消息里没有 `reasoning` 字段时，界面与加这个功能之前
 * 完全一致，不会凭空多出一个空面板。
 *
 * 无障碍：折叠头由 antd 渲染成可聚焦的 `role="button"`，本身支持回车/空格开关；
 * 这里额外挂 `aria-label` 固定名称、并用 `data-testid` 提供给测试，避免依赖会被
 * antd 自动插入空格的中文可见文本（两字中文标签会被拆开，按文本查询会找不到）。
 */
export function MessageReasoning({
  reasoning,
  truncated = false,
}: {
  reasoning?: string;
  truncated?: boolean;
}) {
  if (!reasoning || !reasoning.trim()) return null;
  return (
    <Collapse
      className="assistant-reasoning"
      size="small"
      data-testid="message-reasoning"
      items={[
        {
          key: "reasoning",
          label: (
            <span className="assistant-reasoning-label" aria-label="思考过程">
              思考过程
            </span>
          ),
          children: (
            <div className="assistant-reasoning-body">
              <div className="assistant-reasoning-text" style={{ whiteSpace: "pre-wrap" }}>
                {reasoning}
              </div>
              {truncated && (
                <Typography.Text type="secondary" className="assistant-reasoning-truncated">
                  思考过程过长，这里只保留了前一部分。
                </Typography.Text>
              )}
            </div>
          ),
        },
      ]}
    />
  );
}

export function MessageSources({ sources }: { sources: AssistantSource[] }) {
  if (!sources.length) return null;
  return (
    <Collapse
      className="assistant-sources"
      size="small"
      items={[
        {
          key: "sources",
          label: `参考来源（${sources.length}）`,
          children: (
            <ol>
              {sources.map((source) => (
                <li key={source.url}>
                  <Typography.Link
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="assistant-source-title"
                  >
                    {source.title || source.url}
                    {/* 标题默认就是一段普通文字，用户不会想到能点。外链图标把"可跳转"摆在
                        明面上；aria-hidden 是因为图标自带 aria-label（"export"），不隐藏
                        会并进链接的无障碍名称，读屏时在"招聘官网"后面念一句"export"没意义。 */}
                    <ExportOutlined aria-hidden className="assistant-source-icon" />
                  </Typography.Link>
                  {source.snippet && (
                    <Typography.Text type="secondary">{source.snippet}</Typography.Text>
                  )}
                </li>
              ))}
            </ol>
          ),
        },
      ]}
    />
  );
}

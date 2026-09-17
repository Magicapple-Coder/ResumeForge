/**
 * 一条台账条目的只读展示。
 *
 * 排版上刻意把「原始事实」和「简历表述」并排：这两行放在一起，用户一眼就能看出措辞
 * 有没有比事实更强——这正是这个功能要防的事。占位符单独高亮，因为它同时意味着
 * "这条还没核实"和"导出终稿会被拦下"。
 */
import { Button, Popconfirm, Space, Tag, Tooltip, Typography } from "antd";
import type { Claim, VerificationStatus } from "../../types";
import { SOURCE_TYPE_LABELS, hasPlaceholder } from "../../types";

const STATUS_COLORS: Record<VerificationStatus, string> = {
  已确认: "green",
  待确认: "gold",
  已过期: "volcano",
  不采用: "default",
};

const RESPONSIBILITY_COLORS: Record<string, string> = {
  参与: "default",
  负责模块: "blue",
  主导方案或交付: "purple",
  项目负责人: "magenta",
};

interface Props {
  claim: Claim;
  onEdit: () => void;
  onDelete: () => void;
  onConfirm: () => void;
}

/** 把含占位符的文本切出来单独高亮，让"哪里还没写"一眼可见。 */
function Wording({ text }: { text: string }) {
  if (!text) return <Typography.Text type="secondary">（未填写）</Typography.Text>;
  if (!hasPlaceholder(text)) return <span>{text}</span>;
  const parts = text.split(/(【[^】]*】)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.startsWith("【") ? (
          <mark key={index} className="claim-placeholder">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

export default function ClaimCard({ claim, onEdit, onDelete, onConfirm }: Props) {
  const interview = claim.interview_details;
  const hasInterviewDetail =
    Boolean(interview?.result) ||
    (interview?.decisions?.length ?? 0) > 0 ||
    (interview?.difficulties?.length ?? 0) > 0 ||
    (interview?.verification?.length ?? 0) > 0;

  return (
    <article className="claim-card">
      <header className="claim-card-head">
        <Space size={6} wrap>
          <Typography.Text strong>
            {claim.title || claim.subject || `条目 ${claim.id}`}
          </Typography.Text>
          <Tag>{claim.category}</Tag>
          <Tag color={RESPONSIBILITY_COLORS[claim.responsibility_level] ?? "default"}>
            {claim.responsibility_level}
          </Tag>
          <Tag color={STATUS_COLORS[claim.verification_status] ?? "default"}>
            {claim.verification_status}
          </Tag>
          {claim.last_verified && (
            <Typography.Text type="secondary" className="claim-card-verified">
              最近核实 {claim.last_verified}
            </Typography.Text>
          )}
        </Space>
        <Space size={4}>
          {claim.verification_status !== "已确认" && (
            <Tooltip title="确认后这条才会作为事实进入简历生成">
              <Button size="small" type="link" onClick={onConfirm}>
                标记已确认
              </Button>
            </Tooltip>
          )}
          <Button size="small" type="link" onClick={onEdit}>
            编辑
          </Button>
          <Popconfirm
            title="删除这条台账记录？"
            okText="删除"
            cancelText="取消"
            onConfirm={onDelete}
          >
            <Button size="small" type="link" danger>
              删除
            </Button>
          </Popconfirm>
        </Space>
      </header>

      <div className="claim-card-body">
        <div className="claim-card-row">
          <span className="claim-card-label">原始事实</span>
          <div className="claim-card-value">
            <Wording text={claim.source_fact} />
          </div>
        </div>
        <div className="claim-card-row">
          <span className="claim-card-label">简历表述</span>
          <div className="claim-card-value">
            <Wording text={claim.candidate_wording} />
          </div>
        </div>
        {claim.boundary && (
          <div className="claim-card-row">
            <span className="claim-card-label">个人边界</span>
            <div className="claim-card-value">{claim.boundary}</div>
          </div>
        )}
      </div>

      {(claim.sources.length > 0 || claim.allowed_uses.length > 0 || hasInterviewDetail) && (
        <footer className="claim-card-foot">
          {claim.sources.length > 0 && (
            <Space size={4} wrap>
              <span className="claim-card-label">证据</span>
              {claim.sources.map((source, index) => (
                <Tooltip
                  key={index}
                  title={`${source.location}${source.public ? "" : "（不公开）"}`}
                >
                  <Tag>{SOURCE_TYPE_LABELS[source.type] ?? source.type}</Tag>
                </Tooltip>
              ))}
            </Space>
          )}
          {claim.allowed_uses.length > 0 && (
            <Space size={4} wrap>
              <span className="claim-card-label">可用范围</span>
              {claim.allowed_uses.map((use) => (
                <Tag key={use}>{use}</Tag>
              ))}
            </Space>
          )}
          {hasInterviewDetail && (
            <Typography.Text type="secondary" className="claim-card-interview">
              已备面试细节（决策 / 难点 / 验证 / 结果）
            </Typography.Text>
          )}
        </footer>
      )}

      {/*
        建议只在这里渲染一次：规则本身全部由后端 claim_warnings() 算出并随条目下发。
        前端再判一遍"强主张缺面试细节"之类的规则，同一条提示就会显示两遍，
        而且两处的措辞迟早会漂移。
      */}
      {claim.warnings.length > 0 && (
        <ul className="claim-card-warnings">
          {claim.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}
    </article>
  );
}

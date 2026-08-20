/** 手写简历时使用的岗位参考面板：只展示岗位快照，不参与简历保存。 */
import {
  CheckCircleOutlined,
  FileTextOutlined,
  InfoCircleOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Descriptions, Typography } from "antd";
import type { ReactNode } from "react";
import type { Job } from "../types";
import SkillTags from "./SkillTags";

interface Props {
  job: Pick<
    Job,
    | "title"
    | "company"
    | "location"
    | "salary"
    | "job_type"
    | "description"
    | "requirements"
    | "keywords"
  > & {
    // 兼容正在迁移的旧前端类型；后端缺少该字段时按空内容展示。
    additional_info?: string;
  };
}

interface ReferenceSectionProps {
  title: string;
  icon: ReactNode;
  content: string;
  emptyText: string;
}

function ReferenceSection({ title, icon, content, emptyText }: ReferenceSectionProps) {
  return (
    <section className="job-reference-section">
      <div className="job-reference-section-heading">
        <span className="job-reference-section-icon" aria-hidden="true">
          {icon}
        </span>
        <Typography.Text strong>{title}</Typography.Text>
      </div>
      <Typography.Paragraph
        className="job-reference-section-content"
        type={content ? undefined : "secondary"}
      >
        {content || emptyText}
      </Typography.Paragraph>
    </section>
  );
}

export default function JobRequirementPanel({ job }: Props) {
  return (
    <aside className="job-reference-panel" aria-label={`岗位要求参考：${job.title}`}>
      <div className="job-reference-header">
        <Typography.Text className="job-reference-eyebrow">岗位要求参考</Typography.Text>
        <Typography.Title level={5} className="job-reference-title">
          {job.title}
        </Typography.Title>
        {job.company && <Typography.Text type="secondary">{job.company}</Typography.Text>}
      </div>

      {(job.location || job.job_type || job.salary) && (
        <Descriptions className="job-reference-meta" size="small" column={1} colon={false}>
          {job.location && <Descriptions.Item label="地点">{job.location}</Descriptions.Item>}
          {job.job_type && <Descriptions.Item label="类型">{job.job_type}</Descriptions.Item>}
          {job.salary && <Descriptions.Item label="薪资">{job.salary}</Descriptions.Item>}
        </Descriptions>
      )}

      <ReferenceSection
        title="岗位职责"
        icon={<FileTextOutlined />}
        content={job.description}
        emptyText="暂无岗位职责"
      />
      <ReferenceSection
        title="任职要求"
        icon={<CheckCircleOutlined />}
        content={job.requirements}
        emptyText="暂无任职要求"
      />

      <section className="job-reference-section">
        <div className="job-reference-section-heading">
          <span className="job-reference-section-icon" aria-hidden="true">
            <TagsOutlined />
          </span>
          <Typography.Text strong>技能标签</Typography.Text>
        </div>
        {job.keywords.length > 0 ? (
          <SkillTags tags={job.keywords} max={20} />
        ) : (
          <Typography.Text type="secondary">暂无技能标签</Typography.Text>
        )}
      </section>

      <ReferenceSection
        title="其他信息"
        icon={<InfoCircleOutlined />}
        content={job.additional_info ?? ""}
        emptyText="暂无其他信息"
      />
    </aside>
  );
}

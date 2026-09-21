/** 岗位详情抽屉：JD 全文、技能标签、投递链接与操作入口。 */
import {
  BulbOutlined,
  CheckCircleOutlined,
  EditOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  InfoCircleOutlined,
  LinkOutlined,
  MessageOutlined,
  PictureOutlined,
  PushpinOutlined,
  RobotOutlined,
  SendOutlined,
  StarFilled,
  StarOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Descriptions,
  Divider,
  Drawer,
  Image,
  Space,
  Tooltip,
  Typography,
} from "antd";
import type { ReactNode } from "react";
import type { Job } from "../types";
import SkillTags from "./SkillTags";

interface Props {
  job: Job | null;
  onClose: () => void;
  onGenerate: (job: Job) => void;
  onWrite: (job: Job) => void;
  onViewResumes: (job: Job) => void;
  onAnalyze: (job: Job) => void;
  onMatch: (job: Job) => void;
  onAddToQueue: (job: Job) => void;
  onAskAssistant: (job: Job) => void;
  onFavorite: (job: Job) => void;
  favoriteLoading?: boolean;
  queueLoading?: boolean;
}

interface TextSectionProps {
  title: string;
  icon: ReactNode;
  content: string;
  emptyText: string;
  variant: "description" | "requirements" | "additional" | "note";
}

function TextSection({ title, icon, content, emptyText, variant }: TextSectionProps) {
  return (
    <section className={`job-detail-text-section job-detail-text-section--${variant}`}>
      <div className="job-detail-section-heading">
        <span className="job-detail-section-icon">{icon}</span>
        <Typography.Text strong>{title}</Typography.Text>
      </div>
      <Typography.Paragraph type={content ? undefined : "secondary"} className="job-detail-text">
        {content || emptyText}
      </Typography.Paragraph>
    </section>
  );
}

export default function JobDetailDrawer({
  job,
  onClose,
  onGenerate,
  onWrite,
  onViewResumes,
  onAnalyze,
  onMatch,
  onAddToQueue,
  onAskAssistant,
  onFavorite,
  favoriteLoading = false,
  queueLoading = false,
}: Props) {
  return (
    <Drawer
      title="岗位详情"
      width="min(640px, 100vw)"
      open={!!job}
      onClose={onClose}
      // 操作栏交给抽屉的 footer 插槽：它由抽屉布局常驻底部，内容不足一屏时
      // 也不会浮在正文中间；正文仍由 body 独立滚动。
      styles={{ footer: { padding: "12px 24px" } }}
      footer={
        job && (
          <Space className="job-detail-actions" wrap>
            <Button type="primary" icon={<FileTextOutlined />} onClick={() => onGenerate(job)}>
              用 AI 生成简历
            </Button>
            <Button icon={<EditOutlined />} onClick={() => onWrite(job)}>
              自行编写简历
            </Button>
            <Button icon={<FolderOpenOutlined />} onClick={() => onViewResumes(job)}>
              查看生成的简历
            </Button>
            {/* 两个"解读"性质不同，按钮相邻但用 Tooltip 讲清区别：需求解读只读 JD，
                匹配分析会读取你的资料与简历。 */}
            <Tooltip title="只读招聘原文，总结岗位要什么">
              <Button icon={<BulbOutlined />} onClick={() => onAnalyze(job)}>
                岗位需求解读
              </Button>
            </Tooltip>
            <Tooltip title="读取你的资料与简历，判断你够不够">
              <Button icon={<RobotOutlined />} onClick={() => onMatch(job)}>
                匹配度分析
              </Button>
            </Tooltip>
            <Tooltip
              title={
                job.apply_supported === false
                  ? "这个岗位的来源不在投递台支持的招聘网站内，无法自动投递"
                  : "加入投递台队列；命中真实缺口或未分析时会先请你确认"
              }
            >
              <Button
                icon={<SendOutlined />}
                loading={queueLoading}
                disabled={queueLoading || job.apply_supported === false}
                onClick={() => onAddToQueue(job)}
              >
                加入投递台
              </Button>
            </Tooltip>
            <Button icon={<MessageOutlined />} onClick={() => onAskAssistant(job)}>
              咨询求职助手
            </Button>
            {job.source_url && (
              <Button
                icon={<LinkOutlined />}
                href={job.source_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                前往投递
              </Button>
            )}
          </Space>
        )
      }
    >
      {job && (
        <>
          <div className="job-detail-title-row">
            <Typography.Title level={4} style={{ margin: 0 }}>
              {job.title}
            </Typography.Title>
            <Tooltip title={job.favorite ? "取消收藏" : "收藏岗位"}>
              <Button
                type="text"
                aria-label={job.favorite ? "取消收藏" : "收藏岗位"}
                className={`job-favorite-button${job.favorite ? " is-favorite" : ""}`}
                icon={job.favorite ? <StarFilled /> : <StarOutlined />}
                loading={favoriteLoading}
                disabled={favoriteLoading}
                onClick={() => onFavorite(job)}
              />
            </Tooltip>
          </div>

          {/* 把原因写在页面上而不是只禁用按钮：用户是"手动录了一个岗位"，看到灰按钮会以为是 bug。 */}
          {job.apply_supported === false && (
            <Alert
              type="info"
              showIcon
              style={{ marginTop: 12 }}
              message="这个岗位不能用投递台自动投递"
              description={
                <Typography.Text type="secondary">
                  投递台只能自动投递<Typography.Text strong>招聘网站上的岗位</Typography.Text>
                  ——它的来源或「投递链接」必须指向某个已支持的站点。这个岗位两者都指不到，所以
                  「加入投递台」是灰的。要么把它的「投递链接」改成该岗位在招聘网站上的地址（改完即可
                  自动投递），要么直接在上面「前往投递」或到原渠道自行投递。
                </Typography.Text>
              }
            />
          )}

          <Descriptions column={2} size="small" style={{ marginTop: 16, marginBottom: 16 }}>
            <Descriptions.Item label="公司">{job.company || "-"}</Descriptions.Item>
            <Descriptions.Item label="工作地点">{job.location || "-"}</Descriptions.Item>
            <Descriptions.Item label="薪资范围">{job.salary || "-"}</Descriptions.Item>
            <Descriptions.Item label="岗位类型">{job.job_type || "-"}</Descriptions.Item>
            <Descriptions.Item label="状态">{job.status || "-"}</Descriptions.Item>
            <Descriptions.Item label="发布时间">{job.posted_at || "-"}</Descriptions.Item>
            <Descriptions.Item label="信息来源">
              {job.recognition_source || "未记录"}
            </Descriptions.Item>
          </Descriptions>

          {job.keywords.length > 0 && (
            <>
              <Divider orientation="left" plain style={{ margin: "8px 0" }}>
                岗位技能标签
              </Divider>
              <SkillTags tags={job.keywords} max={20} />
            </>
          )}

          <div className="job-detail-text-sections">
            <TextSection
              title="职位描述"
              icon={<FileTextOutlined />}
              content={job.description}
              emptyText="暂无职位描述"
              variant="description"
            />
            <TextSection
              title="任职要求"
              icon={<CheckCircleOutlined />}
              content={job.requirements}
              emptyText="暂无任职要求"
              variant="requirements"
            />
            <TextSection
              title="其他招聘信息"
              icon={<InfoCircleOutlined />}
              content={job.additional_info}
              emptyText="暂无其他招聘信息"
              variant="additional"
            />
            <TextSection
              title="备注"
              icon={<PushpinOutlined />}
              content={job.note}
              emptyText="暂无备注"
              variant="note"
            />
            {(job.note_images?.length ?? 0) > 0 && (
              <section className="job-detail-text-section job-detail-text-section--note">
                <div className="job-detail-section-heading">
                  <span className="job-detail-section-icon">
                    <PictureOutlined />
                  </span>
                  <Typography.Text strong>备注图片</Typography.Text>
                </div>
                <Space wrap>
                  {job.note_images.map((source, index) => (
                    <Image
                      key={`${index}-${source.slice(-16)}`}
                      src={source}
                      alt={`备注图片 ${index + 1}`}
                      width={150}
                    />
                  ))}
                </Space>
              </section>
            )}
          </div>
        </>
      )}
    </Drawer>
  );
}

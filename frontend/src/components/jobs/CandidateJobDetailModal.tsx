import { LinkOutlined } from "@ant-design/icons";
import { Button, Descriptions, Divider, Image, Modal, Space, Tag, Typography } from "antd";
import type { CandidateJobDetail } from "../../types";

interface Props {
  candidate: CandidateJobDetail | null;
  loading: boolean;
  onClose: () => void;
  onImport: (candidate: CandidateJobDetail) => void;
  onEdit: (candidate: CandidateJobDetail) => void;
}

/** 备选岗位的详情：卡片只放摘要，正文在这里按需读取，避免列表随着 JD 变大。 */
export default function CandidateJobDetailModal({
  candidate,
  loading,
  onClose,
  onImport,
  onEdit,
}: Props) {
  return (
    <Modal
      title={candidate?.title || "备选岗位详情"}
      open={candidate !== null || loading}
      confirmLoading={loading}
      onCancel={onClose}
      footer={
        candidate ? (
          <Space>
            <Button onClick={() => onEdit(candidate)}>编辑</Button>
            {candidate.status === "pending" && (
              <Button type="primary" onClick={() => onImport(candidate)}>
                导入到岗位
              </Button>
            )}
          </Space>
        ) : null
      }
      width={760}
    >
      {candidate && (
        <Space direction="vertical" size="middle" style={{ width: "100%" }}>
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="公司">{candidate.company || "未识别公司"}</Descriptions.Item>
            <Descriptions.Item label="地点">{candidate.location || "-"}</Descriptions.Item>
            <Descriptions.Item label="薪资">{candidate.salary || "-"}</Descriptions.Item>
            <Descriptions.Item label="来源">
              <Space>
                <Tag>{candidate.source || "未知来源"}</Tag>
                {candidate.status === "imported" ? (
                  <Tag color="green">已导入 #{candidate.imported_job_id ?? ""}</Tag>
                ) : (
                  <Tag color="orange">待处理</Tag>
                )}
              </Space>
            </Descriptions.Item>
            {candidate.source_url && (
              <Descriptions.Item label="原岗位链接">
                <Typography.Link
                  href={candidate.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  <LinkOutlined /> 开原站岗位页面
                </Typography.Link>
              </Descriptions.Item>
            )}
          </Descriptions>

          {candidate.description && (
            <section>
              <Typography.Title level={5}>职位描述</Typography.Title>
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                {candidate.description}
              </Typography.Paragraph>
            </section>
          )}
          {candidate.requirements && (
            <section>
              <Typography.Title level={5}>任职要求</Typography.Title>
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                {candidate.requirements}
              </Typography.Paragraph>
            </section>
          )}
          {candidate.additional_info && (
            <section>
              <Typography.Title level={5}>其他招聘信息</Typography.Title>
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                {candidate.additional_info}
              </Typography.Paragraph>
            </section>
          )}
          {candidate.raw_text && (
            <section>
              <Typography.Title level={5}>招聘原文</Typography.Title>
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                {candidate.raw_text}
              </Typography.Paragraph>
            </section>
          )}
          {candidate.images.length > 0 && (
            <section>
              <Typography.Title level={5}>招聘截图</Typography.Title>
              <Space wrap>
                {candidate.images.map((source, index) => (
                  <Image key={`${index}-${source.slice(-16)}`} src={source} width={160} />
                ))}
              </Space>
            </section>
          )}
          {candidate.note && (
            <>
              <Divider style={{ margin: "4px 0" }} />
              <Typography.Text type="secondary">备注：{candidate.note}</Typography.Text>
            </>
          )}
        </Space>
      )}
    </Modal>
  );
}

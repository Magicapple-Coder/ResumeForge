/** 按需生成岗位需求总结和通用求职建议。 */
import { BulbOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, List, Modal, Skeleton, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { generateJobAnalysis } from "../api/jobs";
import type { Job, JobAnalysisPriority, JobAnalysisResult } from "../types";

interface Props {
  job: Job | null;
  onClose: () => void;
}

const PRIORITY_META: Record<JobAnalysisPriority, { label: string; color: string }> = {
  high: { label: "核心要求", color: "red" },
  medium: { label: "重要要求", color: "orange" },
  low: { label: "加分项", color: "blue" },
};

export default function JobAnalysisModal({ job, onClose }: Props) {
  const [data, setData] = useState<JobAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasAttempted, setHasAttempted] = useState(false);
  const requestVersion = useRef(0);
  const lastJobId = useRef<number | null>(null);

  useEffect(() => {
    if (!job || lastJobId.current === job.id) return;
    lastJobId.current = job.id;
    requestVersion.current += 1;
    setData(null);
    setError("");
    setLoading(false);
    setHasAttempted(false);
  }, [job]);

  const load = useCallback(async () => {
    if (!job) return;
    const currentRequest = ++requestVersion.current;
    setHasAttempted(true);
    setLoading(true);
    setError("");
    try {
      const result = await generateJobAnalysis(job.id);
      if (currentRequest === requestVersion.current) setData(result);
    } catch (loadError) {
      if (currentRequest === requestVersion.current) {
        setError(loadError instanceof Error ? loadError.message : "生成岗位解读失败，请稍后重试");
      }
    } finally {
      if (currentRequest === requestVersion.current) setLoading(false);
    }
  }, [job]);

  useEffect(() => {
    if (job && !hasAttempted) void load();
  }, [hasAttempted, job, load]);

  return (
    <Modal
      title={
        <Space>
          <BulbOutlined />
          岗位需求解读
        </Space>
      }
      open={!!job}
      onCancel={onClose}
      footer={null}
      width={760}
      destroyOnHidden
    >
      {error ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert type="error" showIcon message={error} />
          <Button
            aria-label="重新生成解读"
            icon={<ReloadOutlined />}
            loading={loading}
            onClick={() => void load()}
          >
            重新生成解读
          </Button>
        </Space>
      ) : loading ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : data ? (
        <div className="job-analysis-content">
          <div className="job-analysis-summary">
            <Space style={{ width: "100%", justifyContent: "space-between" }} wrap>
              <Typography.Text strong>
                {job?.company ? `${job.company} · ` : ""}
                {job?.title}
              </Typography.Text>
              <Button
                type="link"
                size="small"
                aria-label="重新生成"
                icon={<ReloadOutlined />}
                onClick={() => void load()}
              >
                重新生成
              </Button>
            </Space>
            <Typography.Paragraph>{data.summary}</Typography.Paragraph>
          </div>

          <Typography.Title level={5}>核心需求</Typography.Title>
          {data.requirements.length ? (
            <List
              dataSource={data.requirements}
              renderItem={(item) => {
                const priority = PRIORITY_META[item.priority];
                return (
                  <List.Item>
                    <Space direction="vertical" size={5} style={{ width: "100%" }}>
                      <Space wrap>
                        <Tag color={priority.color}>{priority.label}</Tag>
                        {item.category && <Tag>{item.category}</Tag>}
                      </Space>
                      <Typography.Text strong>{item.requirement}</Typography.Text>
                      {item.evidence && (
                        <Typography.Text type="secondary">依据：{item.evidence}</Typography.Text>
                      )}
                    </Space>
                  </List.Item>
                );
              }}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未提取到明确要求" />
          )}

          <Typography.Title level={5}>求职建议</Typography.Title>
          {data.advice.length ? (
            <List
              dataSource={data.advice}
              renderItem={(item) => (
                <List.Item>
                  <Space direction="vertical" size={4}>
                    <Typography.Text strong>{item.title}</Typography.Text>
                    <Typography.Text>{item.action}</Typography.Text>
                    {item.rationale && (
                      <Typography.Text type="secondary">原因：{item.rationale}</Typography.Text>
                    )}
                  </Space>
                </List.Item>
              )}
            />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无补充建议" />
          )}
        </div>
      ) : null}
    </Modal>
  );
}

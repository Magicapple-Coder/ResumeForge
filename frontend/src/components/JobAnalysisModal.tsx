/** 按需生成岗位需求总结和通用求职建议。 */
import { BulbOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, List, Modal, Skeleton, Space, Tag, Typography } from "antd";
import { announceBackgroundFailure, announceBackgroundResult } from "../utils/backgroundTask";
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

  // 用户在生成过程中关掉了弹窗：请求继续跑，但结果用统一通知告诉他（见 utils/backgroundTask）。
  const leftWhileLoading = useRef(false);

  const load = useCallback(async () => {
    if (!job) return;
    const currentRequest = ++requestVersion.current;
    setHasAttempted(true);
    setLoading(true);
    setError("");
    leftWhileLoading.current = false;
    try {
      const result = await generateJobAnalysis(job.id);
      if (leftWhileLoading.current) {
        announceBackgroundResult("岗位解读", "回到岗位详情再点「岗位需求解读」即可看到。");
        return;
      }
      if (currentRequest === requestVersion.current) setData(result);
    } catch (loadError) {
      const detail =
        loadError instanceof Error ? loadError.message : "生成岗位解读失败，请稍后重试";
      if (leftWhileLoading.current) {
        announceBackgroundFailure("岗位解读", detail);
        return;
      }
      if (currentRequest === requestVersion.current) setError(detail);
    } finally {
      if (!leftWhileLoading.current && currentRequest === requestVersion.current) setLoading(false);
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
        <div>
          <Skeleton active paragraph={{ rows: 8 }} />
          {/* 「后台继续」：请求不会因为关掉弹窗而中断，完成后会弹通知并响一声。
              没有这个按钮时，用户只能干等——而他根本不知道能不能走开。 */}
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 12 }}
            message="生成期间可以关掉这个弹窗去做别的，完成后会提醒你（弹窗 + 提示音）。"
          />
          <div style={{ marginTop: 12, textAlign: "right" }}>
            <Button
              onClick={() => {
                leftWhileLoading.current = true;
                onClose();
              }}
            >
              后台继续（关闭弹窗）
            </Button>
          </div>
        </div>
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

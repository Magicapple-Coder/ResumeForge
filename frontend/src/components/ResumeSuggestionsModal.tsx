/** 针对关联岗位生成简历修改建议的按需弹窗。 */
import { BulbOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Empty, List, Modal, Skeleton, Space, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { generateResumeSuggestions } from "../api/resumes";
import type { ResumeSuggestion, ResumeSuggestions } from "../types";

interface Props {
  open: boolean;
  recordId: number | null;
  /** 简历内容修改后递增，避免继续展示旧建议。 */
  resetKey?: number;
  onClose: () => void;
  onGenerated?: () => void;
}

const PRIORITY_META: Record<ResumeSuggestion["priority"], { label: string; color: string }> = {
  high: { label: "优先修改", color: "red" },
  medium: { label: "建议修改", color: "orange" },
  low: { label: "可选优化", color: "blue" },
};

export default function ResumeSuggestionsModal({
  open,
  recordId,
  resetKey = 0,
  onClose,
  onGenerated,
}: Props) {
  const [data, setData] = useState<ResumeSuggestions | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasAttempted, setHasAttempted] = useState(false);
  const requestVersion = useRef(0);
  const lastRecordId = useRef<number | null>(null);
  const lastResetKey = useRef(resetKey);

  useEffect(() => {
    if (!recordId) return;
    if (lastRecordId.current === recordId && lastResetKey.current === resetKey) return;
    lastRecordId.current = recordId;
    lastResetKey.current = resetKey;
    requestVersion.current += 1;
    setData(null);
    setError("");
    setLoading(false);
    setHasAttempted(false);
  }, [recordId, resetKey]);

  const loadSuggestions = useCallback(async () => {
    if (!recordId) return;
    const currentRequest = ++requestVersion.current;
    setHasAttempted(true);
    setLoading(true);
    setError("");
    try {
      const result = await generateResumeSuggestions(recordId);
      if (currentRequest !== requestVersion.current) return;
      setData(result);
      onGenerated?.();
    } catch (err) {
      if (currentRequest !== requestVersion.current) return;
      setError(err instanceof Error ? err.message : "生成建议失败，请稍后重试");
    } finally {
      if (currentRequest === requestVersion.current) setLoading(false);
    }
  }, [onGenerated, recordId]);

  useEffect(() => {
    if (open && recordId && !hasAttempted) void loadSuggestions();
  }, [hasAttempted, loadSuggestions, open, recordId]);

  return (
    <Modal
      title={
        <Space>
          <BulbOutlined />
          岗位化修改建议
        </Space>
      }
      open={open}
      onCancel={onClose}
      footer={null}
      width={720}
      destroyOnHidden
    >
      {error ? (
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert type="error" showIcon message={error} />
          <Button
            icon={<ReloadOutlined />}
            onClick={() => void loadSuggestions()}
            loading={loading}
          >
            重新生成建议
          </Button>
        </Space>
      ) : loading ? (
        <Skeleton active paragraph={{ rows: 5 }} />
      ) : data ? (
        <div>
          <Space style={{ marginBottom: 12 }} wrap>
            <Typography.Text type="secondary">
              目标岗位：{data.company ? `${data.company} · ` : ""}
              {data.job_title}
            </Typography.Text>
            <Button
              type="link"
              size="small"
              icon={<ReloadOutlined />}
              onClick={() => void loadSuggestions()}
            >
              重新生成建议
            </Button>
          </Space>
          {data.suggestions.length > 0 ? (
            <List
              bordered
              dataSource={data.suggestions}
              renderItem={(item) => {
                const priority = PRIORITY_META[item.priority];
                return (
                  <List.Item>
                    <Space direction="vertical" size={6} style={{ width: "100%" }}>
                      <Space wrap>
                        <Tag color={priority.color}>{priority.label}</Tag>
                        {item.section && <Tag>{item.section}</Tag>}
                      </Space>
                      <Typography.Text strong>{item.issue}</Typography.Text>
                      <Typography.Paragraph style={{ marginBottom: 0 }}>
                        {item.suggestion}
                      </Typography.Paragraph>
                      {item.evidence.length > 0 && (
                        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                          依据：{item.evidence.join("；")}
                        </Typography.Text>
                      )}
                    </Space>
                  </List.Item>
                );
              }}
            />
          ) : (
            <Empty description="当前简历与岗位要求匹配度较好，暂未发现必须修改项" />
          )}
        </div>
      ) : null}
    </Modal>
  );
}

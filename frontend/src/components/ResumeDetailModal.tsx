/** 简历记录预览弹窗（历史记录用）：加载详情与渲染 HTML 后展示。 */
import { BulbOutlined, EditOutlined, FolderOpenOutlined, MessageOutlined } from "@ant-design/icons";
import { Alert, App, Button, Modal, Skeleton, Space, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getResume, fetchResumeHtml, renderResume, updateResume } from "../api/resumes";
import { RESUME_ENHANCEMENT_LEVELS } from "../config";
import type { ResumeContent, ResumeDetail } from "../types";
import ExportButtons from "./ExportButtons";
import ResumeEditorModal from "./ResumeEditorModal";
import ResumePreview from "./ResumePreview";
import ResumeSuggestionsModal from "./ResumeSuggestionsModal";

interface Props {
  recordId: number | null;
  onClose: () => void;
}

export default function ResumeDetailModal({ recordId, onClose }: Props) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ResumeDetail | null>(null);
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorTarget, setEditorTarget] = useState<string | null>(null);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [suggestionsGenerated, setSuggestionsGenerated] = useState(false);
  const [suggestionsResetKey, setSuggestionsResetKey] = useState(0);
  const loadedRecordId = useRef<number | null>(null);
  const requestVersion = useRef(0);
  const saveRequestVersion = useRef(0);

  useEffect(() => {
    const currentRequest = ++requestVersion.current;
    if (!recordId) return;
    setDetail(null);
    setHtml("");
    setError("");
    setEditorOpen(false);
    setEditorTarget(null);
    setSuggestionsOpen(false);
    if (loadedRecordId.current !== recordId) {
      loadedRecordId.current = recordId;
      setSuggestionsGenerated(false);
      setSuggestionsResetKey((value) => value + 1);
    }
    void Promise.all([getResume(recordId), fetchResumeHtml(recordId)])
      .then(([data, rendered]) => {
        if (currentRequest !== requestVersion.current) return;
        setDetail(data);
        setHtml(rendered);
      })
      .catch((err) => {
        if (currentRequest === requestVersion.current) {
          setError(err instanceof Error ? err.message : "加载失败");
        }
      });
    return () => {
      if (currentRequest === requestVersion.current) requestVersion.current += 1;
    };
  }, [recordId]);

  const enhancementLabel = RESUME_ENHANCEMENT_LEVELS.find(
    (item) => item.value === detail?.enhancement_level,
  )?.label;

  const saveEditedResume = async (content: ResumeContent) => {
    if (!detail) return;
    const requestAtStart = requestVersion.current;
    const saveAtStart = ++saveRequestVersion.current;
    const updated = await updateResume(detail.id, content);
    if (requestAtStart !== requestVersion.current || saveAtStart !== saveRequestVersion.current) {
      return;
    }
    const rendered = await renderResume(updated.content);
    if (requestAtStart !== requestVersion.current || saveAtStart !== saveRequestVersion.current) {
      return;
    }
    setDetail(updated);
    setHtml(rendered);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    message.success("简历修改已保存");
  };

  return (
    <Modal
      title={detail?.title ?? "简历预览"}
      open={!!recordId}
      onCancel={onClose}
      width={860}
      footer={null}
      destroyOnHidden
    >
      {error ? (
        <Alert type="error" showIcon message={error} />
      ) : !detail || !html ? (
        <Skeleton active paragraph={{ rows: 8 }} />
      ) : (
        <div>
          <Space style={{ marginBottom: 12 }} wrap>
            <Tag color={detail.source === "manual" ? "purple" : "blue"}>
              {detail.source === "manual" ? "用户编写" : "AI 生成"}
            </Tag>
            <Tag color="blue">目标岗位：{detail.job_title || "-"}</Tag>
            {detail.company && <Tag>{detail.company}</Tag>}
            <Tag>模型：{detail.model || "-"}</Tag>
            <Tag color={detail.enhancement_enabled ? "green" : undefined}>
              美化拓展：{detail.enhancement_enabled ? (enhancementLabel ?? "已开启") : "未开启"}
            </Tag>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              创建于 {detail.created_at.replace("T", " ").slice(0, 16)}
            </Typography.Text>
          </Space>
          <ResumePreview
            html={html}
            warnings={detail.warnings}
            onEditTarget={(path) => {
              setEditorTarget(path);
              setEditorOpen(true);
            }}
          />
          <div
            style={{
              marginTop: 16,
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <Space wrap>
              <Button
                icon={<EditOutlined />}
                onClick={() => {
                  setEditorTarget(null);
                  setEditorOpen(true);
                }}
              >
                微调内容
              </Button>
              <Button
                icon={<BulbOutlined />}
                disabled={!detail.job_id}
                onClick={() => setSuggestionsOpen(true)}
              >
                {suggestionsGenerated ? "查看岗位优化建议" : "生成岗位优化建议"}
              </Button>
              <Button
                icon={<FolderOpenOutlined />}
                disabled={!detail.job_id}
                onClick={() => detail.job_id && navigate(`/jobs?job_id=${detail.job_id}`)}
              >
                查看对应岗位
              </Button>
              <Button
                icon={<MessageOutlined />}
                onClick={() => navigate(`/assistant?resume_id=${detail.id}`)}
              >
                咨询求职助手
              </Button>
            </Space>
            <ExportButtons recordId={detail.id} />
          </div>
        </div>
      )}
      <ResumeEditorModal
        open={editorOpen}
        content={detail?.content ?? null}
        initialTarget={editorTarget}
        onClose={() => {
          setEditorOpen(false);
          setEditorTarget(null);
        }}
        onSave={saveEditedResume}
      />
      <ResumeSuggestionsModal
        open={suggestionsOpen}
        recordId={detail?.id ?? null}
        resetKey={suggestionsResetKey}
        onClose={() => setSuggestionsOpen(false)}
        onGenerated={() => setSuggestionsGenerated(true)}
      />
    </Modal>
  );
}

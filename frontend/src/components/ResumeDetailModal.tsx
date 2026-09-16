/** 简历记录预览弹窗（历史记录用）：加载详情、调整版式、渲染 HTML 后展示。 */
import { BulbOutlined, EditOutlined, FolderOpenOutlined, MessageOutlined } from "@ant-design/icons";
import { Alert, App, Button, Modal, Skeleton, Space, Tag, Tooltip, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchResumeHtml,
  fetchResumeTemplates,
  getResume,
  renderResume,
  updateResume,
  updateResumeLayout,
} from "../api/resumes";
import { RESUME_ENHANCEMENT_LEVELS } from "../config";
import type { ResumeContent, ResumeDetail, ResumeLayout } from "../types";
import ExportButtons from "./ExportButtons";
import ResumeEditorModal from "./ResumeEditorModal";
import ResumeLayoutControls from "./ResumeLayoutControls";
import ResumePreview from "./ResumePreview";
import ResumeSuggestionsModal from "./ResumeSuggestionsModal";

interface Props {
  recordId: number | null;
  onClose: () => void;
}

const DEFAULT_LAYOUT: ResumeLayout = {
  template: "classic",
  page_limit: 1,
  font_scale: "standard",
};

export default function ResumeDetailModal({ recordId, onClose }: Props) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<ResumeDetail | null>(null);
  const [html, setHtml] = useState("");
  const [error, setError] = useState("");
  const [layout, setLayout] = useState<ResumeLayout>(DEFAULT_LAYOUT);
  const [layoutStatus, setLayoutStatus] = useState<{
    pages: number;
    scale: number;
    overflow: boolean;
  } | null>(null);
  const [pdfDirectAvailable, setPdfDirectAvailable] = useState(true);
  const [relayouting, setRelayouting] = useState(false);
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
    setLayoutStatus(null);
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
        // 版式跟着记录走：上次用的是哪套，这次打开还是哪套。
        setLayout({
          template: data.template || DEFAULT_LAYOUT.template,
          page_limit: data.page_limit || DEFAULT_LAYOUT.page_limit,
          font_scale: data.font_scale || DEFAULT_LAYOUT.font_scale,
        });
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

  // 只有第一次打开时才去问后端的模板目录（能不能直接生成 PDF）。
  useEffect(() => {
    void fetchResumeTemplates()
      .then((catalog) => setPdfDirectAvailable(catalog.pdf_direct_available))
      .catch(() => {
        // 取不到目录时仍允许导出，失败会由导出接口给出提示。
      });
  }, []);

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
    const rendered = await renderResume(updated.content, layout);
    if (requestAtStart !== requestVersion.current || saveAtStart !== saveRequestVersion.current) {
      return;
    }
    setDetail(updated);
    setHtml(rendered);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    message.success("简历修改已保存");
  };

  /** 换模板 / 加页数 / 改字号：写回记录并重新渲染，不重新生成内容。 */
  const applyLayout = async (next: ResumeLayout) => {
    if (!detail || relayouting) return;
    setRelayouting(true);
    setLayout(next);
    try {
      const updated = await updateResumeLayout(detail.id, next);
      setDetail(updated);
      setHtml(await renderResume(updated.content, next));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "按新版式渲染失败");
    } finally {
      setRelayouting(false);
    }
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
            {detail.job_id ? (
              <Tag color="blue">目标岗位：{detail.job_title || "-"}</Tag>
            ) : (
              // 通用简历没有岗位；job_title 里存的是求职意向。
              <>
                <Tooltip title="不关联岗位、可投递多个方向的简历">
                  <Tag color="purple">通用简历</Tag>
                </Tooltip>
                <Tag>求职意向：{detail.job_title || "未填写"}</Tag>
              </>
            )}
            {detail.company && <Tag>{detail.company}</Tag>}
            <Tag>模型：{detail.model || "-"}</Tag>
            <Tag color={detail.enhancement_enabled ? "green" : undefined}>
              美化拓展：{detail.enhancement_enabled ? (enhancementLabel ?? "已开启") : "未开启"}
            </Tag>
            <Typography.Text type="secondary" style={{ fontSize: 13 }}>
              创建于 {detail.created_at.replace("T", " ").slice(0, 16)}
            </Typography.Text>
          </Space>
          <div className="generate-layout-bar">
            <ResumeLayoutControls
              compact
              layout={layout}
              disabled={relayouting}
              onChange={(next) => void applyLayout(next)}
            />
            {relayouting && <Typography.Text type="secondary">正在按新版式渲染…</Typography.Text>}
          </div>
          {layoutStatus?.overflow && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={`内容超出了 ${layout.page_limit} 页：已经整体缩小，字会偏小`}
              action={
                <Space>
                  {layout.page_limit < 3 && (
                    <Button
                      size="small"
                      disabled={relayouting}
                      onClick={() =>
                        void applyLayout({ ...layout, page_limit: layout.page_limit + 1 })
                      }
                    >
                      增加到 {layout.page_limit + 1} 页
                    </Button>
                  )}
                  {layout.font_scale !== "small" && (
                    <Button
                      size="small"
                      disabled={relayouting}
                      onClick={() => void applyLayout({ ...layout, font_scale: "small" })}
                    >
                      改为小字号
                    </Button>
                  )}
                </Space>
              }
            />
          )}
          <ResumePreview
            html={html}
            pages={layout.page_limit}
            warnings={detail.warnings}
            onLayoutStatus={setLayoutStatus}
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
            <ExportButtons recordId={detail.id} pdfDirectAvailable={pdfDirectAvailable} />
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

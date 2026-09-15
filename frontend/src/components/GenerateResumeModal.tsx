/** AI 生成简历弹窗：配置岗位导向美化 -> 流式生成 -> 预览结果（自动保存历史）。 */
import { BulbOutlined, EditOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Input,
  Modal,
  Segmented,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { generateResume, renderResume, updateResume } from "../api/resumes";
import { getLLMConfig } from "../api/settings";
import { RESUME_ENHANCEMENT_LEVELS, enhancementLevelDescription } from "../config";
import type { EnhancementLevel, Job, ResumeContent, StreamEvent } from "../types";
import ExportButtons from "./ExportButtons";
import ResumeEditorModal from "./ResumeEditorModal";
import ResumePreview from "./ResumePreview";
import ResumeSuggestionsModal from "./ResumeSuggestionsModal";

type Stage = "config" | "generating" | "preview" | "error";

interface Props {
  /** null 表示生成**通用简历**（不针对任何岗位）。 */
  job: Job | null;
  open: boolean;
  /** 通用简历的初始名称，留空则后端按「姓名-通用简历-时间戳」命名。 */
  initialTitle?: string;
  onClose: () => void;
}

interface GenerateResult {
  resume: ResumeContent;
  warnings: string[];
  recordId: number | null;
}

export default function GenerateResumeModal({ job, open, initialTitle = "", onClose }: Props) {
  const { message } = App.useApp();
  const navigate = useNavigate();

  const [stage, setStage] = useState<Stage>("config");
  const [title, setTitle] = useState("");
  const [enhance, setEnhance] = useState(false);
  const [enhancementLevel, setEnhancementLevel] = useState<EnhancementLevel>("balanced");
  const [modelName, setModelName] = useState("");
  const [llmReady, setLlmReady] = useState(true);
  const [progress, setProgress] = useState<string[]>([]);
  const [streamText, setStreamText] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [previewHtml, setPreviewHtml] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorTarget, setEditorTarget] = useState<string | null>(null);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [suggestionsGenerated, setSuggestionsGenerated] = useState(false);
  const [suggestionsResetKey, setSuggestionsResetKey] = useState(0);

  const abortRef = useRef<AbortController | null>(null);
  const streamBoxRef = useRef<HTMLDivElement>(null);
  const generationVersion = useRef(0);
  const streamTextBuffer = useRef("");
  const streamFrame = useRef<number | null>(null);

  // 打开时把资料页填的名称带进来。reset() 只在关闭时跑，不补这一步的话
  // 名称输入框永远是空的。
  useEffect(() => {
    if (open) setTitle(initialTitle);
  }, [open, initialTitle]);

  // 打开弹窗时检查 LLM 配置并展示当前模型
  useEffect(() => {
    if (!open) return;
    void getLLMConfig()
      .then((config) => {
        setModelName(config.model || "");
        setLlmReady(!!config.base_url && !!config.model);
      })
      .catch(() => setLlmReady(false));
  }, [open]);

  // 流式文本自动滚到底部
  useEffect(() => {
    if (stage === "generating" && streamBoxRef.current) {
      streamBoxRef.current.scrollTop = streamBoxRef.current.scrollHeight;
    }
  }, [streamText, stage]);

  // 关闭时中止未完成的请求，并清理尚未提交到 React 的流式文本帧。
  useEffect(
    () => () => {
      generationVersion.current += 1;
      abortRef.current?.abort();
      if (streamFrame.current !== null) cancelAnimationFrame(streamFrame.current);
    },
    [],
  );

  const reset = useCallback(() => {
    generationVersion.current += 1;
    streamTextBuffer.current = "";
    if (streamFrame.current !== null) {
      cancelAnimationFrame(streamFrame.current);
      streamFrame.current = null;
    }
    setStage("config");
    setTitle(initialTitle);
    setProgress([]);
    setStreamText("");
    setErrorMsg("");
    setResult(null);
    setPreviewHtml("");
    setEditorOpen(false);
    setEditorTarget(null);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    setSuggestionsOpen(false);
  }, [initialTitle]);

  const startGenerate = async () => {
    if (!open) return;
    abortRef.current?.abort();
    const currentGeneration = ++generationVersion.current;
    const controller = new AbortController();
    abortRef.current = controller;
    streamTextBuffer.current = "";
    if (streamFrame.current !== null) {
      cancelAnimationFrame(streamFrame.current);
      streamFrame.current = null;
    }
    setStage("generating");
    setProgress([]);
    setStreamText("");
    setErrorMsg("");
    setResult(null);
    setEditorOpen(false);
    setEditorTarget(null);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    // 事件回调里只更新状态；最终结果收集在闭包变量中，流结束后统一处理
    const final: {
      resume: ResumeContent | null;
      warnings: string[];
      recordId: number | null;
      error: string;
    } = {
      resume: null,
      warnings: [],
      recordId: null,
      error: "",
    };
    const handleEvent = (event: StreamEvent) => {
      if (currentGeneration !== generationVersion.current) return;
      switch (event.type) {
        case "progress":
          setProgress((prev) => [...prev, event.message]);
          break;
        case "delta":
          streamTextBuffer.current += event.text;
          if (streamFrame.current === null) {
            streamFrame.current = requestAnimationFrame(() => {
              streamFrame.current = null;
              if (currentGeneration === generationVersion.current) {
                setStreamText(streamTextBuffer.current);
              }
            });
          }
          break;
        case "done":
          final.resume = event.resume;
          final.warnings = event.warnings;
          break;
        case "saved":
          final.recordId = event.record_id;
          break;
        case "error":
          final.error = event.message;
          setErrorMsg(event.message);
          break;
      }
    };

    try {
      await generateResume(
        {
          job_id: job?.id ?? null,
          title: job ? "" : title.trim(),
          options: { enhance, enhancement_level: enhancementLevel },
        },
        handleEvent,
        controller.signal,
      );
      if (currentGeneration !== generationVersion.current) return;
      if (streamFrame.current !== null) {
        cancelAnimationFrame(streamFrame.current);
        streamFrame.current = null;
      }
      setStreamText(streamTextBuffer.current);
      if (final.resume) {
        const html = await renderResume(final.resume);
        if (currentGeneration !== generationVersion.current) return;
        setResult({ resume: final.resume, warnings: final.warnings, recordId: final.recordId });
        setPreviewHtml(html);
        setStage("preview");
        message.success("简历已生成并自动保存到简历中心");
      } else {
        setStage("error");
        setErrorMsg(final.error || "生成失败：未收到有效结果");
      }
    } catch (err) {
      if (currentGeneration !== generationVersion.current) return;
      // 用户主动取消不报错
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setStage("error");
        setErrorMsg(err instanceof Error ? err.message : "生成失败，请重试");
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  };

  const handleClose = () => {
    abortRef.current?.abort();
    reset();
    onClose();
  };

  const saveEditedResume = async (content: ResumeContent) => {
    if (!result?.recordId) {
      throw new Error("简历记录尚未保存完成，请稍后再试");
    }
    const updated = await updateResume(result.recordId, content);
    const html = await renderResume(updated.content);
    setResult({ resume: updated.content, warnings: updated.warnings, recordId: updated.id });
    setPreviewHtml(html);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    message.success("简历修改已保存");
  };

  return (
    <Modal
      title={job ? `为「${job.title}」生成简历` : "生成通用简历"}
      open={open}
      onCancel={handleClose}
      width={860}
      footer={null}
      maskClosable={stage !== "generating"}
      closable={stage !== "generating"}
      destroyOnHidden
    >
      {stage === "config" && (
        <div>
          {!llmReady ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 16 }}
              message="尚未配置大模型 API，请先到「设置」页完成配置（支持 DeepSeek / 豆包 / Kimi / OpenAI 等）"
            />
          ) : (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 16 }}
              message={`当前模型：${modelName || "未知"}。生成过程约需 1-2 分钟，请勿关闭弹窗。`}
              description={
                job
                  ? "系统会根据目标岗位的 JD，从完整个人资料与经历总结文件中筛选并排序相关信息；原始资料不会被修改。"
                  : "通用简历不针对任何岗位：系统会完整使用你的资料（只受篇幅预算限制），保留各方向的经历与技能；原始资料不会被修改。"
              }
            />
          )}
          {!job && (
            <div style={{ marginBottom: 16 }}>
              <Typography.Text strong>简历名称</Typography.Text>
              <Input
                aria-label="简历名称"
                value={title}
                maxLength={64}
                style={{ marginTop: 8 }}
                placeholder="留空则自动命名为「姓名-通用简历-时间」"
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
          )}
          <Typography.Title level={5}>{job ? "岗位适配与内容美化" : "内容美化"}</Typography.Title>
          <Space direction="vertical" size={14} style={{ width: "100%" }}>
            <Space size={10}>
              <Switch checked={enhance} onChange={setEnhance} />
              <Typography.Text strong>
                {job ? "根据岗位要求美化拓展经历" : "用资料里的总结文件补足经历细节"}
              </Typography.Text>
            </Space>
            <Typography.Text type="secondary">
              {job
                ? "基于已有经历和总结文件补足表达细节，突出与岗位相关的能力，不修改个人资料原文。"
                : "基于已有经历和总结文件补足表达细节，突出资料本身的重点，不修改个人资料原文。"}
            </Typography.Text>
            <Segmented
              block
              disabled={!enhance}
              value={enhancementLevel}
              options={RESUME_ENHANCEMENT_LEVELS.map((item) => ({
                label: item.label,
                value: item.value,
              }))}
              onChange={(value) => setEnhancementLevel(value as EnhancementLevel)}
            />
            <Typography.Text type={enhance ? undefined : "secondary"}>
              {enhance
                ? enhancementLevelDescription(enhancementLevel, !job)
                : "关闭后仅筛选和整理原有资料，不进行拓展。"}
            </Typography.Text>
          </Space>
          <div style={{ marginTop: 24, textAlign: "right" }}>
            <Space>
              <Button onClick={handleClose}>取消</Button>
              <Button type="primary" disabled={!llmReady} onClick={() => void startGenerate()}>
                开始生成
              </Button>
            </Space>
          </div>
        </div>
      )}

      {stage === "generating" && (
        <div>
          {progress.map((item, index) => (
            <div key={`${index}-${item}`} style={{ marginBottom: 6 }}>
              <Spin size="small" style={{ marginRight: 8 }} />
              <Typography.Text>{item}</Typography.Text>
            </div>
          ))}
          <div
            ref={streamBoxRef}
            className="stream-text"
            style={{
              marginTop: 12,
              padding: 12,
              background: "#fafafa",
              borderRadius: 6,
              maxHeight: 320,
              overflowY: "auto",
              border: "1px solid #f0f0f0",
            }}
          >
            {streamText || "等待模型输出…"}
          </div>
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Button danger onClick={handleClose}>
              取消生成
            </Button>
          </div>
        </div>
      )}

      {stage === "preview" && result && (
        <div>
          <ResumePreview
            html={previewHtml}
            warnings={result.warnings}
            onEditTarget={(path) => {
              if (!result.recordId) return;
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
            <Space>
              {result.recordId ? (
                <ExportButtons recordId={result.recordId} />
              ) : (
                <Tag color="orange">记录保存中…</Tag>
              )}
            </Space>
            <Space>
              <Button
                icon={<EditOutlined />}
                disabled={!result.recordId}
                onClick={() => {
                  setEditorTarget(null);
                  setEditorOpen(true);
                }}
              >
                微调内容
              </Button>
              {job && (
                <>
                  <Button
                    icon={<BulbOutlined />}
                    disabled={!result.recordId}
                    onClick={() => setSuggestionsOpen(true)}
                  >
                    {suggestionsGenerated ? "查看岗位优化建议" : "生成岗位优化建议"}
                  </Button>
                  <Button onClick={() => navigate(`/jobs?job_id=${job.id}`)}>查看对应岗位</Button>
                </>
              )}
              <Button onClick={() => navigate("/resumes")}>去简历中心</Button>
              <Button icon={<ReloadOutlined />} onClick={() => void startGenerate()}>
                重新生成
              </Button>
              <Button type="primary" onClick={handleClose}>
                完成
              </Button>
            </Space>
          </div>
        </div>
      )}

      <ResumeEditorModal
        open={editorOpen}
        content={result?.resume ?? null}
        initialTarget={editorTarget}
        onClose={() => {
          setEditorOpen(false);
          setEditorTarget(null);
        }}
        onSave={saveEditedResume}
      />
      <ResumeSuggestionsModal
        open={suggestionsOpen}
        recordId={result?.recordId ?? null}
        resetKey={suggestionsResetKey}
        onClose={() => setSuggestionsOpen(false)}
        onGenerated={() => setSuggestionsGenerated(true)}
      />

      {stage === "error" && (
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <Alert
            type="error"
            showIcon
            message={errorMsg || "生成失败"}
            style={{ marginBottom: 24 }}
          />
          <Space>
            <Button onClick={reset}>返回重试</Button>
            <Button type="primary" onClick={() => void startGenerate()}>
              重新生成
            </Button>
          </Space>
        </div>
      )}
    </Modal>
  );
}

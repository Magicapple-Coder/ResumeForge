/** AI 生成简历弹窗：配置岗位导向美化/篇幅 -> 流式生成 -> 预览结果（自动保存历史）。 */
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
  Tooltip,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  fetchResumeTemplates,
  generateResume,
  renderResume,
  updateResume,
  updateResumeLayout,
} from "../api/resumes";
import { getLLMConfig } from "../api/settings";
import { RESUME_ENHANCEMENT_LEVELS, enhancementLevelDescription } from "../config";
import type { EnhancementLevel, Job, ResumeContent, ResumeLayout, StreamEvent } from "../types";
import ExportButtons from "./ExportButtons";
import ResumeEditorModal from "./ResumeEditorModal";
import ResumeLayoutControls from "./ResumeLayoutControls";
import ResumePreview from "./ResumePreview";
import ResumeSuggestionsModal from "./ResumeSuggestionsModal";

/** 自定义提示词上限，与后端 GenerateOptions.custom_instruction 一致。 */
const MAX_CUSTOM_INSTRUCTION = 2000;

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
  // 默认 1 页 A4 + 标准字号：绝大多数简历就该是一页。
  const [layout, setLayout] = useState<ResumeLayout>({
    template: "classic",
    format_name: "",
    page_limit: 1,
    font_scale: "standard",
  });
  const [customInstruction, setCustomInstruction] = useState("");
  const [layoutStatus, setLayoutStatus] = useState<{
    pages: number;
    scale: number;
    overflow: boolean;
  } | null>(null);
  const [pdfDirectAvailable, setPdfDirectAvailable] = useState(true);
  const [relayouting, setRelayouting] = useState(false);
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

  // 每次打开都按后端给的默认值重置版式，并记下服务端能不能直接生成 PDF。
  useEffect(() => {
    if (!open) return;
    void fetchResumeTemplates()
      .then((catalog) => {
        setPdfDirectAvailable(catalog.pdf_direct_available);
        // 三个参数都要重置。此前漏了 page_limit（只覆盖 template / font_scale），
        // 于是上一次选过 3 页的话，下次打开默认就是 3 页，与"默认一页 A4"相矛盾。
        setLayout((current) => ({
          ...current,
          template: catalog.defaults.template,
          format_name: catalog.defaults.format_name ?? "",
          font_scale: catalog.defaults.font_scale,
          page_limit: catalog.defaults.page_limit,
        }));
      })
      .catch(() => {
        // 取不到目录就用内置默认值，不影响生成。
      });
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
    setLayoutStatus(null);
    setCustomInstruction("");
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
          options: {
            enhance,
            enhancement_level: enhancementLevel,
            page_limit: layout.page_limit,
            font_scale: layout.font_scale,
            template: layout.template,
            format_name: layout.format_name,
            custom_instruction: customInstruction.trim(),
          },
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
        const html = await renderResume(final.resume, layout);
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
    const html = await renderResume(updated.content, layout);
    setResult({ resume: updated.content, warnings: updated.warnings, recordId: updated.id });
    setPreviewHtml(html);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    message.success("简历修改已保存");
  };

  /**
   * 换模板 / 加页数 / 改字号：只重新渲染，不重新调用模型。
   *
   * 记录已经落库，所以同时把版式写回记录——下次从简历中心打开时看到的还是这一套。
   */
  const applyLayout = async (next: ResumeLayout) => {
    setLayout(next);
    const resume = result?.resume;
    if (!resume || relayouting) return;
    setRelayouting(true);
    try {
      const html = await renderResume(resume, next);
      setPreviewHtml(html);
      if (result?.recordId) {
        await updateResumeLayout(result.recordId, next);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : "按新版式渲染失败");
    } finally {
      setRelayouting(false);
    }
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
              // 下面的说明只讲当前选中的那一档，得先点一下才知道别的档是什么；
              // 每一档自己带上悬停说明，生成前可以先把三档比一遍。
              options={RESUME_ENHANCEMENT_LEVELS.map((item) => ({
                label: (
                  <Tooltip title={enhancementLevelDescription(item.value, !job)}>
                    {item.label}
                  </Tooltip>
                ),
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

          <Typography.Title level={5} style={{ marginTop: 20 }}>
            篇幅与版式
          </Typography.Title>
          <ResumeLayoutControls layout={layout} disabled={!llmReady} onChange={setLayout} />
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 8 }}>
            默认 1 页 A4 +
            标准字号。生成后如果内容塞不下，可以在预览里一键增加页数或缩小字号，不必重新生成。
          </Typography.Text>

          <Typography.Title level={5} style={{ marginTop: 20 }}>
            补充要求（选填）
          </Typography.Title>
          <Input.TextArea
            value={customInstruction}
            maxLength={MAX_CUSTOM_INSTRUCTION}
            showCount
            disabled={!llmReady}
            autoSize={{ minRows: 2, maxRows: 5 }}
            placeholder="例如：突出后端性能优化经历；不要出现「负责…」这类空泛表述；把实习经历放在教育经历前面。"
            onChange={(event) => setCustomInstruction(event.target.value)}
          />
          <Typography.Text type="secondary" style={{ display: "block", marginTop: 8 }}>
            这段要求会附在生成提示词后面，只影响表达方向；事实锚定、篇幅上限和防虚构规则不变。
          </Typography.Text>

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
          <div className="generate-layout-bar">
            <ResumeLayoutControls
              compact
              layout={layout}
              resumeId={result.recordId ?? undefined}
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
            html={previewHtml}
            pages={layout.page_limit}
            warnings={result.warnings}
            onLayoutStatus={setLayoutStatus}
            onEditTarget={(path) => {
              if (!result.recordId) return;
              setEditorTarget(path);
              setEditorOpen(true);
            }}
          />
          {/* 按钮组用 flex + wrap：窄屏或按钮多时换行，而不是把「完成」挤出弹窗
              （截图反馈：右侧按钮整体溢出到弹窗外面）。 */}
          <div className="generate-preview-footer">
            <Space wrap>
              {result.recordId ? (
                <ExportButtons recordId={result.recordId} pdfDirectAvailable={pdfDirectAvailable} />
              ) : (
                <Tag color="orange">记录保存中…</Tag>
              )}
            </Space>
            <Space wrap>
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

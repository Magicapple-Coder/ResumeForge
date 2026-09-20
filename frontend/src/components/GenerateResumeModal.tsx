/** AI 生成简历弹窗：配置岗位导向美化/篇幅 -> 流式生成 -> 预览结果（自动保存历史）。 */
import { ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  App,
  Button,
  Input,
  Modal,
  Segmented,
  Space,
  Steps,
  Switch,
  Tooltip,
  Typography,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  cancelResumeGenerateTask,
  fetchResumeTemplates,
  getResume,
  getResumeGenerateTask,
  renderResume,
  startResumeGeneration,
  updateResume,
  updateResumeLayout,
} from "../api/resumes";
import { getLLMConfig } from "../api/settings";
import { RESUME_ENHANCEMENT_LEVELS, enhancementLevelDescription } from "../config";
import type {
  EnhancementLevel,
  Job,
  ResumeContent,
  ResumeDetail,
  ResumeGenerateTask,
  ResumeLayout,
} from "../types";
import type { LayoutMeasure } from "../utils/resumeLayoutMeasure";
import ResumeDetailPreview from "./resume/ResumeDetailPreview";
import ResumeLayoutControls from "./ResumeLayoutControls";
import type { ResumePreviewHandle } from "./ResumePreview";
import {
  RESUME_GENERATION_STAGES,
  stageForProgressMessage,
  stageIndexOf,
} from "./resumeGenerationStages";

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

/** 生成完成的简历记录：直接持有完整 detail，预览阶段与简历中心共享同一套界面（B3）。 */
interface GenerateResult {
  detail: ResumeDetail;
}

export default function GenerateResumeModal({ job, open, initialTitle = "", onClose }: Props) {
  const { message, notification } = App.useApp();
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
  const [measure, setMeasure] = useState<LayoutMeasure | null>(null);
  const [pdfDirectAvailable, setPdfDirectAvailable] = useState(true);
  const [relayouting, setRelayouting] = useState(false);
  const [modelName, setModelName] = useState("");
  const [llmReady, setLlmReady] = useState(true);
  // 生成改为后台任务：taskId 驱动轮询，task 是最近一次轮询到的状态。
  const [taskId, setTaskId] = useState<number | null>(null);
  const [task, setTask] = useState<ResumeGenerateTask | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [result, setResult] = useState<GenerateResult | null>(null);
  const [previewHtml, setPreviewHtml] = useState("");
  const [suggestionsGenerated, setSuggestionsGenerated] = useState(false);
  const [suggestionsResetKey, setSuggestionsResetKey] = useState(0);

  // 生成开始时的版式快照：后台完成后用它渲染预览，避免完成后用户又改了配置导致
  // 预览参数与生成参数不一致。
  const generationLayoutRef = useRef<ResumeLayout>(layout);
  // 预览句柄：拖动字号时用它把探针 CSS 即时注入预览（本地缩放，无网络往返）。
  const previewRef = useRef<ResumePreviewHandle>(null);

  // 后台生成是否仍在进行：决定"重新打开弹窗"时是接着看进度，还是回到配置页。
  // 生成中关掉弹窗（后台继续）不 reset，所以 stage 会留在 generating；等它跑到终态
  // （completed/cancelled/failed）后 taskId 被清空、stage 被改写，这里跟着变 false。
  const generatingInBackground = stage === "generating" && taskId != null;
  const generatingRef = useRef(generatingInBackground);
  useEffect(() => {
    generatingRef.current = generatingInBackground;
  }, [generatingInBackground]);

  // 打开时把资料页填的名称带进来。reset() 只在关闭时跑，不补这一步的话
  // 名称输入框永远是空的。
  useEffect(() => {
    if (open) setTitle(initialTitle);
  }, [open, initialTitle]);

  // 重新打开弹窗时回到配置页；唯一例外是上次的生成还在后台跑（生成中关掉的），
  // 此时保持 generating 让用户接着看进度——否则"生成中关掉 → 后台完成 → 再打开"
  // 会看到一份过期/错位的预览。
  useEffect(() => {
    if (!open) return;
    if (generatingRef.current) return;
    setStage("config");
    setResult(null);
    setPreviewHtml("");
    setErrorMsg("");
  }, [open]);

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

  const reset = useCallback(() => {
    setStage("config");
    setTitle(initialTitle);
    setTaskId(null);
    setTask(null);
    setErrorMsg("");
    setResult(null);
    setPreviewHtml("");
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    setLayoutStatus(null);
    setMeasure(null);
    setCustomInstruction("");
  }, [initialTitle]);

  const loadPreview = useCallback(async (resumeId: number) => {
    try {
      const detail = await getResume(resumeId);
      const html = await renderResume(detail.content, generationLayoutRef.current);
      setResult({ detail });
      setPreviewHtml(html);
      setStage("preview");
    } catch (err) {
      setStage("error");
      setErrorMsg(err instanceof Error ? err.message : "生成完成，但加载结果失败");
    }
  }, []);

  const startGenerate = async () => {
    if (!open) return;
    generationLayoutRef.current = layout;
    setStage("generating");
    setTaskId(null);
    setTask(null);
    setErrorMsg("");
    setResult(null);
    setSuggestionsGenerated(false);
    setSuggestionsResetKey((value) => value + 1);
    try {
      const started = await startResumeGeneration({
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
      });
      setTaskId(started.id);
      setTask(started);
    } catch (err) {
      setStage("error");
      setErrorMsg(err instanceof Error ? err.message : "启动生成失败，请重试");
    }
  };

  // 轮询后台任务：进入终态前每 1.5s 拉一次状态（与 useTaskPolling 同一套轮询模型）。
  useEffect(() => {
    if (taskId == null) return;
    let disposed = false;
    const poll = async () => {
      try {
        const updated = await getResumeGenerateTask(taskId);
        if (!disposed) setTask(updated);
      } catch {
        // 轮询失败（后端短暂不可用）不打断，等下一轮自愈。
      }
    };
    void poll();
    const timer = window.setInterval(poll, 1500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [taskId]);

  // 任务进入终态后的收尾：完成→取简历进预览并提醒；取消→回配置；失败→错误。
  useEffect(() => {
    if (!task) return;
    if (task.status === "completed") {
      const resumeId = task.resume_id;
      setTaskId(null);
      setTask(null);
      if (resumeId == null) {
        // 完成却没回填记录 id：理论上不会发生（完成一定先落库），防御性当作失败处理，
        // 避免卡在"完成"状态却永远拿不到预览。
        setErrorMsg("生成完成，但结果记录缺失，请重试");
        setStage("error");
        return;
      }
      notification.success({
        message: "简历已生成",
        description: "已自动保存到简历中心，可以继续微调或导出。",
        actions: (
          <Button size="small" onClick={() => navigate("/resumes")}>
            查看简历
          </Button>
        ),
      });
      void loadPreview(resumeId);
    } else if (task.status === "cancelled") {
      setTaskId(null);
      setTask(null);
      setStage("config");
      message.info("已取消生成");
    } else if (task.status === "failed") {
      setTaskId(null);
      setErrorMsg(task.error || "生成失败，请重试");
      setStage("error");
    }
  }, [task, notification, message, navigate, loadPreview]);

  const handleCancelGenerate = async () => {
    if (taskId == null) return;
    try {
      const cancelled = await cancelResumeGenerateTask(taskId);
      setTask(cancelled);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "取消失败，请重试");
    }
  };

  const handleClose = () => {
    // 生成中关弹窗 = 后台继续（不是取消）：任务继续跑，完成后提醒；其余阶段照旧复位。
    if (stage === "generating" && taskId != null) {
      onClose();
      return;
    }
    reset();
    onClose();
  };

  const saveEditedResume = async (content: ResumeContent) => {
    const recordId = result?.detail.id;
    if (!recordId) {
      throw new Error("简历记录尚未保存完成，请稍后再试");
    }
    const updated = await updateResume(recordId, content);
    const html = await renderResume(updated.content, layout);
    setResult({ detail: updated });
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
    const detail = result?.detail;
    if (!detail || relayouting) return;
    setRelayouting(true);
    try {
      const html = await renderResume(detail.content, next);
      setPreviewHtml(html);
      if (result?.detail.id) {
        await updateResumeLayout(result.detail.id, next);
      }
    } catch (err) {
      message.error(err instanceof Error ? err.message : "按新版式渲染失败");
    } finally {
      setRelayouting(false);
    }
  };

  /** 「自动一页」已由诊断卡写回配置，这里只需按新配置重渲染一次。 */
  const applyFittedFormat = async (formatConfig: Record<string, number | string>) => {
    const detail = result?.detail;
    if (!detail) return;
    const next: ResumeLayout = { ...layout, format_config: formatConfig };
    setLayout(next);
    setRelayouting(true);
    try {
      setPreviewHtml(await renderResume(detail.content, next));
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
              message={`当前模型：${modelName || "未知"}。生成过程约需 1-2 分钟，生成在后台进行，期间可关闭弹窗，完成后会自动提醒。`}
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
          <Steps
            size="small"
            current={stageIndexOf(stageForProgressMessage(task?.message ?? ""))}
            items={RESUME_GENERATION_STAGES.map((item) => ({ title: item.title }))}
            style={{ marginBottom: 8 }}
          />
          <Typography.Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
            {task?.message || "正在准备…"} · 已接收 {task?.received_chars ?? 0} 字
          </Typography.Text>
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message="生成已在后台开始：现在关闭弹窗不会中断，完成后会自动提醒并打开结果。"
          />
          <div style={{ marginTop: 16, textAlign: "right" }}>
            <Space>
              <Button onClick={handleClose}>后台继续（关闭弹窗）</Button>
              <Button danger disabled={taskId == null} onClick={() => void handleCancelGenerate()}>
                取消生成
              </Button>
            </Space>
          </div>
        </div>
      )}

      {stage === "preview" && result && (
        <ResumeDetailPreview
          detail={result.detail}
          html={previewHtml}
          layout={layout}
          layoutStatus={layoutStatus}
          measure={measure}
          pdfDirectAvailable={pdfDirectAvailable}
          relayouting={relayouting}
          previewRef={previewRef}
          onLayoutStatus={setLayoutStatus}
          onMeasure={setMeasure}
          onApplyLayout={(next) => void applyLayout(next)}
          onApplyFittedFormat={(formatConfig) => void applyFittedFormat(formatConfig)}
          onSaveEditedResume={(content) => saveEditedResume(content)}
          suggestionsGenerated={suggestionsGenerated}
          suggestionsResetKey={suggestionsResetKey}
          onSuggestionsGenerated={() => setSuggestionsGenerated(true)}
          extraActions={
            <Space wrap>
              <Button onClick={() => navigate("/resumes")}>去简历中心</Button>
              <Button icon={<ReloadOutlined />} onClick={() => void startGenerate()}>
                重新生成
              </Button>
              <Button type="primary" onClick={handleClose}>
                完成
              </Button>
            </Space>
          }
        />
      )}

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

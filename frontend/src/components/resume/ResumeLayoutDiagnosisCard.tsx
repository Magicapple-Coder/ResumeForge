/**
 * 版面诊断面板：告诉你版面是空是挤、按什么顺序改，并提供「自动一页」。
 *
 * 分工：**规则全在后端**（多少算满、先动哪个旋钮、字号缩到哪为止），这里只做两件
 * 前端才有能力做的事——把实测高度送上取结论、把候选版式真的应用到预览上量一次。
 *
 * 「自动一页」的关键取舍：**逐档试、够放下就停**，而不是一步把字号缩到最小。
 * 每试一档只是往 iframe 里注入一段后端给的 CSS 再量一次，没有网络往返，所以可以
 * 试得比较细（页边距 → 区块间距 → 行高 → 字号，共十几档）。
 */
import type { ResumeFormatConfig } from "../../types/resumeFormat";
import { App, Alert, Button, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { analyzeResumeLayout, updateResumeLayout } from "../../api/resumes";
import type { ResumeLayout, ResumeLayoutAnalysis, ResumeLayoutStatus } from "../../types";
import type { ResumePreviewHandle } from "../ResumePreview";
import type { LayoutMeasure } from "../../utils/resumeLayoutMeasure";

const STATUS_COLORS: Record<ResumeLayoutStatus, string> = {
  overflow: "red",
  dense: "orange",
  healthy: "green",
  sparse: "gold",
  too_sparse: "gold",
  unknown: "default",
};

interface Props {
  resumeId: number;
  /** 预览量到的实测高度；还没渲染完时为 null。 */
  measure: LayoutMeasure | null;
  /** 预览是否已经判定溢出。诊断接口不可用时靠它兜底，免得连"塞不下"都不说。 */
  overflow: boolean;
  previewRef: React.RefObject<ResumePreviewHandle | null>;
  /**
   * 这份简历当前的版式参数。
   *
   * **必须原样回传**：`PATCH /layout` 是整体替换，漏掉哪个字段就等于把它重置成默认值——
   * 只想着保存 format_config 而传空模板名，会把用户选好的样式模板和字号悄悄改掉。
   */
  layout: ResumeLayout;
  disabled?: boolean;
  /** 保存了新方案之后让父组件重新渲染预览。 */
  onApplied: (formatConfig: ResumeFormatConfig) => void;
  onAddPage: () => void;
}

export default function ResumeLayoutDiagnosisCard({
  resumeId,
  measure,
  overflow,
  previewRef,
  layout,
  disabled = false,
  onApplied,
  onAddPage,
}: Props) {
  const { message } = App.useApp();
  const [analysis, setAnalysis] = useState<ResumeLayoutAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [fitting, setFitting] = useState<{ index: number; total: number; label: string } | null>(
    null,
  );
  const requestId = useRef(0);

  const measureKey = measure
    ? `${measure.usedHeight.toFixed(1)}:${measure.pageContentHeight.toFixed(1)}:${measure.pageLimit}`
    : "";

  useEffect(() => {
    if (!measure) {
      setAnalysis(null);
      setAnalyzing(false);
      return;
    }
    const current = ++requestId.current;
    // 轻微防抖：预览刚渲染完时可能连着上报几次（字体就绪、缩放变化）。
    const timer = setTimeout(() => {
      setAnalyzing(true);
      analyzeResumeLayout(resumeId, {
        used_height: measure.usedHeight,
        page_content_height: measure.pageContentHeight,
        page_limit: measure.pageLimit,
      })
        .then((result) => {
          if (current === requestId.current) setAnalysis(result);
        })
        .catch(() => {
          // 诊断失败不该打扰正在看简历的用户：面板退回"只说溢出"的兜底形态。
          if (current === requestId.current) setAnalysis(null);
        })
        .finally(() => {
          // ★ 复位不能加 `current === requestId.current` 条件：防抖期间连续上报时，
          // 先发出的那次会被后来者"作废"，于是它的 finally 被跳过、analyzing 永远停在
          // true——表现就是卡片该消失的时候一直挂着。只有**结果**需要防过期，
          // "加载中"这个状态不需要。
          setAnalyzing(false);
        });
    }, 250);
    return () => clearTimeout(timer);
    // measureKey 把「同一个高度重复上报」折叠掉，避免每次渲染都打一次接口。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId, measureKey]);

  const autoFit = useCallback(async () => {
    const ladder = analysis?.fit_ladder ?? [];
    const preview = previewRef.current;
    if (ladder.length === 0 || !preview) return;

    // 逐档试：够放下就停在这里，不会一步把字号缩到最小。
    for (let index = 0; index < ladder.length; index += 1) {
      const candidate = ladder[index];
      setFitting({ index: index + 1, total: ladder.length, label: candidate.label });
      const measured = preview.measureWithProbe(candidate.css);
      if (!measured) break;
      const fits = measured.usedHeight <= measured.pageContentHeight + 0.5;
      if (!fits) {
        // 让浏览器有机会把「正在试第 N 档」画出来，否则循环会把整段时间占满。
        await new Promise((resolve) => setTimeout(resolve, 0));
        continue;
      }
      setFitting(null);
      try {
        const saved = await updateResumeLayout(resumeId, {
          template: layout.template,
          format_name: layout.format_name,
          page_limit: layout.page_limit,
          font_scale: layout.font_scale,
          // 候选版式只描述"怎么收紧"，把它叠在用户已有的版式覆盖之上——
          // 否则「自动一页」会把用户自己调过的板块顺序等覆盖清掉。
          format_config: { ...layout.format_config, ...candidate.config },
        });
        // 后端只回显它接受的部分；以它为准，别用本地算的值假装成功。
        onApplied(saved.format_config ?? {});
        message.success(`已按「${candidate.label}」收进 ${layout.page_limit} 页`);
      } catch (error) {
        message.error(error instanceof Error ? error.message : "保存版式失败");
      }
      return;
    }

    setFitting(null);
    // 收到底也放不下时必须如实说，并把用户指向下一条真正有用的建议。
    message.warning(
      "版式已经收到最紧了，还是放不下。接下来只能精简内容或增加页数——上面「版面诊断」里列了具体怎么做。",
    );
  }, [analysis, layout, message, onApplied, previewRef, resumeId]);

  const diagnosis = analysis?.diagnosis;
  const fitRoom = analysis?.fit_room;

  const suggestions = useMemo(() => diagnosis?.suggestions ?? [], [diagnosis]);

  // 没有实测高度就无从诊断。诊断拿不到、又不溢出时整块不显示——留一个空标题只会让
  // 用户以为功能坏了。溢出时必须显示：那时兜底提示是唯一告诉他"塞不下"的地方。
  // （版面健康时后端会给一条"保持即可"的建议，所以那种情况下卡片是**该显示**的：
  //   它顺手回答了"我现在这份到底行不行"。）
  if (!measure) return null;
  if (!diagnosis && !overflow) return null;

  return (
    <div className="resume-diagnosis">
      <div className="resume-diagnosis-head">
        <Space size={8} wrap>
          <Typography.Text strong>版面诊断</Typography.Text>
          {analyzing && <Spin size="small" />}
          {diagnosis && (
            <>
              <Tag color={STATUS_COLORS[diagnosis.status]}>{diagnosis.status_label}</Tag>
              <Typography.Text type="secondary">
                占用 {Math.round(diagnosis.fill * 100)}%
              </Typography.Text>
            </>
          )}
        </Space>
        {diagnosis?.status === "overflow" && (analysis?.fit_ladder.length ?? 0) > 0 && (
          <Button
            size="small"
            type="primary"
            loading={fitting !== null}
            disabled={disabled}
            onClick={() => void autoFit()}
          >
            自动一页
          </Button>
        )}
      </div>

      {fitting && (
        <Typography.Text type="secondary" className="resume-diagnosis-progress">
          正在试第 {fitting.index}/{fitting.total} 档：{fitting.label}
        </Typography.Text>
      )}

      {diagnosis && (
        <Typography.Paragraph className="resume-diagnosis-summary">
          {diagnosis.summary}
        </Typography.Paragraph>
      )}

      {/* 诊断接口不可用（后端一时不可达等）时，至少把"塞不下"这件事说出来——
          只是静默地不显示面板，用户会以为版面没问题。 */}
      {!diagnosis && overflow && (
        <Alert
          type="warning"
          showIcon
          className="resume-diagnosis-floor"
          message={`内容超出了 ${layout.page_limit} 页：预览已经整体缩小，字会偏小。暂时读不到详细诊断，可以稍后重试。`}
        />
      )}

      {suggestions.length > 0 && (
        <ol className="resume-diagnosis-list">
          {suggestions.map((item) => (
            <li key={item.kind}>
              <Typography.Text strong>{item.title}</Typography.Text>
              <Typography.Text type="secondary"> — {item.detail}</Typography.Text>
            </li>
          ))}
        </ol>
      )}

      {fitRoom && diagnosis?.status === "overflow" && (
        <Alert
          type="info"
          showIcon
          className="resume-diagnosis-floor"
          message={fitRoom.font_floor_note}
          action={
            layout.page_limit < 3 && (
              <Button size="small" disabled={disabled || fitting !== null} onClick={onAddPage}>
                增加到 {layout.page_limit + 1} 页
              </Button>
            )
          }
        />
      )}
    </div>
  );
}

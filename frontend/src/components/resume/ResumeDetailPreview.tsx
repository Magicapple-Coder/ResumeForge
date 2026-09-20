/**
 * 简历详情预览（B3）：简历中心与「生成简历」预览阶段共用的统一界面。
 *
 * 此前同一套预览有两份实现（`ResumeDetailModal` 的完整预览、`GenerateResumeModal` 的
 * preview 阶段各写一遍），按钮、诊断卡与导出项都各自维护，改一处漏一处。现在把它们
 * 收进这一个组件：头部元信息 Tags + 版式控件（compact）+ 版面诊断卡 + 简历预览 + 底部
 * 完整操作（微调 / 岗位建议 / 查看岗位 / 咨询助手 / 质量检测 / 导出选项 / 一键脱敏 /
 * 离线分享）+ 导出按钮，以及这些操作各自挂载的子弹窗。
 *
 * 只依赖子组件与 `api/resumes`，**不** import `ResumeDetailModal` / `GenerateResumeModal`，
 * 避免循环依赖（设计 §9 ⑨）。
 */
import {
  BulbOutlined,
  EditOutlined,
  ExportOutlined,
  EyeInvisibleOutlined,
  FolderOpenOutlined,
  MessageOutlined,
  SafetyCertificateOutlined,
  ShareAltOutlined,
} from "@ant-design/icons";
import { Button, Space, Tag, Tooltip, Typography } from "antd";
import { useRef, useState } from "react";
import type { ReactNode, RefObject } from "react";
import { useNavigate } from "react-router-dom";
import { RESUME_ENHANCEMENT_LEVELS } from "../../config";
import type { ResumeContent, ResumeDetail, ResumeLayout } from "../../types";
import type { LayoutMeasure } from "../../utils/resumeLayoutMeasure";
import ExportButtons from "../ExportButtons";
import ExportOptionsModal from "../ExportOptionsModal";
import RedactionModal from "../RedactionModal";
import ResumeEditorModal from "../ResumeEditorModal";
import ResumeLayoutControls from "../ResumeLayoutControls";
import ResumeQualityModal from "../ResumeQualityModal";
import ResumeSuggestionsModal from "../ResumeSuggestionsModal";
import SharePackageModal from "../SharePackageModal";
import ResumePreview, { type ResumePreviewHandle } from "../ResumePreview";
import ResumeLayoutDiagnosisCard from "./ResumeLayoutDiagnosisCard";

interface LayoutStatus {
  pages: number;
  scale: number;
  overflow: boolean;
}

interface Props {
  detail: ResumeDetail;
  /** 已渲染的预览 HTML（由父组件负责取数 / 重渲染后传入）。 */
  html: string;
  layout: ResumeLayout;
  layoutStatus: LayoutStatus | null;
  /** 预览量到的实测高度：由预览上报、这里转交给诊断面板。 */
  measure: LayoutMeasure | null;
  pdfDirectAvailable: boolean;
  relayouting: boolean;
  /** 预览句柄：版式控件 / 诊断卡需要用它注入探针 CSS 与量高。 */
  previewRef: RefObject<ResumePreviewHandle>;
  onLayoutStatus: (status: LayoutStatus | null) => void;
  onMeasure: (measure: LayoutMeasure | null) => void;
  onApplyLayout: (next: ResumeLayout) => void;
  /** 「自动一页」试出方案并保存后的重渲染（只重渲染，不再写回版式）。 */
  onApplyFittedFormat: (formatConfig: Record<string, number | string>) => void;
  onSaveEditedResume: (content: ResumeContent) => Promise<void>;
  /** 是否已经生成过岗位优化建议：决定按钮文案是「生成」还是「查看」。 */
  suggestionsGenerated: boolean;
  suggestionsResetKey: number;
  onSuggestionsGenerated: () => void;
  /** 额外操作（如生成弹窗里的「重新生成 / 去简历中心 / 完成」）插在底部按钮区。 */
  extraActions?: ReactNode;
}

export default function ResumeDetailPreview({
  detail,
  html,
  layout,
  layoutStatus,
  measure,
  pdfDirectAvailable,
  relayouting,
  previewRef,
  onLayoutStatus,
  onMeasure,
  onApplyLayout,
  onApplyFittedFormat,
  onSaveEditedResume,
  suggestionsGenerated,
  suggestionsResetKey,
  onSuggestionsGenerated,
  extraActions,
}: Props) {
  const navigate = useNavigate();
  const [editorOpen, setEditorOpen] = useState(false);
  const [editorTarget, setEditorTarget] = useState<string | null>(null);
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const [qualityOpen, setQualityOpen] = useState(false);
  const [exportOptionsOpen, setExportOptionsOpen] = useState(false);
  const [redactionOpen, setRedactionOpen] = useState(false);
  const [sharePackageOpen, setSharePackageOpen] = useState(false);
  // 内部再包一层引用：父组件可能传 null（尚未量到），子组件需要一份稳定的 ref 传入 ResumePreview。
  const fallbackRef = useRef<ResumePreviewHandle>(null);
  const resolvedPreviewRef = previewRef ?? fallbackRef;

  const enhancementLabel = RESUME_ENHANCEMENT_LEVELS.find(
    (item) => item.value === detail.enhancement_level,
  )?.label;

  return (
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
          resumeId={detail.id}
          disabled={relayouting}
          previewRef={resolvedPreviewRef}
          onChange={(next) => onApplyLayout(next)}
        />
        {relayouting && <Typography.Text type="secondary">正在按新版式渲染…</Typography.Text>}
      </div>
      <ResumeLayoutDiagnosisCard
        resumeId={detail.id}
        measure={measure}
        overflow={layoutStatus?.overflow ?? false}
        previewRef={resolvedPreviewRef}
        layout={layout}
        disabled={relayouting}
        onApplied={(formatConfig) => onApplyFittedFormat(formatConfig)}
        onAddPage={() => onApplyLayout({ ...layout, page_limit: layout.page_limit + 1 })}
      />
      <ResumePreview
        ref={resolvedPreviewRef}
        html={html}
        pages={layout.page_limit}
        warnings={detail.warnings}
        onLayoutStatus={onLayoutStatus}
        onMeasure={onMeasure}
        onEditTarget={(path) => {
          setEditorTarget(path);
          setEditorOpen(true);
        }}
      />
      {/* 固定在弹窗底部：内容长（版面诊断 + 预览）时不必一路翻到最后才够得着这些按钮。
          按钮区是 CSS Grid：每个按钮独占一格、block 拉满整格，自动铺满整行不留右侧空当；
          「下载 PDF」主按钮独占底部一整行，保持醒目。 */}
      <div className="resume-detail-footer">
        <Button
          block
          icon={<EditOutlined />}
          onClick={() => {
            setEditorTarget(null);
            setEditorOpen(true);
          }}
        >
          微调内容
        </Button>
        <Button
          block
          icon={<BulbOutlined />}
          disabled={!detail.job_id}
          onClick={() => setSuggestionsOpen(true)}
        >
          {suggestionsGenerated ? "查看岗位优化建议" : "生成岗位优化建议"}
        </Button>
        <Button
          block
          icon={<FolderOpenOutlined />}
          disabled={!detail.job_id}
          onClick={() => detail.job_id && navigate(`/jobs?job_id=${detail.job_id}`)}
        >
          查看对应岗位
        </Button>
        <Button
          block
          icon={<MessageOutlined />}
          onClick={() => navigate(`/assistant?resume_id=${detail.id}&new=1`)}
        >
          咨询求职助手
        </Button>
        <Button block icon={<SafetyCertificateOutlined />} onClick={() => setQualityOpen(true)}>
          质量检测
        </Button>
        <Button block icon={<ExportOutlined />} onClick={() => setExportOptionsOpen(true)}>
          导出选项
        </Button>
        <Button block icon={<EyeInvisibleOutlined />} onClick={() => setRedactionOpen(true)}>
          一键脱敏
        </Button>
        <Button block icon={<ShareAltOutlined />} onClick={() => setSharePackageOpen(true)}>
          离线分享
        </Button>
        <div className="resume-detail-footer-export">
          <ExportButtons recordId={detail.id} pdfDirectAvailable={pdfDirectAvailable} />
        </div>
        {extraActions ? <div className="resume-detail-footer-extra">{extraActions}</div> : null}
      </div>

      <ResumeEditorModal
        open={editorOpen}
        content={detail.content}
        initialTarget={editorTarget}
        // 传 resumeId 才会挂出「写作增强」页签（STAR 量化改写 / 话术生成器 / 多风格润色 /
        // 中英互译）——那几个接口都按简历 id 调。此前这里没传，于是后端与组件都齐了、
        // 界面上却点不到，而 README 与使用指南都写着它可用。
        resumeId={detail.id}
        onClose={() => {
          setEditorOpen(false);
          setEditorTarget(null);
        }}
        onSave={onSaveEditedResume}
      />
      <ResumeSuggestionsModal
        open={suggestionsOpen}
        recordId={detail.id}
        resetKey={suggestionsResetKey}
        onClose={() => setSuggestionsOpen(false)}
        onGenerated={onSuggestionsGenerated}
      />
      <ResumeQualityModal
        open={qualityOpen}
        resumeId={detail.id}
        onClose={() => setQualityOpen(false)}
      />
      <ExportOptionsModal
        recordId={detail.id}
        open={exportOptionsOpen}
        onClose={() => setExportOptionsOpen(false)}
      />
      <RedactionModal
        recordId={detail.id}
        open={redactionOpen}
        onClose={() => setRedactionOpen(false)}
      />
      <SharePackageModal
        recordId={detail.id}
        open={sharePackageOpen}
        onClose={() => setSharePackageOpen(false)}
      />
    </div>
  );
}

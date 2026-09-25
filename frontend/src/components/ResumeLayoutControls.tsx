/** 简历版式控制：样式模板 / 格式模板 / 最大篇幅（页数）/ 字号，生成与预览弹窗共用。 */

import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  PictureOutlined,
  UndoOutlined,
} from "@ant-design/icons";
import { Button, Popover, Segmented, Select, Slider, Space, Tooltip, Typography } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApi } from "../hooks/useApi";
import { fetchResumeTemplates } from "../api/resumes";
import { RESUME_PAGE_LIMITS, type ResumeLayout } from "../types";
import type { ResumePreviewHandle } from "./ResumePreview";
import TemplateGalleryModal from "./resume/TemplateGalleryModal";
import {
  DEFAULT_RESUME_SECTION_ORDER,
  moveSection,
  normalizeSectionOrder,
  RESUME_SECTION_LABELS,
} from "../utils/resumeSectionOrder";
import {
  fontProbeCss,
  fontPxBounds,
  fontTiers,
  layoutForFontPx,
  layoutToFontPx,
  tierByName,
  withFontAdjust,
} from "../utils/resumeFontScale";

/**
 * 拖动字号后多久提交一次（毫秒）。
 *
 * 连续拖动每秒会产生几十个事件，每个都 PATCH + render 会打出几十个请求；而用户真正
 * 想要的"实时手感"由本地探针即时给到，一次往返完全来得及。取 180ms：短到松手后几乎
 * 立刻看到真实渲染，长到足以把一次连续拖动折叠成**一次**提交（比诊断面板的 250ms 略快，
 * 因为这里用户的手指刚离开、对延迟更敏感）。
 */
const FONT_COMMIT_DEBOUNCE_MS = 180;

interface Props {
  layout: ResumeLayout;
  disabled?: boolean;
  onChange: (layout: ResumeLayout) => void;
  /** 紧凑模式：只留控件、不显示分组标签（放在工具栏里时用）。 */
  compact?: boolean;
  /** 用哪份简历做模板预览；为空时后端用内置示例内容。 */
  resumeId?: number;
  /**
   * 预览句柄：拖动字号时用它把探针 CSS 即时注入预览（本地缩放，无网络往返）。
   * 没有预览时（生成前的配置阶段）可省略——滑块仍可用，只是没有即时反馈。
   */
  previewRef?: React.RefObject<ResumePreviewHandle | null>;
}

export default function ResumeLayoutControls({
  layout,
  disabled = false,
  onChange,
  compact = false,
  resumeId,
  previewRef,
}: Props) {
  const { data: catalog } = useApi(fetchResumeTemplates, []);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const templates = catalog?.templates ?? [];
  const formatPresets = catalog?.format_presets ?? [];

  const tiers = useMemo(() => fontTiers(catalog?.font_scales ?? []), [catalog?.font_scales]);
  const pxBounds = useMemo(() => fontPxBounds(tiers), [tiers]);
  const committedPx = layoutToFontPx(layout, tiers);
  // 拖动过程中的即时值：非 null 时覆盖 committedPx，让滑块与读数跟着手指走。
  const [draggingPx, setDraggingPx] = useState<number | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 防抖回调在最后一次拖动之后才跑；用 ref 读"提交那一刻"的 layout，避免这段时间里
  // 父组件改了其它版式（如页数）时被本次字号提交用旧 layout 覆盖回去。
  const layoutRef = useRef(layout);
  layoutRef.current = layout;

  // 布局一被父组件确认（提交成功或外部改动），就交回权威值，避免滑块停在中间态。
  // 用标量签名而不是 layout 对象：父组件每次渲染都新建对象，直接依赖它会不停误触发。
  const fontSignature = `${layout.font_scale}:${layout.format_config?.["font_scale_adjust"] ?? ""}`;
  useEffect(() => {
    setDraggingPx(null);
  }, [fontSignature]);

  // 关掉组件时清掉未触发的提交，避免对已卸载的父组件调用 onChange。
  useEffect(
    () => () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    },
    [],
  );

  const shownPx = draggingPx ?? committedPx;
  const shownPxText = `${Number(shownPx.toFixed(1))}px`;
  const currentTemplate = templates.find((item) => item.name === layout.template);
  const defaultTierLabel = tierByName(tiers, catalog?.defaults.font_scale ?? "standard").label;

  // 正文分区顺序：键与标签由后端下发（改默认值只改一处），归一化在前端做同样的事，
  // 因为控件展示的是"完整排列"，而存储里可能只有用户动过的那几项。
  const defaultSectionOrder = useMemo(
    () => catalog?.default_section_order ?? DEFAULT_RESUME_SECTION_ORDER,
    [catalog?.default_section_order],
  );
  const sectionOptions = useMemo(() => catalog?.section_options ?? [], [catalog?.section_options]);
  const sectionOrder = useMemo(
    () => normalizeSectionOrder(layout.format_config?.section_order, defaultSectionOrder),
    [layout.format_config?.section_order, defaultSectionOrder],
  );
  const isCustomOrder = sectionOrder.join(",") !== defaultSectionOrder.join(",");

  const handleSectionMove = (index: number, direction: -1 | 1) => {
    const next = moveSection(sectionOrder, index, direction);
    if (next === sectionOrder) return;
    onChange({
      ...layout,
      format_config: { ...layout.format_config, section_order: next },
    });
  };

  const handleSectionOrderReset = () => {
    if (!isCustomOrder) return;
    const nextFormatConfig = { ...layout.format_config };
    delete nextFormatConfig.section_order;
    onChange({ ...layout, format_config: nextFormatConfig });
  };

  const handleFontChange = (px: number) => {
    setDraggingPx(px);
    // 即时反馈：直接改预览里的 `--fs`，不外发请求。探针保持到下一次重渲染（iframe 重新
    // 加载时自然销毁），所以从"拖动中的字号"到"最终渲染的字号"之间不会出现跳回旧值的闪动。
    previewRef?.current?.setLiveProbe(fontProbeCss(px));
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null;
      onChange(layoutForFontPx(layoutRef.current, px, tiers));
    }, FONT_COMMIT_DEBOUNCE_MS);
  };

  const resetFont = () => {
    // 恢复默认：回到默认档位，并清掉系数覆盖（保留强调色等其它覆盖）。
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
      debounceRef.current = null;
    }
    previewRef?.current?.setLiveProbe("");
    setDraggingPx(null);
    onChange({
      ...layout,
      font_scale: catalog?.defaults.font_scale ?? "standard",
      format_config: withFontAdjust(layout.format_config, 1),
    });
  };

  return (
    <Space size={compact ? 8 : 16} wrap className="resume-layout-controls">
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">样式</Typography.Text>}
        {/* 选模板与看效果合并成同一个入口：打开的就是"每种模板的真实渲染"，
            点「用这个模板」即写入并重渲染（没有额外确认步骤）。这样就不必先在下拉里
            按名字盲选、再另外点一次「看效果」——选与看是同一件事。 */}
        <Tooltip
          title={
            currentTemplate
              ? `${currentTemplate.description}。点击打开预览，直接看到每种模板的真实效果`
              : "打开模板预览，直接看到每种模板的真实效果"
          }
        >
          <Button
            size="small"
            icon={<PictureOutlined />}
            disabled={disabled || templates.length === 0}
            aria-label="选择简历模板并预览效果"
            onClick={() => setGalleryOpen(true)}
          >
            {currentTemplate?.label ?? layout.template}
            {currentTemplate?.custom ? "（自制）" : ""}
          </Button>
        </Tooltip>
      </Space>
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">版式</Typography.Text>}
        <Tooltip title="版式控制行高、页边距与强调色；可以在工作台里自制更多版式">
          <Select
            size="small"
            value={layout.format_name || ""}
            disabled={disabled}
            style={{ minWidth: 120 }}
            options={[
              { value: "", label: "模板自带" },
              ...formatPresets.map((item) => ({
                value: item.name,
                label: item.custom ? `${item.label}（自制）` : item.label,
                title: item.description,
              })),
            ]}
            onChange={(value) => onChange({ ...layout, format_name: value })}
          />
        </Tooltip>
      </Space>
      <TemplateGalleryModal
        open={galleryOpen}
        layout={layout}
        resumeId={resumeId}
        onSelect={(template) => onChange({ ...layout, template })}
        onClose={() => setGalleryOpen(false)}
      />
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">板块</Typography.Text>}
        <Popover
          trigger="click"
          placement="bottomRight"
          arrow={false}
          title={
            <span className="resume-section-order-title">
              调整板块顺序
              {isCustomOrder && (
                <Button size="small" type="link" onClick={handleSectionOrderReset}>
                  恢复默认
                </Button>
              )}
            </span>
          }
          content={
            <div className="resume-section-order-list" role="list" aria-label="简历板块顺序">
              {sectionOrder.map((key, index) => {
                const label =
                  sectionOptions.find((item) => item.key === key)?.label ??
                  RESUME_SECTION_LABELS[key] ??
                  key;
                return (
                  <div className="resume-section-order-row" role="listitem" key={key}>
                    <span className="resume-section-order-index">{index + 1}</span>
                    <span className="resume-section-order-label">{label}</span>
                    <Space size={0}>
                      <Tooltip title="上移">
                        <Button
                          size="small"
                          type="text"
                          icon={<ArrowUpOutlined />}
                          aria-label={`把${label}上移`}
                          disabled={index === 0}
                          onClick={() => handleSectionMove(index, -1)}
                        />
                      </Tooltip>
                      <Tooltip title="下移">
                        <Button
                          size="small"
                          type="text"
                          icon={<ArrowDownOutlined />}
                          aria-label={`把${label}下移`}
                          disabled={index === sectionOrder.length - 1}
                          onClick={() => handleSectionMove(index, 1)}
                        />
                      </Tooltip>
                    </Space>
                  </div>
                );
              })}
              <Typography.Paragraph type="secondary" className="resume-section-order-hint">
                顺序对预览、PDF、Word
                与文本导出同时生效；页眉（姓名、求职意向、联系方式）固定在最前。
              </Typography.Paragraph>
            </div>
          }
        >
          <Tooltip title="调整个人总结、教育经历、项目经历等板块在简历里的先后顺序">
            <Button size="small" disabled={disabled} aria-label="调整简历板块顺序">
              顺序{isCustomOrder ? "·已调整" : ""}
            </Button>
          </Tooltip>
        </Popover>
      </Space>
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">最大篇幅</Typography.Text>}
        <Tooltip title="简历内容最多排几页 A4；内容少时会自然留白，不会硬撑满">
          <Segmented
            size="small"
            value={layout.page_limit}
            disabled={disabled}
            options={RESUME_PAGE_LIMITS.map((value) => ({
              value,
              label: `${value} 页`,
            }))}
            onChange={(value) => onChange({ ...layout, page_limit: value as number })}
          />
        </Tooltip>
      </Space>
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">字号</Typography.Text>}
        {/* 无级滑块：拖动时本地即时缩放预览，静置 180ms 后才提交一次。落库仍是
            "档位 + 系数"，所以老简历读到的默认值（系数缺省 1.0）完全不受影响。 */}
        <Slider
          className="resume-font-slider"
          min={pxBounds.min}
          max={pxBounds.max}
          step={0.1}
          value={shownPx}
          disabled={disabled}
          aria-label="字号（拖动调整，方向键微调）"
          ariaLabelForHandle="字号"
          tooltip={{ formatter: (value) => (value == null ? "" : `${Number(value.toFixed(1))}px`) }}
          style={{ width: 150, margin: "0 4px" }}
          onChange={handleFontChange}
        />
        <Typography.Text type="secondary" style={{ minWidth: 44, display: "inline-block" }}>
          {shownPxText}
        </Typography.Text>
        <Tooltip title={`恢复默认字号（${defaultTierLabel}）`}>
          <Button
            size="small"
            type="text"
            icon={<UndoOutlined />}
            disabled={disabled}
            aria-label="恢复默认字号"
            onClick={resetFont}
          />
        </Tooltip>
      </Space>
    </Space>
  );
}

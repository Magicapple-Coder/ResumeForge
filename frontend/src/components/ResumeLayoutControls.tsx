/** 简历版式控制：样式模板 / 格式模板 / 最大篇幅（页数）/ 字号，生成与预览弹窗共用。 */

import { PictureOutlined } from "@ant-design/icons";
import { Button, Select, Segmented, Space, Tooltip, Typography } from "antd";
import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { fetchResumeTemplates } from "../api/resumes";
import { RESUME_PAGE_LIMITS, type ResumeLayout } from "../types";
import TemplateGalleryModal from "./resume/TemplateGalleryModal";

interface Props {
  layout: ResumeLayout;
  disabled?: boolean;
  onChange: (layout: ResumeLayout) => void;
  /** 紧凑模式：只留控件、不显示分组标签（放在工具栏里时用）。 */
  compact?: boolean;
  /** 用哪份简历做模板预览；为空时后端用内置示例内容。 */
  resumeId?: number;
}

export default function ResumeLayoutControls({
  layout,
  disabled = false,
  onChange,
  compact = false,
  resumeId,
}: Props) {
  const { data: catalog } = useApi(fetchResumeTemplates, []);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const templates = catalog?.templates ?? [];
  const fontScales = catalog?.font_scales ?? [];
  const formatPresets = catalog?.format_presets ?? [];

  return (
    <Space size={compact ? 8 : 16} wrap className="resume-layout-controls">
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">样式</Typography.Text>}
        <Select
          size="small"
          value={layout.template}
          disabled={disabled || templates.length === 0}
          style={{ minWidth: 150 }}
          options={templates.map((item) => ({
            value: item.name,
            label: item.custom ? `${item.label}（自制）` : item.label,
            // 说明挂在选项上：下拉展开时就能看清每一种的差别。
            title: item.description,
          }))}
          optionRender={(option) => (
            <div>
              <div>{option.label}</div>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {templates.find((item) => item.name === option.value)?.description}
              </Typography.Text>
            </div>
          )}
          onChange={(value) => onChange({ ...layout, template: value })}
        />
        <Tooltip title="逐个查看每种模板的真实渲染效果">
          <Button
            size="small"
            icon={<PictureOutlined />}
            disabled={disabled || templates.length === 0}
            onClick={() => setGalleryOpen(true)}
          >
            看效果
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
        <Segmented
          size="small"
          value={layout.font_scale}
          disabled={disabled || fontScales.length === 0}
          options={
            (fontScales.length > 0
              ? fontScales.map((item) => ({ value: item.name, label: item.label }))
              : [
                  { value: "small", label: "小" },
                  { value: "standard", label: "标准" },
                  { value: "large", label: "大" },
                ]) as { value: string; label: string }[]
          }
          onChange={(value) =>
            onChange({ ...layout, font_scale: value as ResumeLayout["font_scale"] })
          }
        />
      </Space>
    </Space>
  );
}

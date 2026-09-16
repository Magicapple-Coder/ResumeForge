/** 简历版式控制：模板 / 最大篇幅（页数）/ 字号，生成弹窗与预览弹窗共用。 */

import { Select, Segmented, Space, Tooltip, Typography } from "antd";
import { useApi } from "../hooks/useApi";
import { fetchResumeTemplates } from "../api/resumes";
import { RESUME_PAGE_LIMITS, type ResumeLayout } from "../types";

interface Props {
  layout: ResumeLayout;
  disabled?: boolean;
  onChange: (layout: ResumeLayout) => void;
  /** 紧凑模式：只留控件、不显示分组标签（放在工具栏里时用）。 */
  compact?: boolean;
}

export default function ResumeLayoutControls({
  layout,
  disabled = false,
  onChange,
  compact = false,
}: Props) {
  const { data: catalog } = useApi(fetchResumeTemplates, []);
  const templates = catalog?.templates ?? [];
  const fontScales = catalog?.font_scales ?? [];

  return (
    <Space size={compact ? 8 : 16} wrap className="resume-layout-controls">
      <Space size={6}>
        {!compact && <Typography.Text type="secondary">模板</Typography.Text>}
        <Select
          size="small"
          value={layout.template}
          disabled={disabled || templates.length === 0}
          style={{ minWidth: 160 }}
          options={templates.map((item) => ({
            value: item.name,
            label: item.label,
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

/** 统一导出选项：格式多选 + 水印 + 脱敏 + 页边距 / 字号 / 页数 / 照片。 */
import { App, Checkbox, Input, InputNumber, Modal, Select, Space, Switch, Typography } from "antd";
import { useState } from "react";
import { exportResumeWithOptions } from "../api/resumes";
import type { ResumeFontScale } from "../types";
import {
  DEFAULT_REDACTION_OPTIONS,
  EXPORT_FORMATS,
  REDACTION_FIELDS,
  type ExportFormat,
  type RedactionOptions,
} from "../types/export";
import { downloadBlob } from "../utils/download";

interface Props {
  recordId: number;
  open: boolean;
  onClose: () => void;
}

const FONT_SCALE_OPTIONS: { value: ResumeFontScale; label: string }[] = [
  { value: "small", label: "小字号" },
  { value: "standard", label: "标准字号" },
  { value: "large", label: "大字号" },
];

const PAGE_LIMIT_OPTIONS = [
  { value: 1, label: "1 页" },
  { value: 2, label: "2 页" },
  { value: 3, label: "3 页" },
];

export default function ExportOptionsModal({ recordId, open, onClose }: Props) {
  const { message } = App.useApp();
  const [formats, setFormats] = useState<ExportFormat[]>(["pdf"]);
  const [watermarkEnabled, setWatermarkEnabled] = useState(false);
  const [watermark, setWatermark] = useState("");
  const [redact, setRedact] = useState(false);
  const [redactOptions, setRedactOptions] = useState<RedactionOptions>(DEFAULT_REDACTION_OPTIONS);
  const [marginMm, setMarginMm] = useState<number | null>(null);
  const [fontScale, setFontScale] = useState<ResumeFontScale | null>(null);
  const [pageLimit, setPageLimit] = useState<number | null>(null);
  const [includePhoto, setIncludePhoto] = useState(true);
  const [exporting, setExporting] = useState(false);

  const exportAll = async () => {
    if (formats.length === 0) {
      message.warning("请至少选择一种导出格式");
      return;
    }
    if (exporting) return;
    setExporting(true);
    try {
      for (const format of formats) {
        const result = await exportResumeWithOptions(recordId, {
          format,
          watermark: watermarkEnabled ? watermark : "",
          redact,
          redact_options: redact ? redactOptions : undefined,
          margin_mm: marginMm,
          font_scale: fontScale,
          page_limit: pageLimit,
          include_photo: includePhoto,
        });
        downloadBlob(result.blob, result.filename);
        if (result.pages && result.pageLimit && result.pages > result.pageLimit) {
          message.warning(
            `「${format}」共 ${result.pages} 页，超过所选 ${result.pageLimit} 页上限。`,
          );
        }
      }
      message.success("已开始导出");
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出失败");
    } finally {
      setExporting(false);
    }
  };

  return (
    <Modal
      title="导出选项"
      open={open}
      onCancel={onClose}
      okText="导出"
      confirmLoading={exporting}
      onOk={() => void exportAll()}
      width="min(560px, 92vw)"
      destroyOnHidden
    >
      <Space direction="vertical" style={{ width: "100%" }} size="middle">
        <div>
          <Typography.Text strong>格式</Typography.Text>
          <div style={{ marginTop: 8 }}>
            <Checkbox.Group
              options={EXPORT_FORMATS.map((item) => ({ label: item.label, value: item.value }))}
              value={formats}
              onChange={(values) => setFormats(values as ExportFormat[])}
            />
          </div>
        </div>

        <div>
          <Space>
            <Typography.Text strong>水印</Typography.Text>
            <Switch
              checked={watermarkEnabled}
              onChange={setWatermarkEnabled}
              aria-label="开启水印"
            />
          </Space>
          {watermarkEnabled && (
            <Input
              style={{ marginTop: 8 }}
              placeholder="水印文案，例如：内部使用"
              value={watermark}
              onChange={(event) => setWatermark(event.target.value)}
            />
          )}
        </div>

        <div>
          <Space>
            <Typography.Text strong>脱敏</Typography.Text>
            <Switch checked={redact} onChange={setRedact} aria-label="开启脱敏" />
          </Space>
          {redact && (
            <div style={{ marginTop: 8 }}>
              <Checkbox.Group
                options={REDACTION_FIELDS.map((item) => ({ label: item.label, value: item.key }))}
                value={REDACTION_FIELDS.filter((item) => redactOptions[item.key]).map(
                  (item) => item.key,
                )}
                onChange={(values) => {
                  const selected = values as (keyof RedactionOptions)[];
                  const next = {} as RedactionOptions;
                  for (const field of REDACTION_FIELDS) {
                    next[field.key] = selected.includes(field.key);
                  }
                  setRedactOptions(next);
                }}
              />
            </div>
          )}
        </div>

        <div>
          <Typography.Text strong>版式（留空沿用记录）</Typography.Text>
          <Space wrap style={{ marginTop: 8 }}>
            <span>页边距(mm)</span>
            <InputNumber
              min={4}
              max={40}
              placeholder="默认"
              style={{ width: 90 }}
              value={marginMm}
              onChange={(value) => setMarginMm(value)}
            />
            <span>字号</span>
            <Select
              allowClear
              placeholder="默认"
              style={{ width: 110 }}
              value={fontScale}
              options={FONT_SCALE_OPTIONS}
              onChange={(value) => setFontScale((value as ResumeFontScale | null) ?? null)}
            />
            <span>页数</span>
            <Select
              allowClear
              placeholder="默认"
              style={{ width: 90 }}
              value={pageLimit}
              options={PAGE_LIMIT_OPTIONS}
              onChange={(value) => setPageLimit((value as number | null) ?? null)}
            />
          </Space>
          <div style={{ marginTop: 8 }}>
            <Space>
              <Typography.Text>显示照片</Typography.Text>
              <Switch checked={includePhoto} onChange={setIncludePhoto} aria-label="显示照片" />
            </Space>
          </div>
        </div>
      </Space>
    </Modal>
  );
}

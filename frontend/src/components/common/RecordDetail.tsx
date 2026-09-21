/**
 * 通用「卡片 → 详情」能力：列表卡片点一下就能看全字段。
 *
 * 为什么单独抽一份：内推、资料箱、面经、提醒、知识库这些卡片都只放得下摘要，各家自己
 * 写一遍详情会得到五种不一致的排版与五种不一致的关闭方式。这里统一成「右侧抽屉 + 字段
 * 表 + 正文区」，调用方只负责给字段。
 *
 * 卡片整块可点，但**不能**做成 `<button>`：卡片里有「编辑 / 删除」这类按钮，按钮套按钮
 * 是无效 HTML。所以用 `role="button"` + `tabIndex`，并在点击时跳过内层可交互元素，
 * 否则点「删除」会顺带把详情打开了。判定与类型在 `recordDetailCore.ts`。
 */
import { Divider, Drawer, Empty, Space, Typography } from "antd";
import type { ReactNode } from "react";
import { useCallback } from "react";
import type { KeyboardEvent, MouseEvent } from "react";
import { isFromInnerControl } from "./recordDetailCore";
import type { DetailField, DetailSection } from "./recordDetailCore";

export type { DetailField, DetailSection } from "./recordDetailCore";

interface DetailTriggerProps {
  /** 打开详情。 */
  onOpen: () => void;
  /** 卡片里放不下、但读屏需要知道的一句话（例如「打开资料「证书」的详情」）。 */
  label: string;
  className?: string;
  children: ReactNode;
}

/** 可点击卡片：整块可点、可用键盘操作，内层按钮不受影响。 */
export function DetailTrigger({ onOpen, label, className, children }: DetailTriggerProps) {
  const handleClick = (event: MouseEvent<HTMLDivElement>) => {
    if (isFromInnerControl(event)) return;
    onOpen();
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    // 焦点在内层按钮上时，回车/空格归按钮。
    if (isFromInnerControl(event)) return;
    event.preventDefault();
    onOpen();
  };

  const stableClick = useCallback(handleClick, [onOpen]);
  const stableKeyDown = useCallback(handleKeyDown, [onOpen]);

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={label}
      className={`detail-trigger${className ? ` ${className}` : ""}`}
      onClick={stableClick}
      onKeyDown={stableKeyDown}
    >
      {children}
    </div>
  );
}

interface RecordDetailDrawerProps {
  open: boolean;
  title: ReactNode;
  /** 标题下的一行补充信息（公司、时间等）。 */
  subtitle?: ReactNode;
  /** 标题区下方的状态标签。 */
  tags?: ReactNode;
  /** 字段表：一行一项，适合短字段。 */
  fields?: DetailField[];
  /** 长正文区：每条一个分区，适合备注、正文、问题清单。 */
  sections?: DetailSection[];
  /** 底部操作（编辑、删除等）；不传则不显示操作区。 */
  actions?: ReactNode;
  onClose: () => void;
  width?: number;
}

/** 详情抽屉：字段缺失时给出统一占位，不留空行。 */
export function RecordDetailDrawer({
  open,
  title,
  subtitle,
  tags,
  fields = [],
  sections = [],
  actions,
  onClose,
  width = 520,
}: RecordDetailDrawerProps) {
  const visibleFields = fields.filter((field) => field.value !== undefined && field.value !== null);
  const visibleSections = sections.filter((section) => section.content !== undefined);
  const isEmpty = visibleFields.length === 0 && visibleSections.length === 0;

  return (
    <Drawer
      title={title}
      placement="right"
      width={width}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      <Space direction="vertical" size="small" style={{ width: "100%" }}>
        {subtitle && <Typography.Text type="secondary">{subtitle}</Typography.Text>}
        {tags}
      </Space>

      {isEmpty ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="这条记录没有更多内容" />
      ) : (
        <>
          {visibleFields.length > 0 && (
            <div className="record-detail-fields">
              {visibleFields.map((field, index) => (
                <div className="record-detail-field" key={index}>
                  <span className="record-detail-label">{field.label}</span>
                  <div className="record-detail-value">{field.value}</div>
                </div>
              ))}
            </div>
          )}
          {visibleSections.map((section, index) => (
            <div className="record-detail-section" key={index}>
              {(section.title || index > 0) && <Divider style={{ margin: "12px 0" }} />}
              {section.title && (
                <Typography.Title level={5} style={{ marginTop: 0 }}>
                  {section.title}
                </Typography.Title>
              )}
              <div className="record-detail-section-body">{section.content}</div>
            </div>
          ))}
        </>
      )}

      {actions && <div className="record-detail-actions">{actions}</div>}
    </Drawer>
  );
}

export default RecordDetailDrawer;

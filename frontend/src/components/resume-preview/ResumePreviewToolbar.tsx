import {
  DragOutlined,
  EditOutlined,
  ReloadOutlined,
  ZoomInOutlined,
  ZoomOutOutlined,
} from "@ant-design/icons";
import { Button, Segmented, Space, Tooltip, Typography } from "antd";
import type { Dispatch, RefObject, SetStateAction } from "react";
import type { InteractionMode } from "./config";

interface Props {
  canEdit: boolean;
  /**
   * 「正指向」提示的占位元素。
   *
   * 它的内容由 ResumePreview 在 iframe 的 mousemove 里**直接更新**（不经过 React 状态）：
   * 事件监听器挂在 iframe 文档上，而回调随父组件重渲染每次都是新引用，若把 hover 放进
   * React 状态，"hover 生效 → 父重渲染 → 绑定 effect 重跑 → cleanup 清空"会形成振荡
   * （实测 hover 一生效就被清掉）。
   */
  hoverChipRef: RefObject<HTMLSpanElement>;
  onRewriteHoverTarget?: (path: string) => void;
  interactionMode: InteractionMode;
  scale: number;
  onInteractionModeChange: Dispatch<SetStateAction<InteractionMode>>;
  onAdjustZoom: (delta: number) => void;
  onResetZoom: () => void;
}

export default function ResumePreviewToolbar({
  canEdit,
  hoverChipRef,
  onRewriteHoverTarget,
  interactionMode,
  scale,
  onInteractionModeChange,
  onAdjustZoom,
  onResetZoom,
}: Props) {
  return (
    <div className="resume-preview-toolbar">
      <Space size={8} wrap>
        {canEdit && (
          <Segmented
            size="small"
            aria-label="简历预览交互模式"
            value={interactionMode}
            onChange={(value) => onInteractionModeChange(value as InteractionMode)}
            options={[
              {
                value: "pan",
                label: <Tooltip title="按住拖动浏览简历">抓手</Tooltip>,
                icon: <DragOutlined />,
              },
              {
                value: "edit",
                label: <Tooltip title="点击简历中的字段直接修改">编辑</Tooltip>,
                icon: <EditOutlined />,
              },
            ]}
          />
        )}
        <Tooltip title="缩小预览">
          <Button
            type="text"
            size="small"
            aria-label="缩小预览"
            icon={<ZoomOutOutlined />}
            onClick={() => onAdjustZoom(-0.1)}
          />
        </Tooltip>
        <Typography.Text type="secondary" className="resume-preview-zoom-label">
          {Math.round(scale * 100)}%
        </Typography.Text>
        <Tooltip title="放大预览">
          <Button
            type="text"
            size="small"
            aria-label="放大预览"
            icon={<ZoomInOutlined />}
            onClick={() => onAdjustZoom(0.1)}
          />
        </Tooltip>
        <Tooltip title="适应页面（重置缩放）">
          <Button
            type="text"
            size="small"
            aria-label="适应页面"
            icon={<ReloadOutlined />}
            onClick={onResetZoom}
          />
        </Tooltip>
        {/* 快捷键提示：Ctrl+滚轮缩放早已实现，但没有任何地方告诉用户——用户只能一个个
            按钮试。常驻在缩放控件旁边而不是做成一次性引导，因为"想放大看一眼"随时会发生。 */}
        {/* 默认隐藏：iframe 的 mousemove 直接改它的文本与显隐（见 hoverChipRef 注释）。
            按钮点击时从 data-path 读"当前指向"，保证改的就是用户刚指的那一栏。 */}
        <span ref={hoverChipRef} className="resume-preview-hover-chip" style={{ display: "none" }}>
          <span className="resume-preview-hover-label" />
          <Button
            size="small"
            type="primary"
            ghost
            onClick={() => onRewriteHoverTarget?.(hoverChipRef.current?.dataset.path ?? "")}
          >
            让 AI 改这一栏
          </Button>
        </span>
        <Typography.Text type="secondary" className="resume-preview-zoom-hint">
          按住 Ctrl 滚滚轮可缩放
        </Typography.Text>
      </Space>
    </div>
  );
}

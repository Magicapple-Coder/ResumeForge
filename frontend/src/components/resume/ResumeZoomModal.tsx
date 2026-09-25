/**
 * 「查看大图」：把简历放到一个大窗口里按 1:1 看。
 *
 * 为什么不复用外面的预览：外面那份为了塞进列表页，视口高度只有几百像素、还带缩放，
 * "这一页到底排得满不满、分页在哪"看不清。这里换一个大视口重新量一次，页面就是原尺寸。
 *
 * 复用同一个 `ResumePreview` 组件（而不是再写一个渲染器）是刻意的：两份实现迟早会在
 * 分页、缩放、编辑定位这些细节上分叉，而"看到的和导出的一致"正是这一块的全部意义。
 */
import { CloseOutlined, DownloadOutlined } from "@ant-design/icons";
import { Button, Modal, Space, Typography } from "antd";
import ResumePreview, { type ResumePreviewHandle } from "../ResumePreview";

interface Props {
  open: boolean;
  html: string;
  warnings: string[];
  /** 与记录里的页数上限一致；预览里那几根虚线就是按它切的。 */
  pages: number;
  onClose: () => void;
  onEditTarget: (path: string) => void;
  /** 把字段路径翻译成人话栏名，用于工具栏上的"正指向"提示。 */
  describePath?: (path: string) => string;
  onExport?: () => void;
  previewRef?: React.Ref<ResumePreviewHandle>;
}

export default function ResumeZoomModal({
  open,
  html,
  warnings,
  pages,
  onClose,
  onEditTarget,
  describePath,
  onExport,
  previewRef,
}: Props) {
  return (
    <Modal
      title="查看简历大图"
      open={open}
      onCancel={onClose}
      footer={null}
      width="min(1240px, 96vw)"
      styles={{ body: { paddingTop: 8 } }}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>
        按原始尺寸显示，虚线是分页位置（与当前 {pages} 页的设置一致）。缩放用工具栏， 也可以按住
        Ctrl 滚滚轮。
      </Typography.Paragraph>
      <div className="resume-zoom-body">
        <ResumePreview
          ref={previewRef}
          html={html}
          pages={pages}
          warnings={warnings}
          // 视角更大：占满窗口高度，页面就能以 1:1 显示（不必再缩到 0.x 倍）。
          height={Math.round(window.innerHeight * 0.72)}
          describePath={describePath}
          onEditTarget={onEditTarget}
        />
      </div>
      <Space className="resume-zoom-footer">
        {onExport ? (
          <Button icon={<DownloadOutlined />} onClick={onExport}>
            导出
          </Button>
        ) : null}
        <Button icon={<CloseOutlined />} onClick={onClose}>
          关闭
        </Button>
      </Space>
    </Modal>
  );
}

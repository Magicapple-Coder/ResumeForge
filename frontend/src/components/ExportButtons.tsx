/** 导出按钮组：直接下载 PDF（服务端生成）/ 浏览器打印 / HTML / Markdown / JSON。 */
import { DownloadOutlined, PrinterOutlined } from "@ant-design/icons";
import { App, Button, Dropdown, Space, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { useState } from "react";
import { ApiError } from "../api/client";
import { exportResume, fetchResumeHtml } from "../api/resumes";
import { downloadBlob, printHtml } from "../utils/download";

/**
 * 浏览器打印路径的诚实提示。
 *
 * **为什么只能给提示、不能在应用内消除差异**：屏幕上的近似分页是预览用 CSS `columns`
 * 排出来的估算；而「浏览器打印 / 另存为 PDF」走的是 `@media print` 的 `break-inside: avoid`，
 * 页断点可能与屏幕不同（预览说一页、打印可能两页）。浏览器不向 JS 暴露打印页数，所以应用
 * 无法在内部算出真实打印页数，只能就地说明"打印是权威、屏幕是近似"。
 */
export const PRINT_PAGINATION_NOTE =
  "打印 / 另存为 PDF 的分页以浏览器为准，可能与屏幕近似分页略有不同。";

interface Props {
  recordId: number;
  /** 服务端是否找到中文字体；为 false 时主按钮退回浏览器打印。 */
  pdfDirectAvailable?: boolean;
}

export default function ExportButtons({ recordId, pdfDirectAvailable = true }: Props) {
  const { message, modal } = App.useApp();
  const [downloading, setDownloading] = useState(false);

  /**
   * 导出被"正文还有未完成标记"拦下时（409），问一次是否仍要导草稿。
   *
   * 拦下不等于堵死：用户确实只想导一份草稿自查时得有出路。写成通用包装是因为
   * 四种格式和打印都会撞到这条闸门，各写一遍迟早漏掉一个。
   */
  const runExport = async <T,>(
    run: (allowIncomplete: boolean) => Promise<T>,
  ): Promise<T | null> => {
    try {
      return await run(false);
    } catch (err) {
      if (!(err instanceof ApiError) || err.status !== 409) throw err;
      const proceed = await new Promise<boolean>((resolve) => {
        modal.confirm({
          title: "简历里还有未完成标记",
          content: err.message,
          okText: "仍要导出草稿",
          cancelText: "我去改简历",
          onOk: () => resolve(true),
          onCancel: () => resolve(false),
        });
      });
      if (!proceed) return null;
      return await run(true);
    }
  };

  /** 直接下载 PDF：服务端用 fpdf2 + 系统中文字体排版，不需要打开打印窗口。 */
  const downloadPdf = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const result = await runExport((allowIncomplete) =>
        exportResume(recordId, "pdf", allowIncomplete),
      );
      if (result === null) return; // 用户选择先去改简历
      const { blob, filename, pages, pageLimit } = result;
      downloadBlob(blob, filename);
      if (pages && pageLimit && pages > pageLimit) {
        // 内容放不下时服务端宁可多出一页也不裁字，所以页数可能多于用户选的上限。
        // 之前这种情况只在服务端日志里，用户下载完才发现版式跟预览不一样。
        message.warning(
          `PDF 共 ${pages} 页，超过你选择的 ${pageLimit} 页上限：服务端排版不裁内容，` +
            "放不下就顺延。想要和预览完全一致的版式，请用「浏览器打印 / 另存为 PDF」。",
        );
      } else {
        message.success("PDF 已开始下载");
      }
    } catch (err) {
      message.error(
        err instanceof Error
          ? `${err.message}（可以改用「浏览器打印 / 另存为 PDF」）`
          : "下载 PDF 失败，请改用浏览器打印",
      );
    } finally {
      setDownloading(false);
    }
  };

  /** 浏览器打印：版式与预览同源（同一模板 + 同一 --fit-scale），但分页受 @media print 的
   *  break-inside: avoid 影响，可能与屏幕近似分页略有不同——浏览器不向 JS 暴露打印页数，
   *  应用内无法消除这个差异，只能在下拉项上提示一句（见 PRINT_PAGINATION_NOTE）。 */
  const printPdf = async () => {
    try {
      const html = await runExport((allowIncomplete) => fetchResumeHtml(recordId, allowIncomplete));
      if (html === null) return;
      printHtml(html);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "打开打印窗口失败");
    }
  };

  /** 下载文件（HTML / Markdown / JSON） */
  const exportFile = async (format: "html" | "md" | "json") => {
    try {
      const result = await runExport((allowIncomplete) =>
        exportResume(recordId, format, allowIncomplete),
      );
      if (result === null) return;
      downloadBlob(result.blob, result.filename);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出失败");
    }
  };

  const menuItems: MenuProps["items"] = [
    {
      key: "pdf-print",
      label: <span title={PRINT_PAGINATION_NOTE}>浏览器打印 / 另存为 PDF</span>,
      icon: <PrinterOutlined />,
    },
    ...(pdfDirectAvailable ? [{ key: "pdf-download", label: "直接下载 PDF" }] : []),
    { key: "html", label: "导出 HTML" },
    { key: "md", label: "导出 Markdown" },
    { key: "json", label: "导出 JSON" },
  ];

  const onMenuClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "pdf-download") void downloadPdf();
    if (key === "pdf-print") void printPdf();
    if (key === "html" || key === "md" || key === "json") void exportFile(key);
  };

  return (
    <Space>
      {pdfDirectAvailable ? (
        <Tooltip title="服务端直接生成，不用打开打印窗口。它用自己的一套排版（强调色跟随所选模板），版式与预览不逐像素一致；想要和预览完全一样，请用「浏览器打印 / 另存为 PDF」">
          <Button
            type="primary"
            icon={<DownloadOutlined />}
            loading={downloading}
            onClick={() => void downloadPdf()}
          >
            下载 PDF
          </Button>
        </Tooltip>
      ) : (
        <Tooltip title="系统里没有找到中文字体，PDF 由浏览器打印生成">
          <Button type="primary" icon={<PrinterOutlined />} onClick={() => void printPdf()}>
            打印 / 另存为 PDF
          </Button>
        </Tooltip>
      )}
      <Dropdown menu={{ items: menuItems, onClick: onMenuClick }}>
        <Button>更多格式</Button>
      </Dropdown>
    </Space>
  );
}

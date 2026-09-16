/** 导出按钮组：直接下载 PDF（服务端生成）/ 浏览器打印 / HTML / Markdown / JSON。 */
import { DownloadOutlined, PrinterOutlined } from "@ant-design/icons";
import { App, Button, Dropdown, Space, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { useState } from "react";
import { exportResume, fetchResumeHtml } from "../api/resumes";
import { downloadBlob, printHtml } from "../utils/download";

interface Props {
  recordId: number;
  /** 服务端是否找到中文字体；为 false 时主按钮退回浏览器打印。 */
  pdfDirectAvailable?: boolean;
}

export default function ExportButtons({ recordId, pdfDirectAvailable = true }: Props) {
  const { message } = App.useApp();
  const [downloading, setDownloading] = useState(false);

  /** 直接下载 PDF：服务端用 fpdf2 + 系统中文字体排版，不需要打开打印窗口。 */
  const downloadPdf = async () => {
    if (downloading) return;
    setDownloading(true);
    try {
      const { blob, filename } = await exportResume(recordId, "pdf");
      downloadBlob(blob, filename);
      message.success("PDF 已开始下载");
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

  /** 浏览器打印：版式与预览完全一致，用户在打印对话框里选「另存为 PDF」。 */
  const printPdf = async () => {
    try {
      printHtml(await fetchResumeHtml(recordId));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "打开打印窗口失败");
    }
  };

  /** 下载文件（HTML / Markdown / JSON） */
  const exportFile = async (format: "html" | "md" | "json") => {
    try {
      const { blob, filename } = await exportResume(recordId, format);
      downloadBlob(blob, filename);
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出失败");
    }
  };

  const menuItems: MenuProps["items"] = [
    { key: "pdf-print", label: "浏览器打印 / 另存为 PDF", icon: <PrinterOutlined /> },
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
        <Button
          type="primary"
          icon={<DownloadOutlined />}
          loading={downloading}
          onClick={() => void downloadPdf()}
        >
          下载 PDF
        </Button>
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

/** 导出按钮组：PDF（浏览器打印）/ HTML / Markdown / JSON。 */
import { DownloadOutlined } from "@ant-design/icons";
import { App, Button, Dropdown, Space } from "antd";
import type { MenuProps } from "antd";
import { exportResume, fetchResumeHtml } from "../api/resumes";
import { downloadBlob, printHtml } from "../utils/download";

interface Props {
  recordId: number;
}

export default function ExportButtons({ recordId }: Props) {
  const { message } = App.useApp();

  /** 导出 PDF：打开 HTML 并调起浏览器打印（浏览器"另存为 PDF"） */
  const exportPdf = async () => {
    try {
      printHtml(await fetchResumeHtml(recordId));
    } catch (err) {
      message.error(err instanceof Error ? err.message : "导出 PDF 失败");
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
    { key: "pdf", label: "导出 PDF（浏览器打印）" },
    { key: "html", label: "导出 HTML" },
    { key: "md", label: "导出 Markdown" },
    { key: "json", label: "导出 JSON" },
  ];

  const onMenuClick: MenuProps["onClick"] = ({ key }) => {
    if (key === "pdf") void exportPdf();
    if (key === "html" || key === "md" || key === "json") void exportFile(key);
  };

  return (
    <Space>
      <Button type="primary" icon={<DownloadOutlined />} onClick={() => void exportPdf()}>
        导出 PDF
      </Button>
      <Dropdown menu={{ items: menuItems, onClick: onMenuClick }}>
        <Button>更多格式</Button>
      </Dropdown>
    </Space>
  );
}

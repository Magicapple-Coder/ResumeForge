/**
 * 软件更新：对比本地版本与 GitHub 最新发布，说明怎么更新。
 *
 * 只做「检查」：下载与替换由 `update.cmd` / `scripts/Update-ResumeForge.ps1` 完成——
 * 应用自己替换正在运行的文件既不可靠也不安全。
 */

import { CloudDownloadOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Descriptions, Space, Spin, Typography } from "antd";
import { useState } from "react";
import { checkForUpdate } from "../../api/settings";
import type { UpdateCheckResult } from "../../types";

export default function UpdateCard() {
  const [result, setResult] = useState<UpdateCheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");

  const check = async (refresh: boolean) => {
    if (checking) return;
    setChecking(true);
    setError("");
    try {
      setResult(await checkForUpdate(refresh));
    } catch (err) {
      setError(err instanceof Error ? err.message : "检查更新失败");
    } finally {
      setChecking(false);
    }
  };

  return (
    <Card title="软件更新" className="settings-card">
      <Typography.Paragraph type="secondary" style={{ marginBottom: 16 }}>
        更新只替换程序文件，不会动 <code>data/</code>{" "}
        里的数据（岗位、简历、助手对话、设置都在那里）。
        更新前建议先在下方「数据集与备份」里导出一份备份。
      </Typography.Paragraph>
      <Descriptions size="small" column={1} style={{ marginBottom: 12 }}>
        <Descriptions.Item label="更新方式">
          在项目目录双击运行 <code>update.cmd</code>（Windows）；其它系统按 README
          的「升级」一节手动更新依赖与代码。
        </Descriptions.Item>
        <Descriptions.Item label="当前版本">
          {result?.current_version || "点击下方按钮获取"}
        </Descriptions.Item>
      </Descriptions>

      <Space wrap>
        <Button
          type="primary"
          icon={<CloudDownloadOutlined />}
          loading={checking}
          onClick={() => void check(true)}
        >
          检查更新
        </Button>
        {result && (
          <Button icon={<ReloadOutlined />} disabled={checking} onClick={() => void check(true)}>
            重新检查
          </Button>
        )}
      </Space>

      {checking && !result && <Spin style={{ marginTop: 16 }} />}
      {error && <Alert style={{ marginTop: 16 }} type="error" showIcon message={error} />}
      {result && (
        <Alert
          style={{ marginTop: 16 }}
          type={result.update_available ? "success" : "info"}
          showIcon
          message={result.message || "检查完成"}
          description={
            <Space direction="vertical" size={4} style={{ width: "100%" }}>
              {result.latest_version && <span>最新版本：{result.latest_version}</span>}
              {result.published_at && <span>发布时间：{result.published_at.slice(0, 10)}</span>}
              {result.notes && (
                <Typography.Paragraph
                  style={{
                    margin: 0,
                    whiteSpace: "pre-wrap",
                    maxHeight: 200,
                    overflowY: "auto",
                    overflowX: "hidden",
                  }}
                >
                  {result.notes}
                </Typography.Paragraph>
              )}
              {result.release_url && (
                <Typography.Link
                  href={result.release_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  打开发布页面
                </Typography.Link>
              )}
            </Space>
          }
        />
      )}
    </Card>
  );
}

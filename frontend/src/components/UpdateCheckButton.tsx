/**
 * 侧栏页脚右侧的「检查更新」按钮。
 *
 * 为什么要有它：检查更新原来只藏在「设置 → 软件更新」里，而"我这是不是最新版"是用户
 * 偶尔会想一下、但不值得专门进设置页的问题。放在左下角与「使用指南」并排，随手可点。
 *
 * 它**只做检查**，不做下载与安装——那两件事涉及覆盖程序文件，必须在设置页里、由用户
 * 看到版本说明后确认。这里有更新时给出的动作是「去设置页」，而不是直接开始下载。
 *
 * 三种结果都如实说：有新版本（带跳转）、已是最新、检查失败（后端已把 403/限流/网络
 * 各自的原因写进 message，这里原样转达，不吞掉）。
 */
import { SyncOutlined } from "@ant-design/icons";
import { App, Button, Tooltip } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { checkForUpdate } from "../api/settings";

interface Props {
  /** 紧凑的折叠侧栏里只留图标（按钮本身就是图标，这里控制尺寸）。 */
  label?: string;
}

export default function UpdateCheckButton({ label }: Props) {
  const { message } = App.useApp();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(false);

  const check = async () => {
    if (checking) return;
    setChecking(true);
    try {
      // refresh=true：用户主动点就是要当下的结果，不吃 15 分钟的缓存。
      const result = await checkForUpdate(true);
      if (!result.update_available) {
        message.success(result.message || `已是最新版本（${result.current_version}）`);
        return;
      }
      message.open({
        type: "info",
        duration: 8,
        content: (
          <span>
            有新版本 {result.latest_version}。
            <Button
              type="link"
              size="small"
              style={{ paddingInline: 4 }}
              onClick={() => navigate("/settings")}
            >
              去设置页更新
            </Button>
          </span>
        ),
      });
    } catch (error) {
      message.warning(error instanceof Error ? error.message : "检查更新失败");
    } finally {
      setChecking(false);
    }
  };

  return (
    <Tooltip title={checking ? "正在检查更新…" : "检查更新"}>
      <Button
        className="app-update-button"
        type="text"
        icon={<SyncOutlined spin={checking} />}
        disabled={checking}
        onClick={() => void check()}
        aria-label="检查更新"
      >
        {label ? <span className="app-update-label">{label}</span> : null}
      </Button>
    </Tooltip>
  );
}

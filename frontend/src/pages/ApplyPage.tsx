/**
 * 投递台：投递队列、自动采集、执行进度与投递记录。
 *
 * 页面只负责编排（谁在跑、把任务交给进度面板），具体交互拆在 `components/apply/` 下的子组件里。
 * 执行采用**轮询**模型：`useTaskPolling` 按 1.5s 拉取批次详情，任务进入终态后自动停止。
 */
import { SettingOutlined } from "@ant-design/icons";
import { App, Button, Space, Tabs, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";
import {
  getCollectTaskDetail,
  getCurrentTask,
  getTaskDetail,
  pauseTask,
  resumeTask,
  stopTask,
} from "../api/apply";
import { listJobs } from "../api/jobs";
import { listTracks } from "../api/tracker";
import ReferralPanel from "../components/ReferralPanel";
import ApplyProgressPanel from "../components/apply/ApplyProgressPanel";
import ApplyQueuePanel from "../components/apply/ApplyQueuePanel";
import ApplyRecordsPanel from "../components/apply/ApplyRecordsPanel";
import ApplySettingsModal from "../components/apply/ApplySettingsModal";
import BrowserStatusBar from "../components/apply/BrowserStatusBar";
import CollectPanel from "../components/apply/CollectPanel";
import CollectRecordsPanel from "../components/apply/CollectRecordsPanel";
import CurrentSiteBar from "../components/apply/CurrentSiteBar";
import { isActiveTaskStatus, useTaskPolling } from "../hooks/useTaskPolling";
import type { ApplyTask } from "../types";

export default function ApplyPage() {
  const { message } = App.useApp();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [task, setTask] = useState<ApplyTask | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("queue");
  const [jobOptions, setJobOptions] = useState<{ value: number; label: string }[]>([]);
  const [trackOptions, setTrackOptions] = useState<{ value: number; label: string }[]>([]);

  // 内推面板需要绑定岗位 / 漏斗，这里拉取可选项；失败静默，不影响投递台本身。
  useEffect(() => {
    listJobs({ page_size: 100 })
      .then((page) =>
        setJobOptions(
          page.items.map((job) => ({
            value: job.id,
            label: `${job.title}${job.company ? ` · ${job.company}` : ""}`,
          })),
        ),
      )
      .catch(() => setJobOptions([]));
    listTracks({})
      .then((trackList) =>
        setTrackOptions(
          trackList.items.map((track) => ({
            value: track.id,
            label: `${track.company} · ${track.title}`,
          })),
        ),
      )
      .catch(() => setTrackOptions([]));
  }, []);

  // 首屏恢复：应用重启或切页回来时，若仍有进行中的投递任务，直接接着显示进度。
  useEffect(() => {
    let cancelled = false;
    void getCurrentTask()
      .then((current) => {
        if (!cancelled && current) setTask(current);
      })
      .catch(() => {
        /* 没有进行中的任务或接口不可用时静默即可，不打断页面 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const fetchDetail = useCallback(
    (taskId: number) =>
      task?.kind === "collect" ? getCollectTaskDetail(taskId) : getTaskDetail(taskId),
    [task?.kind],
  );

  const { detail, error, refresh } = useTaskPolling(fetchDetail, task?.id ?? null);

  useEffect(() => {
    if (error) message.error(error);
  }, [error, message]);

  const status = detail?.status ?? task?.status;
  const running = status ? isActiveTaskStatus(status) : false;

  const control = async (action: "pause" | "resume" | "stop") => {
    if (!task) return;
    setBusy(true);
    try {
      const handler = action === "pause" ? pauseTask : action === "resume" ? resumeTask : stopTask;
      const updated = await handler(task.id);
      setTask(updated);
      await refresh();
    } catch (err) {
      message.error(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const adoptTask = (created: ApplyTask) => setTask(created);

  return (
    <div className="apply-page">
      <div className="apply-page-head">
        <Space direction="vertical" size={0}>
          <Typography.Title level={4} style={{ margin: 0 }}>
            投递台
          </Typography.Title>
          <Typography.Text type="secondary">
            采集岗位 → 判断匹配度 → 显式确认 → 自动投递。所有对招聘网站的动作都由你显式发起，
            登录在你自己的浏览器窗口里完成。
          </Typography.Text>
        </Space>
        <Button icon={<SettingOutlined />} onClick={() => setSettingsOpen(true)}>
          投递设置
        </Button>
      </div>

      <CurrentSiteBar />

      <BrowserStatusBar />

      {detail && (
        <ApplyProgressPanel
          task={detail}
          busy={busy}
          onPause={() => void control("pause")}
          onResume={() => void control("resume")}
          onStop={() => void control("stop")}
        />
      )}
      {!detail && task && (
        <Typography.Paragraph type="secondary">正在读取任务进度…</Typography.Paragraph>
      )}

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "queue",
            label: "投递队列",
            children: <ApplyQueuePanel disabled={running} onStarted={adoptTask} />,
          },
          {
            key: "collect",
            label: "自动采集",
            children: (
              <CollectPanel
                disabled={running}
                onStarted={adoptTask}
                collectTask={task?.kind === "collect" ? detail : null}
              />
            ),
          },
          {
            key: "collect-records",
            label: "采集记录",
            // 刷新键拼上"完成时间"：采集一结束它就会变，于是记录页签自己重新拉一次，
            // 不必让用户手动刷新去看刚跑完的那一次。
            children: (
              <CollectRecordsPanel
                disabled={running}
                refreshKey={`${task?.id ?? 0}-${detail?.status ?? ""}-${detail?.finished_at ?? ""}`}
              />
            ),
          },
          {
            key: "records",
            label: "投递记录",
            children: <ApplyRecordsPanel disabled={running} onRetried={adoptTask} />,
          },
          {
            key: "referrals",
            label: "内推",
            children: <ReferralPanel jobOptions={jobOptions} trackOptions={trackOptions} />,
          },
        ]}
      />

      <ApplySettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </div>
  );
}

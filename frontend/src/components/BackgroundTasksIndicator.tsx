/**
 * 页头的「后台任务」入口：正在跑的生成任务 + 进度 + 取消。
 *
 * 为什么需要它：用户点「后台继续」把弹窗关掉之后，界面里就再也没有任何地方能看到
 * "刚才那个生成跑到哪了"——他只能猜。这一块把那件事说清楚：还有几个任务在跑、分别
 * 是什么、进度如何，以及**取消**。
 *
 * 数据来自 `utils/backgroundTasks`（模块级登记表，关掉弹窗也照跑），所以它天然对
 * "换个页面"免疫：任务由登记表追踪，不是由某个组件的生命周期持有。
 */
import { CloseCircleOutlined, LoadingOutlined } from "@ant-design/icons";
import { App, Badge, Button, Popover, Space, Tooltip, Typography } from "antd";
import { useState } from "react";
import { useBackgroundTasks } from "../hooks/useBackgroundTasks";
import { cancelBackgroundTask, type BackgroundTask } from "../utils/backgroundTasks";

/** 一行任务：名称、进度、取消。 */
function TaskRow({ task, onCancel }: { task: BackgroundTask; onCancel: () => void }) {
  const progress = [`已接收 ${task.receivedChars} 字`, task.message].filter(Boolean).join(" · ");
  return (
    <div className="background-task-row">
      <Space size={8} align="start">
        <LoadingOutlined className="background-task-spin" />
        <div>
          <Typography.Text strong className="background-task-label">
            {task.label}
          </Typography.Text>
          <Typography.Text type="secondary" className="background-task-progress">
            {progress || "正在准备…"}
          </Typography.Text>
        </div>
      </Space>
      <Button size="small" danger type="text" icon={<CloseCircleOutlined />} onClick={onCancel}>
        取消
      </Button>
    </div>
  );
}

export default function BackgroundTasksIndicator() {
  const { message } = App.useApp();
  const tasks = useBackgroundTasks();
  const [cancelling, setCancelling] = useState<number | null>(null);

  if (tasks.length === 0) return null;

  const cancel = async (task: BackgroundTask) => {
    if (cancelling !== null) return;
    setCancelling(task.id);
    try {
      await cancelBackgroundTask(task.id);
      message.info(`已取消「${task.label}」`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "取消失败，请稍后重试");
    } finally {
      setCancelling(null);
    }
  };

  // 没有任务时整个入口不渲染（上面已经 return null），所以这里不必再写空态分支。
  const content = (
    <div className="background-tasks-panel">
      {tasks.map((task) => (
        <TaskRow key={task.id} task={task} onCancel={() => void cancel(task)} />
      ))}
      <Typography.Text type="secondary" className="background-tasks-hint">
        关掉窗口也会继续跑，完成后会弹窗提醒并响一声。
      </Typography.Text>
    </div>
  );

  return (
    <Popover content={content} title="正在进行的任务" trigger="click" placement="bottomRight">
      <Tooltip title={`${tasks.length} 个任务正在进行`}>
        <Button className="background-tasks-button" type="text" aria-label="查看后台任务">
          <Badge count={tasks.length} size="small" offset={[2, -2]}>
            <LoadingOutlined /> 后台任务
          </Badge>
        </Button>
      </Tooltip>
    </Popover>
  );
}

/** 订阅后台任务登记表（`utils/backgroundTasks`）的 React 入口。 */
import { useSyncExternalStore } from "react";
import {
  getBackgroundTasks,
  subscribeBackgroundTasks,
  type BackgroundTask,
} from "../utils/backgroundTasks";

/** 当前正在进行的后台任务（完成的会自己从列表里消失）。 */
export function useBackgroundTasks(): BackgroundTask[] {
  return useSyncExternalStore(subscribeBackgroundTasks, getBackgroundTasks, getBackgroundTasks);
}

/** 只看某一个任务；不在了（完成/取消）返回 undefined。 */
export function useBackgroundTask(id: number | null): BackgroundTask | undefined {
  const tasks = useBackgroundTasks();
  if (id === null) return undefined;
  return tasks.find((task) => task.id === id);
}

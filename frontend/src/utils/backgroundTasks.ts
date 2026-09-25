/**
 * 后台任务登记表：让"关掉窗口也继续跑"这件事真的有结果。
 *
 * **为什么需要它**：简历生成的轮询原本写在生成弹窗里（`GenerateResumeModal` 的 useEffect）。
 * 用户点「后台继续（关闭弹窗）」之后组件卸载，**轮询也跟着停了**——任务在后端还在跑，但
 * 前端再也没人去问它结果，于是"完成后会提醒你"成了一句空话（用户反馈"当前后台任务完成后
 * 并没有弹窗和完成音提醒"）。
 *
 * 所以把轮询搬到模块级：进程内的单例，与任何组件生命周期无关。它同时提供两件事：
 * 1. **完成/失败时用统一出口提醒**（弹窗 + 提示音，见 utils/taskNotify）；
 * 2. **一份可订阅的任务列表**，让页头能显示"正在进行的任务 + 进度 + 取消"。
 *
 * 仍然**不跨页面刷新**：浏览器刷新会丢掉这份内存状态。后端任务本身不受影响（它有自己的
 * 记录），只是刷新后不再由前端提示——这一点在界面上没有承诺过"刷新后还能收到通知"。
 */
import { cancelResumeGenerateTask, getResumeGenerateTask } from "../api/resumes";
import type { ResumeGenerateTask, ResumeGenerateTaskStatus } from "../types";
import { notifyTaskDone } from "./taskNotify";

/** 界面要显示的运行时快照（不直接暴露后端原始对象，避免组件依赖它的全部字段）。 */
export interface BackgroundTask {
  id: number;
  /** 人话说明这是谁的任务，例如「为「前端开发」生成简历」。 */
  label: string;
  status: ResumeGenerateTaskStatus;
  /** 后端给的进度文案（"正在写第 2 段…"）。 */
  message: string;
  receivedChars: number;
  resumeId: number | null;
  error: string;
}

type Listener = (tasks: BackgroundTask[]) => void;

/** 轮询间隔：与原来的弹窗内轮询一致，1.5s 足够跟手又不至于太吵。 */
export const POLL_INTERVAL_MS = 1500;

const tasks = new Map<number, BackgroundTask>();
/** 任务终态时要通知谁（弹窗打开时要刷新预览；关掉之后没人需要）。 */
const finishHandlers = new Map<number, (task: BackgroundTask) => void>();
/** 哪些任务当前"有界面在看"，决定完成时是右上角卡片还是居中弹窗。 */
const attached = new Set<number>();
const listeners = new Set<Listener>();
let timer: number | null = null;

// 快照必须有稳定的引用：`useSyncExternalStore` 用 `Object.is` 比较前后值，
// 每次返回新数组会被判成"一直在变"，于是组件无限重渲染（真实踩到过
// "Maximum update depth exceeded"）。内容没变就复用同一个数组。
let cached: BackgroundTask[] = [];
let cacheDirty = true;

function snapshot(): BackgroundTask[] {
  if (cacheDirty) {
    cached = [...tasks.values()];
    cacheDirty = false;
  }
  return cached;
}

function emit(): void {
  cacheDirty = true;
  const current = snapshot();
  for (const listener of listeners) listener(current);
}

function stopPollingIfIdle(): void {
  if (tasks.size > 0 || timer === null) return;
  window.clearInterval(timer);
  timer = null;
}

function ensurePolling(): void {
  if (timer !== null || typeof window === "undefined") return;
  timer = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
}

function isTerminal(status: ResumeGenerateTaskStatus): boolean {
  return status === "completed" || status === "failed" || status === "cancelled";
}

async function tick(): Promise<void> {
  if (tasks.size === 0) {
    stopPollingIfIdle();
    return;
  }
  await Promise.all(
    [...tasks.keys()].map(async (id) => {
      try {
        const latest = await getResumeGenerateTask(id);
        applyUpdate(id, latest);
      } catch {
        // 轮询失败（后端短暂不可用）不打断，等下一轮自愈——与原来的弹窗内轮询同策略。
      }
    }),
  );
}

function applyUpdate(id: number, latest: ResumeGenerateTask): void {
  const existing = tasks.get(id);
  if (!existing) return;
  const next: BackgroundTask = {
    ...existing,
    status: latest.status,
    message: latest.message,
    receivedChars: latest.received_chars,
    resumeId: latest.resume_id,
    error: latest.error,
  };
  tasks.set(id, next);
  emit();
  if (!isTerminal(latest.status)) return;
  finish(id, next);
}

function finish(id: number, task: BackgroundTask): void {
  tasks.delete(id);
  stopPollingIfIdle();
  // **必须 emit**：`applyUpdate` 在调用这里之前已经 emit 过一次（那一次的列表里还有这个
  // 任务），如果删掉之后不再通知，订阅者看到的永远是"任务还在"，而快照缓存也停在旧值上
  // ——页头的任务面板不会消失，`getBackgroundTasks()` 也永远返回它。
  emit();
  const handler = finishHandlers.get(id);
  finishHandlers.delete(id);
  // **先通知，再回调**：即使业务侧的回调抛错（例如取预览失败），用户也该收到"跑完了"这件事。
  const watchers = attached.has(id);
  attached.delete(id);
  if (task.status === "completed") {
    notifyTaskDone({
      // 有界面在看就不要再弹一个居中弹窗打断它；用户已经走了才需要"叫住他"。
      modal: !watchers,
      title: "简历已生成",
      description: "已自动保存到简历中心，可以继续微调或导出。",
      confirmLabel: "知道了",
    });
  } else if (task.status === "failed") {
    notifyTaskDone({
      kind: "error",
      title: "简历生成失败",
      description: task.error || "可以回到简历中心重试。",
    });
  } else {
    notifyTaskDone({ kind: "warning", title: "简历生成已取消" });
  }
  handler?.(task);
}

/**
 * 登记一个正在进行中的生成任务。
 *
 * @param task 后端返回的初始任务（含 id 与状态）
 * @param label 人话说明这是谁的任务
 * @param onFinished 终态回调（用它刷新预览、切界面）；**通知与提示音不在这里做**，
 *   由本模块统一负责，避免"有的地方响、有的地方不响"。
 */
export function watchResumeTask(
  task: ResumeGenerateTask,
  label: string,
  onFinished?: (task: BackgroundTask) => void,
): void {
  tasks.set(task.id, {
    id: task.id,
    label,
    status: task.status,
    message: task.message,
    receivedChars: task.received_chars,
    resumeId: task.resume_id,
    error: task.error,
  });
  if (onFinished) finishHandlers.set(task.id, onFinished);
  ensurePolling();
  emit();
  // 立刻拉一次：刚启动的任务不该等到下一个间隔才有进度。
  void tick();
}

/**
 * 手动推进一轮轮询。
 *
 * 两个用途：测试里不必等真实的 1.5s；以及将来"用户回到页面时立刻刷新一次"这类需求。
 */
export async function tickBackgroundTasks(): Promise<void> {
  await tick();
}

/** 声明"这个任务的界面正开着"；返回 detach。没声明的任务完成时用居中弹窗提醒。 */
export function attachTaskUi(id: number): () => void {
  attached.add(id);
  return () => attached.delete(id);
}

export function getBackgroundTasks(): BackgroundTask[] {
  return snapshot();
}

export function subscribeBackgroundTasks(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 取消一个后台任务（后端会把任务置为取消，且不保存半成品）。 */
export async function cancelBackgroundTask(id: number): Promise<void> {
  const latest = await cancelResumeGenerateTask(id);
  applyUpdate(id, latest);
}

/** 测试与"换数据集"之类场景用：清空登记表。 */
export function resetBackgroundTasks(): void {
  tasks.clear();
  finishHandlers.clear();
  attached.clear();
  stopPollingIfIdle();
  emit();
}

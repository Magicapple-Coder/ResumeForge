/** 日历提醒（后端 /api/reminders）。 */

export const REMINDER_KINDS = ["interview", "assessment_deadline", "hr_reply", "other"] as const;
export type ReminderKind = (typeof REMINDER_KINDS)[number];

export const REMINDER_STATUSES = ["pending", "done", "dismissed"] as const;
export type ReminderStatus = (typeof REMINDER_STATUSES)[number];

export const REMINDER_KIND_LABELS: Record<ReminderKind, string> = {
  interview: "面试",
  assessment_deadline: "测评/笔试截止",
  hr_reply: "催 HR 回复",
  other: "其他",
};

export const REMINDER_STATUS_LABELS: Record<ReminderStatus, string> = {
  pending: "待办",
  done: "已完成",
  dismissed: "已忽略",
};

/** 首页紧急度（与后端 services/reminder_service 唯一实现处保持一致）。 */
export const REMINDER_URGENCIES = ["overdue", "soon", "upcoming", "later"] as const;
export type ReminderUrgency = (typeof REMINDER_URGENCIES)[number];

export const REMINDER_URGENCY_LABELS: Record<ReminderUrgency, string> = {
  overdue: "已逾期",
  soon: "临近",
  upcoming: "即将",
  later: "稍后",
};

export const REMINDER_URGENCY_COLORS: Record<ReminderUrgency, string> = {
  overdue: "red",
  soon: "orange",
  upcoming: "blue",
  later: "default",
};

export interface Reminder {
  id: number;
  title: string;
  /** 提醒时间（ISO 字符串），列表按它升序排"接下来要做什么"。 */
  remind_at: string;
  kind: string;
  status: string;
  track_id: number | null;
  job_id: number | null;
  resume_id: number | null;
  note: string;
  created_at: string;
  updated_at: string;
}

/** 首页待办提醒：在 Reminder 之外补紧急度与展示标签（由后端 /upcoming 计算）。 */
export interface ReminderUpcoming extends Reminder {
  urgency: ReminderUrgency;
  due_label: string;
}

export interface ReminderPayload {
  title: string;
  remind_at: string;
  kind?: ReminderKind;
  status?: ReminderStatus;
  track_id?: number | null;
  job_id?: number | null;
  resume_id?: number | null;
  note?: string;
}

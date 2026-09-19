/** 日历提醒接口。 */
import type { Reminder, ReminderPayload, ReminderUpcoming } from "../types";
import { buildQuery, request } from "./client";

export function listReminders(
  params: { kind?: string; status?: string; limit?: number } = {},
): Promise<Reminder[]> {
  return request(`/reminders${buildQuery(params)}`);
}

export function listUpcomingReminders(limit = 50): Promise<ReminderUpcoming[]> {
  return request(`/reminders/upcoming?limit=${limit}`);
}

export function createReminder(payload: ReminderPayload): Promise<Reminder> {
  return request("/reminders", { method: "POST", body: JSON.stringify(payload) });
}

export function updateReminder(id: number, payload: Partial<ReminderPayload>): Promise<Reminder> {
  return request(`/reminders/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
}

export function deleteReminder(id: number): Promise<void> {
  return request(`/reminders/${id}`, { method: "DELETE" });
}

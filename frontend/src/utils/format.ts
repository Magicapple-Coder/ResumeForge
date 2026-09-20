/** 展示格式化工具。 */

/** 本地当天日期，`YYYY-MM-DD`（与后端 `applied_at` / `status_date` 的格式一致）。
 *
 * 用本地时间而不是 `toISOString()`：后者是 UTC，晚上录的记录会被写成"昨天"。
 * 这里收口成一份实现——`TrackCard` 的逾期判定此前自己手搓了一份同样的拼接。
 */
export function todayIsoDate(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** 后端下发的比率（0..1）转成整数百分比文本，如 `0.3333` → `"33%"`。 */
export function formatRate(value: number | undefined): string {
  if (typeof value !== "number" || Number.isNaN(value)) return "-";
  return `${Math.round(value * 100)}%`;
}

/** 后端 UTC 时间戳转本地时间（如 "2026-08-16 14:30"）。 */
export function formatDateTime(iso: string | undefined): string {
  if (!iso) return "-";
  // 后端为兼容 SQLite 返回无时区标记的 UTC 时间，解析前补上 Z 才能正确转换到本地时区。
  const hasTime = /[T ]\d/.test(iso);
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  const date = new Date(hasTime && !hasTimezone ? `${iso}Z` : iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 展示格式化工具。 */

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

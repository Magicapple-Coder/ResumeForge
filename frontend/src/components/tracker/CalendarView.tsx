/**
 * 真实月历（E11）：按 ``remind_at`` 把提醒归集到月格里，色块/状态区分。
 *
 * 自绘 grid，不引入第三方日历库（前端依赖受控）。数据源 v1 仅提醒（含 done/dismissed
 * 状态），聚合 next_action 留 P1。pending 蓝色、逾期红色、done 绿色、dismissed 灰色。
 *
 * 组件默认自拉 ``listReminders``；传入 ``reminders`` 时用它覆盖（测试 / 父组件已取数时）。
 */
import { LeftOutlined, RightOutlined } from "@ant-design/icons";
import { Button, Empty, Space, Spin, Tag, Tooltip, Typography } from "antd";
import dayjs from "dayjs";
import type { Dayjs } from "dayjs";
import { useMemo, useState } from "react";
import { listReminders } from "../../api/reminders";
import { useApi } from "../../hooks/useApi";
import { REMINDER_KIND_LABELS } from "../../types";
import type { Reminder, ReminderKind } from "../../types";
import { formatDateTime } from "../../utils/format";

interface Props {
  /** 覆盖自拉的数据（测试用）；缺省时组件自己拉 ``listReminders``。 */
  reminders?: Reminder[];
  loading?: boolean;
  /** 紧凑模式：用于首页「近期提醒」卡，只画色点不铺标题。 */
  compact?: boolean;
  onSelectDate?: (date: Dayjs) => void;
}

/** 星期表头：周一开始（国内习惯）。 */
const WEEK_LABELS = ["一", "二", "三", "四", "五", "六", "日"];

/** 提醒在月历上的颜色：状态优先，逾期再单独标红。 */
function reminderColor(reminder: Reminder, now: Dayjs): string {
  if (reminder.status === "done") return "green";
  if (reminder.status === "dismissed") return "default";
  const remindAt = dayjs(reminder.remind_at);
  if (remindAt.isValid() && remindAt.isBefore(now, "day")) return "red";
  return "blue";
}

/** 把某一天的提醒按「逾期 → pending → done → dismissed」排序，紧凑模式只关心有没有。 */
function sortForDay(items: Reminder[]): Reminder[] {
  const rank = (status: string): number =>
    status === "pending" ? 0 : status === "done" ? 2 : status === "dismissed" ? 3 : 1;
  return [...items].sort((a, b) => rank(a.status) - rank(b.status));
}

export default function CalendarView({
  reminders,
  loading: loadingProp,
  compact = false,
  onSelectDate,
}: Props) {
  const [month, setMonth] = useState<Dayjs>(() => dayjs().startOf("month"));
  const { data: fetched, loading: loadingFetched } = useApi(
    () => listReminders({ limit: 500 }),
    [],
  );

  const items = useMemo(() => reminders ?? fetched ?? [], [reminders, fetched]);
  const loading = loadingProp ?? loadingFetched;
  const now = dayjs();

  // 按 remind_at 归集到「YYYY-MM-DD」。同一天可能有多条。
  const byDay = useMemo(() => {
    const map = new Map<string, Reminder[]>();
    for (const reminder of items) {
      const key = dayjs(reminder.remind_at).format("YYYY-MM-DD");
      const bucket = map.get(key) ?? [];
      bucket.push(reminder);
      map.set(key, bucket);
    }
    return map;
  }, [items]);

  // 月历网格：从当月 1 号往前补到周一，一直铺到覆盖整月的最后一天所在的周。
  const cells = useMemo(() => {
    const first = month.startOf("month");
    const daysInMonth = month.daysInMonth();
    // dayjs 的 day()：0=周日 … 6=周六；换算成「周一起始」的偏移。
    const offset = (first.day() + 6) % 7;
    const gridStart = first.subtract(offset, "day");
    const total = offset + daysInMonth;
    const weeks = Math.ceil(total / 7);
    return Array.from({ length: weeks * 7 }, (_, index) => gridStart.add(index, "day"));
  }, [month]);

  const isToday = (date: Dayjs): boolean => date.isSame(now, "day");
  const isCurrentMonth = (date: Dayjs): boolean => date.isSame(month, "month");

  return (
    <div className="calendar-view">
      <div className="calendar-view-head">
        <Space>
          <Button
            size="small"
            icon={<LeftOutlined />}
            aria-label="上个月"
            onClick={() => setMonth((current) => current.subtract(1, "month"))}
          />
          <Typography.Text strong>{month.format("YYYY 年 M 月")}</Typography.Text>
          <Button
            size="small"
            icon={<RightOutlined />}
            aria-label="下个月"
            onClick={() => setMonth((current) => current.add(1, "month"))}
          />
          <Button size="small" onClick={() => setMonth(dayjs().startOf("month"))}>
            回到本月
          </Button>
        </Space>
      </div>

      {loading ? (
        <Spin style={{ display: "block", margin: "24px auto" }} />
      ) : (
        <div className="calendar-view-grid" role="grid">
          {WEEK_LABELS.map((label) => (
            <div key={label} className="calendar-view-weekday" role="columnheader">
              {label}
            </div>
          ))}
          {cells.map((date) => {
            const key = date.format("YYYY-MM-DD");
            const dayItems = sortForDay(byDay.get(key) ?? []);
            const dimmed = !isCurrentMonth(date);
            return (
              <button
                type="button"
                key={key}
                className={`calendar-view-cell${isToday(date) ? " is-today" : ""}${
                  dimmed ? " is-dimmed" : ""
                }`}
                onClick={() => onSelectDate?.(date)}
                aria-label={`${key}${dayItems.length ? `，${dayItems.length} 条提醒` : ""}`}
              >
                <span className="calendar-view-day">{date.date()}</span>
                {compact
                  ? dayItems.length > 0 && (
                      <span className="calendar-view-dots">
                        {dayItems.slice(0, 3).map((item) => (
                          <Tooltip key={item.id} title={item.title}>
                            <Tag
                              color={reminderColor(item, now)}
                              className="calendar-view-dot"
                              aria-hidden
                            >
                              {""}
                            </Tag>
                          </Tooltip>
                        ))}
                      </span>
                    )
                  : dayItems.length > 0 && (
                      <span className="calendar-view-items">
                        {dayItems.slice(0, 2).map((item) => (
                          <Tooltip
                            key={item.id}
                            title={`${formatDateTime(item.remind_at)} · ${
                              REMINDER_KIND_LABELS[item.kind as ReminderKind] ?? item.kind
                            }`}
                          >
                            <span
                              className="calendar-view-item"
                              style={{ borderLeftColor: reminderColor(item, now) }}
                            >
                              {item.title}
                            </span>
                          </Tooltip>
                        ))}
                        {dayItems.length > 2 && (
                          <span className="calendar-view-more">+{dayItems.length - 2}</span>
                        )}
                      </span>
                    )}
              </button>
            );
          })}
        </div>
      )}
      {!loading && items.length === 0 && (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description="这个月还没有提醒，把面试、测评截止这些时点记下来吧"
        />
      )}
    </div>
  );
}

/**
 * 一条进度记录的只读展示。
 *
 * 排序上把「下一步」放在状态旁边：秋招真正会被漏掉的是"9 月 20 日前确认面试时间"
 * 这种带截止时间的事，而不是"我投过这家"。
 */
import { MoreOutlined } from "@ant-design/icons";
import { Button, Dropdown, Space, Tag, Tooltip, Typography } from "antd";
import type { Track } from "../../types";
import {
  TRACK_SOURCE_LABELS,
  TRACK_STATUS_COLORS,
  TRACK_STATUS_LABELS,
  isActiveStatus,
} from "../../types";
import { useRowActionMenu } from "../common/rowActionMenu";

interface Props {
  track: Track;
  onEdit: () => void;
  onDelete: () => void;
}

/** 截止日期是不是已经过了（只看日期，不管当天）。 */
function isOverdue(dateText: string): boolean {
  if (!dateText) return false;
  const today = new Date();
  const stamp = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(
    today.getDate(),
  ).padStart(2, "0")}`;
  return dateText < stamp;
}

export default function TrackCard({ track, onEdit, onDelete }: Props) {
  const buildMenu = useRowActionMenu();
  const overdue = isOverdue(track.next_action_date);

  return (
    <article className={`track-card${isActiveStatus(track.status) ? " is-active" : ""}`}>
      <header className="track-card-head">
        <Space size={6} wrap>
          <Typography.Text strong>{track.company || "（未填公司）"}</Typography.Text>
          <Typography.Text type="secondary">{track.title || "（未填岗位）"}</Typography.Text>
          <Tag color={TRACK_STATUS_COLORS[track.status]}>{TRACK_STATUS_LABELS[track.status]}</Tag>
          {track.stage_note && <Tag>{track.stage_note}</Tag>}
        </Space>
        <Space size={4}>
          <Dropdown
            trigger={["click"]}
            menu={{
              items: buildMenu([
                { key: "edit", label: "编辑", onClick: onEdit },
                {
                  key: "delete",
                  label: "删除",
                  danger: true,
                  confirm: "删除这条进度记录？",
                  onClick: onDelete,
                },
              ]),
            }}
          >
            <Button
              size="small"
              type="text"
              icon={<MoreOutlined />}
              aria-label={`更多操作 ${track.company || track.title || "进度"}`}
            />
          </Dropdown>
        </Space>
      </header>

      <div className="track-card-meta">
        {track.applied_at && (
          <Typography.Text type="secondary">投递于 {track.applied_at}</Typography.Text>
        )}
        {track.status_date && (
          <Typography.Text type="secondary">状态更新 {track.status_date}</Typography.Text>
        )}
        <Tooltip title={TRACK_SOURCE_LABELS[track.source]}>
          <Typography.Text type="secondary">{TRACK_SOURCE_LABELS[track.source]}</Typography.Text>
        </Tooltip>
      </div>

      {(track.next_action || track.next_action_date) && (
        <div className={`track-card-next${overdue ? " is-overdue" : ""}`}>
          <span className="track-card-next-label">下一步</span>
          <span>
            {track.next_action || "（未填写内容）"}
            {track.next_action_date && ` · ${track.next_action_date}`}
            {overdue && " · 已过期"}
          </span>
        </div>
      )}

      {track.note && (
        <Typography.Paragraph className="track-card-note">{track.note}</Typography.Paragraph>
      )}

      {track.evidence && (
        <Typography.Text type="secondary" className="track-card-evidence">
          依据：{track.evidence}
        </Typography.Text>
      )}
    </article>
  );
}

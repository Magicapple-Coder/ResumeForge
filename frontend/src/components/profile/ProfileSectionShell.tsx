/** 个人资料大分区的排序外壳与顺序定义。 */

import { HolderOutlined } from "@ant-design/icons";
import { Tooltip, Typography } from "antd";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";
import { SECTION_LABELS } from "./ProfileSectionConfig";
import type { ProfileSectionKey } from "./ProfileSectionConfig";

export type { ProfileSectionKey } from "./ProfileSectionConfig";

export type ProfileSectionPointerDownHandler = (
  event: ReactPointerEvent<HTMLButtonElement>,
  sectionKey: ProfileSectionKey,
) => void;

interface SortableProfileSectionProps {
  sectionKey: ProfileSectionKey;
  order: number;
  editable: boolean;
  compact: boolean;
  dragOver: boolean;
  onHandlePointerDown: ProfileSectionPointerDownHandler;
  onMoveByOffset: (sectionKey: ProfileSectionKey, offset: -1 | 1) => void;
  children: ReactNode;
}

export function SortableProfileSection({
  sectionKey,
  order,
  editable,
  compact,
  dragOver,
  onHandlePointerDown,
  onMoveByOffset,
  children,
}: SortableProfileSectionProps) {
  return (
    <div
      className={`profile-section-sortable${dragOver ? " is-drag-over" : ""}${
        compact ? " is-section-reordering" : ""
      }`}
      style={{ order }}
      data-profile-section-key={sectionKey}
    >
      {editable && (
        <Tooltip title={`拖动或使用上下方向键调整“${SECTION_LABELS[sectionKey]}”顺序`}>
          <button
            type="button"
            className="profile-section-drag-handle"
            aria-label={`拖动调整${SECTION_LABELS[sectionKey]}顺序`}
            onPointerDown={(event) => onHandlePointerDown(event, sectionKey)}
            onKeyDown={(event) => {
              if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
              event.preventDefault();
              onMoveByOffset(sectionKey, event.key === "ArrowUp" ? -1 : 1);
            }}
          >
            <HolderOutlined />
          </button>
        </Tooltip>
      )}
      {compact && (
        <div className="profile-section-compact-label">
          <Typography.Text strong>{SECTION_LABELS[sectionKey]}</Typography.Text>
          <Typography.Text type="secondary">拖到此处</Typography.Text>
        </div>
      )}
      <div className={`profile-section-content${compact ? " is-collapsed" : ""}`}>{children}</div>
    </div>
  );
}

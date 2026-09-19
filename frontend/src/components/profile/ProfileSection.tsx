/** 资料分区容器：卡片 + 动态列表 + 增删行，各分区共用。 */
import { DeleteOutlined, HolderOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Card, Form, Tooltip, Typography } from "antd";
import type { FormListFieldData, FormListOperation } from "antd/es/form/FormList";
import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent, ReactNode } from "react";

type ProfileListItem = Record<string, unknown>;
const ITEM_DRAG_THRESHOLD_PX = 6;

type ItemLabelFormatter = (item: ProfileListItem, index: number) => string;

interface Props {
  /** 表单字段名（对应 profile 的 educations/experiences/...） */
  fieldName: string;
  /** 只读查看时保留内容，但锁定动态列表操作。 */
  editable?: boolean;
  /** 新增一行的默认值 */
  emptyValue: Record<string, string>;
  /** 行渲染函数 */
  renderRow: (field: FormListFieldData, remove: FormListOperation["remove"]) => ReactNode;
  /** 拖动排序时显示的条目标题，避免用户只能靠长表单位置定位。 */
  itemLabel?: ItemLabelFormatter;
}

interface ProfileListBodyProps extends Omit<Props, "title"> {
  fields: FormListFieldData[];
  operations: FormListOperation;
}

function ProfileListBody({
  fields,
  operations,
  fieldName,
  editable = true,
  emptyValue,
  renderRow,
  itemLabel,
}: ProfileListBodyProps) {
  const form = Form.useFormInstance();
  const [draggingItemKey, setDraggingItemKey] = useState<number | null>(null);
  const [itemReorderMode, setItemReorderMode] = useState(false);
  const [dragOverItemKey, setDragOverItemKey] = useState<number | null>(null);
  const [dragItemLabels, setDragItemLabels] = useState<Record<string, string>>({});
  const itemPointerStart = useRef<{ x: number; y: number } | null>(null);
  const itemDragActivated = useRef(false);
  const isReordering = editable && itemReorderMode;

  const clearItemDrag = () => {
    itemPointerStart.current = null;
    itemDragActivated.current = false;
    setDraggingItemKey(null);
    setItemReorderMode(false);
    setDragOverItemKey(null);
    setDragItemLabels({});
  };

  const handleItemPointerDown = (
    event: ReactPointerEvent<HTMLButtonElement>,
    field: FormListFieldData,
  ) => {
    if (!editable) return;
    event.preventDefault();
    itemPointerStart.current = { x: event.clientX, y: event.clientY };
    itemDragActivated.current = false;
    const values = (form.getFieldValue(fieldName) as ProfileListItem[] | undefined) ?? [];
    const labels = Object.fromEntries(
      fields.map((currentField, currentIndex) => [
        String(currentField.key),
        itemLabel?.(values[currentIndex] ?? {}, currentIndex) || `第 ${currentIndex + 1} 项`,
      ]),
    );
    setDragItemLabels(labels);
    setItemReorderMode(true);
    setDraggingItemKey(field.key);
    setDragOverItemKey(null);
  };

  useEffect(() => {
    if (!editable || draggingItemKey === null) return;

    const findItemAtPoint = (clientX: number, clientY: number): number | null => {
      const element = document.elementFromPoint(clientX, clientY);
      const item = element?.closest<HTMLElement>("[data-profile-list-item-key]");
      const key = item?.dataset.profileListItemKey;
      if (!key) return null;
      const parsedKey = Number(key);
      return Number.isFinite(parsedKey) ? parsedKey : null;
    };

    const handlePointerMove = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      const start = itemPointerStart.current;
      if (!start) return;
      const distance = Math.hypot(event.clientX - start.x, event.clientY - start.y);
      if (!itemDragActivated.current && distance < ITEM_DRAG_THRESHOLD_PX) return;
      itemDragActivated.current = true;
      const targetKey = findItemAtPoint(event.clientX, event.clientY);
      setDragOverItemKey(targetKey === draggingItemKey ? null : targetKey);
    };

    const finishItemDrag = (event: globalThis.PointerEvent) => {
      event.preventDefault();
      const start = itemPointerStart.current;
      const distance = start ? Math.hypot(event.clientX - start.x, event.clientY - start.y) : 0;
      const targetKey = findItemAtPoint(event.clientX, event.clientY);
      if (
        itemDragActivated.current &&
        distance >= ITEM_DRAG_THRESHOLD_PX &&
        targetKey !== null &&
        targetKey !== draggingItemKey
      ) {
        const sourceIndex = fields.findIndex((field) => field.key === draggingItemKey);
        const targetIndex = fields.findIndex((field) => field.key === targetKey);
        if (sourceIndex >= 0 && targetIndex >= 0) operations.move(sourceIndex, targetIndex);
      }
      clearItemDrag();
    };

    document.addEventListener("pointermove", handlePointerMove, { passive: false });
    document.addEventListener("pointerup", finishItemDrag);
    document.addEventListener("pointercancel", finishItemDrag);
    return () => {
      document.removeEventListener("pointermove", handlePointerMove);
      document.removeEventListener("pointerup", finishItemDrag);
      document.removeEventListener("pointercancel", finishItemDrag);
    };
  }, [draggingItemKey, editable, fields, operations]);

  return (
    <>
      <div className={`profile-list-items${isReordering ? " is-reordering" : ""}`}>
        {fields.map((field, index) => {
          const label =
            dragItemLabels[String(field.key)] || itemLabel?.({}, index) || `第 ${index + 1} 项`;
          return (
            <div
              key={field.key}
              data-profile-list-item-key={field.key}
              className={`profile-list-item${dragOverItemKey === field.key ? " is-drag-over" : ""}`}
            >
              {editable && (
                <Tooltip title={`拖动或使用上下方向键调整${label}顺序`}>
                  <button
                    type="button"
                    className="profile-list-item-drag-handle"
                    aria-label={`拖动调整${label}顺序`}
                    onPointerDown={(event) => handleItemPointerDown(event, field)}
                    onKeyDown={(event) => {
                      if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
                      event.preventDefault();
                      const targetIndex = index + (event.key === "ArrowUp" ? -1 : 1);
                      if (targetIndex >= 0 && targetIndex < fields.length) {
                        operations.move(index, targetIndex);
                      }
                    }}
                  >
                    <HolderOutlined />
                  </button>
                </Tooltip>
              )}
              <Tooltip title={`删除${label}`}>
                <Button
                  type="text"
                  danger
                  size="small"
                  aria-label={`删除${label}`}
                  icon={<DeleteOutlined />}
                  disabled={!editable || isReordering}
                  className="profile-list-item-delete"
                  onClick={() => operations.remove(field.name)}
                />
              </Tooltip>
              {isReordering && (
                <div className="profile-list-item-summary">
                  <Typography.Text strong ellipsis={{ tooltip: label }}>
                    {label}
                  </Typography.Text>
                </div>
              )}
              <div className={`profile-list-item-content${isReordering ? " is-collapsed" : ""}`}>
                {renderRow(field, operations.remove)}
              </div>
            </div>
          );
        })}
      </div>
      {!isReordering && (
        <Button
          type="dashed"
          block
          icon={<PlusOutlined />}
          disabled={!editable}
          onClick={() => operations.add({ ...emptyValue })}
        >
          添加一条
        </Button>
      )}
    </>
  );
}

export default function ProfileSection({
  fieldName,
  editable = true,
  emptyValue,
  renderRow,
  itemLabel,
}: Props) {
  return (
    <Card size="small" style={{ marginBottom: 16 }}>
      <Form.List name={fieldName}>
        {(fields, operations) => (
          <ProfileListBody
            fields={fields}
            operations={operations}
            fieldName={fieldName}
            editable={editable}
            emptyValue={emptyValue}
            renderRow={renderRow}
            itemLabel={itemLabel}
          />
        )}
      </Form.List>
    </Card>
  );
}

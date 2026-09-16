/**
 * 列表行的操作区：少量主操作直接显示，其余收进「更多」下拉。
 *
 * 之前的列表把 6 个操作（含红色的删除）全部平铺在右侧，视觉上很吵、也容易误点删除。
 * 现在主操作最多两个，其余进菜单；删除一律放在菜单里并二次确认。
 *
 * 同一个 `RowActionItem` 列表同时供两点使用：表格行内的「更多」按钮，以及整行的
 * 右键菜单（`RowContextMenu`），保证两处菜单项完全一致。
 */

import { MoreOutlined } from "@ant-design/icons";
import { Button, Dropdown, Space } from "antd";
import type { ReactNode } from "react";
import { useRowActionMenu, type RowActionItem } from "./rowActionMenu";

// 类型从工具模块转发出去：调用方只认 `RowActions` 这一个入口，不必知道菜单项
// 与 hook 被拆到了另一个文件。
export type { RowActionItem } from "./rowActionMenu";

interface RowActionsProps {
  /** 直接显示的主操作（建议不超过 2 个）。 */
  primary?: RowActionItem[];
  /** 收进「更多」下拉的操作，含删除等危险项。 */
  more?: RowActionItem[];
  disabled?: boolean;
}

export function RowActions({ primary = [], more = [], disabled = false }: RowActionsProps) {
  const buildMenu = useRowActionMenu();
  const menuItems = buildMenu(more);
  return (
    <Space size={4} className="row-actions">
      {primary.map((item) => (
        <Button
          key={item.key}
          type="link"
          size="small"
          disabled={disabled || item.disabled}
          danger={item.danger}
          icon={item.icon}
          onClick={item.onClick}
        >
          {item.label}
        </Button>
      ))}
      {more.length > 0 && (
        <Dropdown menu={{ items: menuItems }} trigger={["click"]} placement="bottomRight">
          <Button
            type="text"
            size="small"
            className="row-actions-more"
            aria-label="更多操作"
            disabled={disabled}
            icon={<MoreOutlined />}
          />
        </Dropdown>
      )}
    </Space>
  );
}

interface RowContextMenuProps {
  items: RowActionItem[];
  children: ReactNode;
  disabled?: boolean;
}

/** 整行的右键菜单：与「更多」下拉共用同一份菜单项。 */
export function RowContextMenu({ items, children, disabled = false }: RowContextMenuProps) {
  const buildMenu = useRowActionMenu();
  if (disabled || items.length === 0) return <>{children}</>;
  return (
    <Dropdown menu={{ items: buildMenu(items) }} trigger={["contextMenu"]}>
      {children}
    </Dropdown>
  );
}

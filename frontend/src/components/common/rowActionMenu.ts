/**
 * 列表行操作的菜单项定义与构造。
 *
 * 单独成文件而不是和 `RowActions` 放一起：那个文件只导出组件，才能让 React
 * Fast Refresh 在开发时正常工作（同时导出 hook 会让热更新退化成整页刷新）。
 */

import { App } from "antd";
import type { MenuProps } from "antd";
import type { ReactNode } from "react";

export interface RowActionItem {
  key: string;
  label: string;
  danger?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  onClick?: () => void;
  /** 有值时点击后弹出二次确认，确认文案即此字符串。 */
  confirm?: string;
}

interface BuildOptions {
  onDone?: () => void;
}

/** 把 `RowActionItem` 列表转成 antd 菜单项（含二次确认）。 */
export function useRowActionMenu() {
  const { modal } = App.useApp();
  return (items: RowActionItem[], options: BuildOptions = {}): MenuProps["items"] =>
    items.map((item) => ({
      key: item.key,
      danger: item.danger,
      disabled: item.disabled,
      icon: item.icon,
      label: item.label,
      onClick: () => {
        if (item.confirm) {
          modal.confirm({
            title: item.confirm,
            okButtonProps: { danger: item.danger },
            onOk: () => {
              item.onClick?.();
              options.onDone?.();
            },
          });
          return;
        }
        item.onClick?.();
        options.onDone?.();
      },
    }));
}

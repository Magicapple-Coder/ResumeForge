/**
 * 「卡片 → 详情」的共享判定与类型。
 *
 * 为什么与 `RecordDetail.tsx` 分成两个文件：`.tsx` 里导出非组件会让
 * `react-refresh/only-export-components` 报警，而它守的是真实体验——热更新一旦退化成
 * 整页刷新，改样式就只能靠手点。所以判定函数与类型放进这个 `.ts`，组件文件只导出组件。
 *
 * 文件名**不能叫 `recordDetail.ts`**：Windows 文件系统大小写不敏感，TypeScript 解析
 * `./common/RecordDetail` 时会先命中 `.ts`，于是 `RecordDetail.tsx` 反被解析成这个文件
 * （报 TS1149「只差大小写」并找不到组件导出）。同理也不与 `RowActions.tsx` /
 * `rowActionMenu.ts` 的命名方式冲突——那是两个不同的词，而这里只差大小写。
 */
import type { ReactNode } from "react";

/** 内层可交互元素：点它们时卡片自身不响应。 */
export const INTERACTIVE_SELECTOR =
  'button, a, input, textarea, select, summary, [role="button"], [role="link"], [contenteditable="true"]';

/**
 * 这次点击是不是来自卡片里的按钮/链接？
 *
 * 表格行（`<tr>`）与 antd `List.Item` 不方便再套一层 `DetailTrigger`，它们可以直接
 * `onClick` + 调这个函数，判定口径与 `DetailTrigger` 完全一致。
 */
export function isFromInnerControl(event: {
  target: EventTarget | null;
  currentTarget: EventTarget | null;
}): boolean {
  const { target, currentTarget } = event;
  if (!(target instanceof HTMLElement)) return true;
  const hit = target.closest(INTERACTIVE_SELECTOR);
  return hit !== null && hit !== currentTarget;
}

/** 详情抽屉里的一行短字段。 */
export interface DetailField {
  label: ReactNode;
  value: ReactNode;
}

/** 详情抽屉里的长正文分区（备注、正文、问题清单等）。 */
export interface DetailSection {
  title?: ReactNode;
  content: ReactNode;
}

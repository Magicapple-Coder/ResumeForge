/**
 * 回收站。
 *
 * 六类内容共用一个形状（`TrashItem`），界面用一张表混排 + 类型筛选——比做成六个页签更好找，
 * 也让"我最近删了什么"这个问题只有一个答案。
 *
 * `type` 的**中文名由后端下发**（`labels`），前端不抄一份 "job→岗位" 的映射：抄一份就会漂移，
 * 后端新增一类内容时界面会显示成英文 key。
 */

/** 后端下发的类型名映射：`{ job: "岗位", resume: "简历记录", ... }`。 */
export type TrashLabels = Record<string, string>;

export interface TrashItem {
  type: string;
  /** 后端给的中文类型名，直接渲染即可。 */
  type_label: string;
  id: number;
  title: string;
  subtitle: string;
  deleted_at: string | null;
}

export interface TrashSummary {
  total: number;
  counts: Record<string, number>;
  labels: TrashLabels;
  items: TrashItem[];
}

/** 清空回收站的结果：**真正**删掉了多少条（只回 204 等于让用户自己数）。 */
export interface TrashEmptyResult {
  removed: number;
}

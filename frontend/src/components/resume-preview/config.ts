import type { LayoutMeasure } from "../../utils/resumeLayoutMeasure";

export const A4_WIDTH_PX = 794;
export const A4_HEIGHT_PX = 1123;
export const PREVIEW_BOTTOM_RESERVE = 150;
export const PREVIEW_HEIGHT_RATIO = 0.62;
export const MIN_PREVIEW_HEIGHT = 360;
export const MIN_ZOOM = 0.5;
export const MAX_ZOOM = 3.5;
export const PROBE_STYLE_ID = "resume-fit-probe";
export const LIVE_PROBE_STYLE_ID = "resume-font-live-probe";

export const APPROXIMATE_PAGINATION_NOTE =
  "多页视图为「按 A4 高度切分的近似分页」，真实分页以「浏览器打印 / 下载 PDF」为准。";

export interface AvailableSpace {
  width: number;
  height: number;
}

export interface PanStart {
  clientX: number;
  clientY: number;
  scrollLeft: number;
  scrollTop: number;
}

export type InteractionMode = "pan" | "edit";

/** 预览暴露给外部的命令式接口，只给「自动一页」等版式控件使用。 */
export interface ResumePreviewHandle {
  measureWithProbe(css: string): LayoutMeasure | null;
  setLiveProbe(css: string): void;
}

/**
 * 把连续流固定为指定数量的 A4 列。
 *
 * 不能只设置 column-width 再通过 scrollWidth 反推页数：列间距和 body 的边距也会被算进去，
 * 内容实际需要两页时可能被误画成三、四页。列数由测量结果直接决定，外层分隔线也因此有
 * 唯一的几何来源。
 */
export function columnsCss(columnCount: number): string {
  const count = Math.max(2, Math.round(columnCount));
  return (
    "html,body{overflow:hidden!important}" +
    `body{width:${count * 210}mm!important;height:297mm!important;` +
    "column-width:182mm!important;column-gap:28mm!important;" +
    `column-count:${count}!important;column-fill:auto!important}`
  );
}

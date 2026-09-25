/**
 * 排行/漏斗图里**标签排版**的纯函数：估宽、截断、按最长标签算标签区宽度。
 *
 * 单独成模块而不是留在 `HorizontalBarChart.tsx` 里：那个文件是组件，混着导出纯函数会触发
 * 组件的 Fast Refresh 失效（eslint `react-refresh/only-export-components`），而且这几个
 * 函数本来就不依赖 React，放这里可以单独测。
 *
 * 存在的理由：横向条形的标签是**右端固定、向左排版**的，标签区宽度固定时，长公司名会一直
 * 往左伸、伸出画布被裁掉（用户看到"公司名少了几个字"）。
 */

export const HORIZONTAL_BAR_MIN_LABEL_WIDTH = 96;
export const HORIZONTAL_BAR_MAX_LABEL_WIDTH = 200;
export const BAR_LABEL_FONT_SIZE = 13;
export const BAR_LABEL_GAP = 10;

/**
 * 估宽的保守余量。
 *
 * `estimateTextWidth` 把汉字按 1em 算，而系统字体的实际步进比 1em 略大（实测一排十个汉字
 * 会多出 1~2px）。不留余量的话，量着"正好放得下"的那一行会差一个像素贴到画布边缘
 * （实测 `bbox.x = -1.1`），用户能看出第一个字被切了一刀。留 4px 之后左缘稳定在 +12 左右。
 */
export const BAR_LABEL_SAFETY = 4;

/** 估算一段文字的像素宽度：全角（汉字、全角标点）按一个字号、其余按 0.55 个字号。 */
export function estimateTextWidth(text: string, fontSize: number = BAR_LABEL_FONT_SIZE): number {
  let width = 0;
  for (const char of text) {
    width += /[\u2e80-\u9fff\uff00-\uffef\u3000-\u303f]/.test(char) ? fontSize : fontSize * 0.55;
  }
  return width;
}

/** 把标签压到可用宽度内；压不下就截断加省略号（宁可自己截，也不要被画布边缘裁）。 */
export function fitLabel(label: string, available: number): string {
  if (estimateTextWidth(label) <= available) return label;
  const ellipsisWidth = estimateTextWidth("…");
  let kept = "";
  let width = 0;
  for (const char of label) {
    const charWidth = estimateTextWidth(char);
    if (width + charWidth + ellipsisWidth > available) break;
    kept += char;
    width += charWidth;
  }
  return kept ? `${kept}…` : label.slice(0, 1);
}

/** 按最长标签决定标签区宽度（夹在 [96, 200]），并给出真正可用于文字的宽度。 */
export function labelLayoutFor(labels: string[]): { labelWidth: number; labelTextWidth: number } {
  const longest = labels.reduce((widest, label) => Math.max(widest, estimateTextWidth(label)), 0);
  const labelWidth = Math.min(
    HORIZONTAL_BAR_MAX_LABEL_WIDTH,
    Math.max(HORIZONTAL_BAR_MIN_LABEL_WIDTH, Math.ceil(longest) + BAR_LABEL_GAP + BAR_LABEL_SAFETY),
  );
  return { labelWidth, labelTextWidth: labelWidth - BAR_LABEL_GAP - BAR_LABEL_SAFETY };
}

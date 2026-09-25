import { A4_WIDTH_PX, columnsCss } from "./config";
import {
  measureResumeLayout,
  pagesNeededFor,
  type LayoutMeasure,
} from "../../utils/resumeLayoutMeasure";

export interface FrameLayoutResult {
  measure: LayoutMeasure | null;
  overflow: boolean;
  naturalWidth: number;
  pagesNeeded: number;
  visualPages: number;
  scale: number;
}

interface Options {
  document: Document;
  pageCount: number;
  paperHeight: number;
}

/**
 * 测量 iframe 并把需要的多页列数固定下来。
 *
 * 测量一定发生在单列状态，避免 columns 把纵向高度折叠后让页数看起来变少；测量完成后再
 * 写入固定 column-count。这样内容实际需要两页时，渲染列数、外层纸张宽度和虚线数量始终
 * 来自同一个 pagesNeeded，而不会再通过 scrollWidth 猜出第四页。
 */
export function layoutFrame({
  document,
  pageCount,
  paperHeight,
}: Options): FrameLayoutResult | null {
  const body = document.body;
  const root = document.documentElement;
  if (!body || !root) return null;

  body.style.width = "";
  body.style.height = "";
  const style =
    (document.getElementById("resume-preview-style") as HTMLStyleElement | null) ??
    document.createElement("style");
  style.id = "resume-preview-style";
  style.textContent = "";
  if (!style.parentElement) document.head.appendChild(style);

  const measured = measureResumeLayout(document, pageCount);
  const reportedScale = Number(body.dataset.scale ?? "");
  const templateScriptRan = Number.isFinite(reportedScale) && reportedScale > 0;

  let overflow = body.dataset.overflow === "1";
  if (!templateScriptRan) {
    const contentWidth = Math.max(body.scrollWidth, root.scrollWidth, A4_WIDTH_PX);
    const contentHeight = Math.max(body.scrollHeight, root.scrollHeight, paperHeight);
    const contentScale = Math.min(1, A4_WIDTH_PX / contentWidth, paperHeight / contentHeight);
    if (contentScale < 1) body.style.setProperty("--fit-scale", contentScale.toFixed(4));
    overflow = overflow || body.scrollHeight > paperHeight + 1;
  }

  const pagesNeeded = measured ? pagesNeededFor(measured) : overflow ? pageCount + 1 : pageCount;
  overflow = overflow || pagesNeeded > pageCount;
  const visualPages = overflow ? Math.max(pageCount + 1, pagesNeeded) : pageCount;
  style.textContent = overflow ? columnsCss(visualPages) : "html,body{overflow:hidden!important}";

  // 令 columns 真正参与布局；宽度不再用于反推页数，只作为画布尺寸。
  if (overflow) void body.offsetWidth;
  const naturalWidth = overflow ? A4_WIDTH_PX * visualPages : A4_WIDTH_PX;

  return {
    measure: measured,
    overflow,
    naturalWidth,
    pagesNeeded,
    visualPages,
    scale: templateScriptRan ? reportedScale : 1,
  };
}

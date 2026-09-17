/**
 * 在预览的 iframe 里量出「正文实际占了多高」。
 *
 * **为什么不用 `scrollHeight`**：它把 `padding-bottom` 之外的空白、以及被撑开的容器
 * 都算进去，量出来的"内容高度"偏大；而我们要的是"正文最后一行离内容区顶边有多远"，
 * 好和"一页的可用高度"相除。所以做法是：拿 body 的固定高度减上下 padding 得到可用高度，
 * 再取最后一个**可见正文元素**的底边（含它的下外边距）减去内容顶边。
 *
 * 另外两个坑：
 * - 调用方可能给 body 加过 `transform: scale()` 把内容压进页面。`getBoundingClientRect`
 *   返回的是**变换后**的坐标，而 `getComputedStyle().paddingTop` 返回的是**未变换**的值，
 *   两者混用会算出离谱的结果。这里自己把 transform 摘掉、量完再还原。
 * - 只认"带直接文本"或媒体元素，空容器不算正文——否则一个只有下边距的空 div 会被当成
 *   占了一行，让本来就空的版面显得更满。
 */

export interface LayoutMeasure {
  /** 正文最后一行底边到内容区顶边的距离。 */
  usedHeight: number;
  /** 一页里正文可用的高度（页高减上下页边距）。 */
  pageContentHeight: number;
  pageLimit: number;
}

const MEDIA_TAGS = new Set(["IMG", "SVG", "CANVAS", "TABLE"]);

function hasDirectText(element: Element): boolean {
  for (const node of Array.from(element.childNodes)) {
    if (node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim()) return true;
  }
  return false;
}

function isCounted(element: Element): boolean {
  const style = window.getComputedStyle(element);
  if (style.display === "none" || style.visibility === "hidden") return false;
  if (style.position === "fixed") return false;
  const rect = element.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return false;
  return hasDirectText(element) || MEDIA_TAGS.has(element.tagName);
}

/** 量一页的版面。``pageLimit`` 是用户选的页数，body 的总高度是它的整数倍。 */
export function measureResumeLayout(document: Document, pageLimit: number): LayoutMeasure | null {
  const body = document.body;
  if (!body || pageLimit < 1) return null;

  const previousTransform = body.style.transform;
  body.style.transform = "none";
  try {
    const style = window.getComputedStyle(body);
    const rect = body.getBoundingClientRect();
    const paddingTop = Number.parseFloat(style.paddingTop) || 0;
    const paddingBottom = Number.parseFloat(style.paddingBottom) || 0;

    const contentTop = rect.top + paddingTop;
    const totalContentHeight = rect.height - paddingTop - paddingBottom;
    if (!(totalContentHeight > 0)) return null;
    const pageContentHeight = totalContentHeight / pageLimit;

    let lastBottom = contentTop;
    for (const element of Array.from(body.querySelectorAll("*"))) {
      if (!isCounted(element)) continue;
      const elementRect = element.getBoundingClientRect();
      const marginBottom = Number.parseFloat(window.getComputedStyle(element).marginBottom) || 0;
      lastBottom = Math.max(lastBottom, elementRect.bottom + marginBottom);
    }

    return {
      usedHeight: Math.max(0, lastBottom - contentTop),
      pageContentHeight,
      pageLimit,
    };
  } finally {
    body.style.transform = previousTransform;
  }
}

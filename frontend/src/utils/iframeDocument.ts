/**
 * 给预览用的 iframe 文档做一点"展示层"加工。
 *
 * 背景：模板一览里每个模板都是一个 794×1123 的 iframe 缩放到 0.36 倍当缩略图。
 * 简历正文一旦超过一页，iframe 内部就会冒出**自己的滚动条**——在缩略图上看起来
 * 就是卡片右下角一根多余的竖条（用户反馈"右边都有一个滚动条，看起来不美观"）。
 *
 * 缩略图只需要"这一页长什么样"，所以把内层滚动直接关掉；想看完整内容走
 * 「查看大图」（那个弹窗里的 iframe 允许滚动，因为那里的滚动是预期的）。
 */

const HIDE_SCROLLBAR_STYLE =
  "<style>html,body{overflow:hidden !important;}" +
  "html::-webkit-scrollbar,body::-webkit-scrollbar{display:none !important;width:0 !important;height:0 !important;}</style>";

/** 往预览 HTML 里注入"隐藏滚动条"的样式；已有 `</head>` 就插进去，没有就放在最前面。 */
export function withHiddenScrollbar(html: string): string {
  if (!html) return html;
  const headEnd = html.toLowerCase().indexOf("</head>");
  if (headEnd >= 0) {
    return `${html.slice(0, headEnd)}${HIDE_SCROLLBAR_STYLE}${html.slice(headEnd)}`;
  }
  return `${HIDE_SCROLLBAR_STYLE}${html}`;
}

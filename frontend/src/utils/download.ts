/** 浏览器端文件下载与打印工具。 */

/** 触发浏览器下载 blob 文件 */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

/** 在新窗口打开 HTML 并自动调起打印（另存为 PDF） */
export function printHtml(html: string): void {
  // Blob URL 使用独立来源，避免把预览 HTML 通过 document.write 注入当前站点来源。
  const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
  const win = window.open(url, "_blank");
  if (!win) {
    URL.revokeObjectURL(url);
    throw new Error("浏览器拦截了弹窗，请允许本站弹窗后重试");
  }
  win.addEventListener(
    "load",
    () => {
      setTimeout(() => {
        win.focus();
        win.print();
        URL.revokeObjectURL(url);
      }, 300);
    },
    { once: true },
  );
}

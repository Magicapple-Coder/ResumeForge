/** 缩略图 iframe 的展示层加工：隐藏内层滚动条。 */

import { describe, expect, it } from "vitest";
import { withHiddenScrollbar } from "./iframeDocument";

describe("withHiddenScrollbar", () => {
  it("把样式插在 </head> 之前（不破坏原有结构）", () => {
    const html = "<html><head><title>t</title></head><body>hi</body></html>";
    const result = withHiddenScrollbar(html);
    expect(result.indexOf("overflow:hidden")).toBeLessThan(result.indexOf("</head>"));
    expect(result).toContain("<body>hi</body>");
    expect(result.indexOf("<title>")).toBeLessThan(result.indexOf("overflow:hidden"));
  });

  it("没有 </head> 时放在最前面，照样生效", () => {
    const result = withHiddenScrollbar("<div>裸片段</div>");
    expect(result.startsWith("<style>")).toBe(true);
    expect(result).toContain("<div>裸片段</div>");
  });

  it("大小写不敏感（服务端可能输出 </HEAD>）", () => {
    const html = "<html><HEAD></HEAD><body>x</body></html>";
    expect(withHiddenScrollbar(html).indexOf("overflow:hidden")).toBeLessThan(
      withHiddenScrollbar(html).toLowerCase().indexOf("</head>"),
    );
  });

  it("空串原样返回（不凭空造一个文档）", () => {
    expect(withHiddenScrollbar("")).toBe("");
  });
});

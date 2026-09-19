import { createElement } from "react";
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { renderInlineMarkdown, resolveSourceUrl, summarizeSkillNames } from "./assistantUtils";
import type { AssistantSourceNumber } from "../../types";

function skill(name: string) {
  return { name };
}

function sourceMap(): AssistantSourceNumber[] {
  return [
    { number: 1, url: "https://example.com/first" },
    { number: 2, url: "https://example.com/second" },
  ];
}

/** 把 renderInlineMarkdown 的输出包进一个 div 渲染，返回 DOM 容器。 */
function renderMarkdown(value: string, map?: AssistantSourceNumber[]): HTMLElement {
  return render(createElement("div", null, ...renderInlineMarkdown(value, map))).container;
}

describe("summarizeSkillNames", () => {
  it("lists every name while they still fit", () => {
    expect(summarizeSkillNames([skill("简历诊断")])).toBe("简历诊断");
    expect(summarizeSkillNames([skill("简历诊断"), skill("面试追问")])).toBe("简历诊断、面试追问");
  });

  it("collapses the list instead of letting the header grow", () => {
    expect(summarizeSkillNames([skill("A"), skill("B"), skill("C")])).toBe("A、B 等 3 个");
  });
});

describe("renderInlineMarkdown 来源引用", () => {
  it("turns [来源N] into a link pointing at the Nth entry of the persisted map", () => {
    const container = renderMarkdown("见 [来源1] 和 [来源2]。", sourceMap());
    const links = Array.from(container.querySelectorAll("a"));

    expect(links.map((link) => [link.textContent, link.getAttribute("href")])).toEqual([
      ["[来源1]", "https://example.com/first"],
      ["[来源2]", "https://example.com/second"],
    ]);
  });

  it("keeps [来源N] as plain text when the number is not in the map", () => {
    const container = renderMarkdown("见 [来源9]。", sourceMap());

    // 编号对不上时必须退化成纯文本、绝不报错、也绝不渲染一个会跳错来源的链接。
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("见 [来源9]。");
  });

  it("keeps [来源N] as plain text when there is no source map at all", () => {
    const container = renderMarkdown("见 [来源1]。");

    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toBe("见 [来源1]。");
  });
});

describe("resolveSourceUrl", () => {
  it("returns the url only for a known number", () => {
    expect(resolveSourceUrl(sourceMap(), 1)).toBe("https://example.com/first");
    expect(resolveSourceUrl(sourceMap(), 2)).toBe("https://example.com/second");
    expect(resolveSourceUrl(sourceMap(), 3)).toBeNull();
    expect(resolveSourceUrl(undefined, 1)).toBeNull();
  });

  it("rejects a non-http url so it cannot become a bad link", () => {
    expect(resolveSourceUrl([{ number: 1, url: "javascript:alert(1)" }], 1)).toBeNull();
  });
});

/** 图表标签排版：估宽、截断、按最长标签算标签区宽度。
 *
 * 这几条对着一个真实缺陷：横向条形的标签右端固定、向左排版，标签区固定 96px 时，
 * 「示例科技（上海）有限公司」这类公司名会伸出画布左缘被裁掉，用户看到的是"公司名少了几个字"。
 */

import { describe, expect, it } from "vitest";
import {
  BAR_LABEL_FONT_SIZE,
  BAR_LABEL_GAP,
  BAR_LABEL_SAFETY,
  HORIZONTAL_BAR_MAX_LABEL_WIDTH,
  HORIZONTAL_BAR_MIN_LABEL_WIDTH,
  estimateTextWidth,
  fitLabel,
  labelLayoutFor,
} from "./barLabelLayout";

describe("estimateTextWidth", () => {
  it("汉字按一个字号、ASCII 按 0.55 个字号", () => {
    expect(estimateTextWidth("中中")).toBe(BAR_LABEL_FONT_SIZE * 2);
    expect(estimateTextWidth("abc")).toBeCloseTo(BAR_LABEL_FONT_SIZE * 0.55 * 3, 5);
  });
});

describe("fitLabel", () => {
  it("放得下就原样返回，不加省略号", () => {
    expect(fitLabel("示例公司", 200)).toBe("示例公司");
  });

  it("放不下时截断加省略号，且截断后不超过可用宽度", () => {
    const label = "示例国际控股集团有限责任公司上海分公司";
    const available = 100;
    const fitted = fitLabel(label, available);
    expect(fitted.endsWith("…")).toBe(true);
    expect(fitted.length).toBeLessThan(label.length);
    expect(estimateTextWidth(fitted)).toBeLessThanOrEqual(available);
  });

  it("窄到连一个字都放不下时也至少返回一个字（不返回空串）", () => {
    expect(fitLabel("示例公司", 1)).toBe("示");
  });
});

describe("labelLayoutFor", () => {
  it("标签短时用最小宽度", () => {
    expect(labelLayoutFor(["甲", "乙"]).labelWidth).toBe(HORIZONTAL_BAR_MIN_LABEL_WIDTH);
  });

  it("按最长标签变宽，让常见公司名完整放得下", () => {
    const long = "示例会展服务有限公司";
    const { labelWidth, labelTextWidth } = labelLayoutFor(["短", long]);
    expect(labelWidth).toBeGreaterThan(HORIZONTAL_BAR_MIN_LABEL_WIDTH);
    // 真正可用的文字宽度必须装得下最长那一条——这正是"公司名不再被裁"的判据。
    expect(estimateTextWidth(long)).toBeLessThanOrEqual(labelTextWidth);
    expect(labelWidth - labelTextWidth).toBe(BAR_LABEL_GAP + BAR_LABEL_SAFETY);
  });

  it("超长标签封顶在最大宽度，剩下的交给截断", () => {
    const layout = labelLayoutFor(["示例国际控股集团有限责任公司上海分公司"]);
    expect(layout.labelWidth).toBe(HORIZONTAL_BAR_MAX_LABEL_WIDTH);
  });

  it("没有标签时回落到最小宽度", () => {
    expect(labelLayoutFor([]).labelWidth).toBe(HORIZONTAL_BAR_MIN_LABEL_WIDTH);
  });
});

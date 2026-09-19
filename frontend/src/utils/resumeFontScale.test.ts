/**
 * 无级字号映射的纯函数测试。
 *
 * 这里盯的是"拖出来的绝对像素 → 落库的档位 + 系数"这件事本身：映射错了不会报错，
 * 只会让用户拖到某个位置、存下去、下次打开却换了字号——是那种不写用例就发现不了的错。
 */
import { describe, expect, it, vi } from "vitest";
import type { ResumeFontScaleOption, ResumeLayout } from "../types";
import {
  FONT_SCALE_ADJUST_KEY,
  fontProbeCss,
  fontPxBounds,
  fontTiers,
  layoutForFontPx,
  layoutToFontPx,
  tierByName,
  withFontAdjust,
} from "./resumeFontScale";

const OPTIONS: ResumeFontScaleOption[] = [
  { name: "large", label: "大字号", description: "", base_px: 15.5 },
  { name: "small", label: "小字号", description: "", base_px: 12 },
  { name: "standard", label: "标准字号", description: "", base_px: 14 },
];

const TIERS = fontTiers(OPTIONS);

function layout(overrides: Partial<ResumeLayout> = {}): ResumeLayout {
  return {
    template: "classic",
    format_name: "",
    page_limit: 1,
    font_scale: "standard",
    ...overrides,
  };
}

describe("fontTiers", () => {
  it("按基准像素升序排列，即使后端给的顺序是乱的", () => {
    expect(TIERS.map((tier) => tier.name)).toEqual(["small", "standard", "large"]);
    expect(TIERS.map((tier) => tier.basePx)).toEqual([12, 14, 15.5]);
  });

  it("目录尚未加载（空数组）时静默退回内置三档，不告警", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(fontTiers([]).map((tier) => tier.basePx)).toEqual([12, 14, 15.5]);
    // 首屏目录还没到是正常态：每次都刷告警等于把真正的信号淹掉。
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });

  it("目录里有档位却缺合法 base_px 时退回内置三档，并告警（回退不能无声）", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const tiers = fontTiers([
      { name: "standard", label: "标准", description: "", base_px: Number.NaN },
    ]);
    expect(tiers.map((tier) => tier.basePx)).toEqual([12, 14, 15.5]);
    // 这条断言就是"回退不能无声"的牙齿：后端漏发 base_px 时台面上必须看得见。
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain("base_px");
    warn.mockRestore();
  });

  it("目录正常（都带合法 base_px）时既不回退也不告警", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    expect(fontTiers(OPTIONS).map((tier) => tier.basePx)).toEqual([12, 14, 15.5]);
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe("fontPxBounds", () => {
  it("范围取所有档位基准像素的最小 / 最大", () => {
    expect(fontPxBounds(TIERS)).toEqual({ min: 12, max: 15.5 });
  });
});

describe("layoutToFontPx", () => {
  it("档位基准 × 系数", () => {
    expect(layoutToFontPx(layout({ font_scale: "standard" }), TIERS)).toBe(14);
    expect(
      layoutToFontPx(
        layout({ font_scale: "standard", format_config: { [FONT_SCALE_ADJUST_KEY]: 0.9 } }),
        TIERS,
      ),
    ).toBe(12.6);
    expect(layoutToFontPx(layout({ font_scale: "large" }), TIERS)).toBe(15.5);
  });

  it("系数是字符串（后端 JSON 可能回成字符串）时也能解析", () => {
    expect(
      layoutToFontPx(
        layout({ font_scale: "standard", format_config: { [FONT_SCALE_ADJUST_KEY]: "0.95" } }),
        TIERS,
      ),
    ).toBe(13.3);
  });

  it("未知档位名退回默认档而不是崩", () => {
    expect(layoutToFontPx(layout({ font_scale: "standard" }), [])).toBe(14);
    expect(tierByName(TIERS, "standard").basePx).toBe(14);
  });
});

describe("layoutForFontPx", () => {
  it("落在档位基准上时不写系数键（避免每份简历都多一条无意义的覆盖）", () => {
    const next = layoutForFontPx(layout(), 14, TIERS);
    expect(next.font_scale).toBe("standard");
    expect(next.format_config).toEqual({});
  });

  it("就近取档：13.1 落到标准档、15.0 落到大档", () => {
    expect(layoutForFontPx(layout(), 13.1, TIERS)).toMatchObject({
      font_scale: "standard",
      format_config: { [FONT_SCALE_ADJUST_KEY]: 0.936 },
    });
    expect(layoutForFontPx(layout(), 15, TIERS)).toMatchObject({
      font_scale: "large",
      format_config: { [FONT_SCALE_ADJUST_KEY]: 0.968 },
    });
    expect(layoutForFontPx(layout(), 12.5, TIERS)).toMatchObject({
      font_scale: "small",
      format_config: { [FONT_SCALE_ADJUST_KEY]: 1.042 },
    });
  });

  it("保留强调色等其它覆盖，只改字号", () => {
    const next = layoutForFontPx(
      layout({ format_config: { accent: "#123456", line_height: 1.5 } }),
      13.1,
      TIERS,
    );
    expect(next.format_config).toEqual({
      accent: "#123456",
      line_height: 1.5,
      [FONT_SCALE_ADJUST_KEY]: 0.936,
    });
  });

  it("整段范围内的系数都落在后端 [0.88, 1.16] 内（越界会被后端静默丢弃）", () => {
    for (let px = 12; px <= 15.5 + 1e-9; px = Math.round((px + 0.1) * 10) / 10) {
      const next = layoutForFontPx(layout(), px, TIERS);
      const adjust = next.format_config?.[FONT_SCALE_ADJUST_KEY];
      if (adjust === undefined) continue;
      expect(Number(adjust)).toBeGreaterThanOrEqual(0.88);
      expect(Number(adjust)).toBeLessThanOrEqual(1.16);
    }
  });

  it("超出范围的值被夹到边界，不会发出后端会丢弃的系数", () => {
    expect(layoutForFontPx(layout(), 999, TIERS)).toMatchObject({
      font_scale: "large",
      format_config: {},
    });
    expect(layoutForFontPx(layout(), 1, TIERS)).toMatchObject({ font_scale: "small" });
  });
});

describe("withFontAdjust", () => {
  it("系数为 1 时删除该键，其它键保留", () => {
    expect(withFontAdjust({ accent: "#000", [FONT_SCALE_ADJUST_KEY]: 0.95 }, 1)).toEqual({
      accent: "#000",
    });
  });

  it("undefined 也能安全处理", () => {
    expect(withFontAdjust(undefined, 0.95)).toEqual({ [FONT_SCALE_ADJUST_KEY]: 0.95 });
  });
});

describe("fontProbeCss", () => {
  it("与模板里 --fs 的写法一致，只换基准像素", () => {
    expect(fontProbeCss(13.4)).toBe(":root { --fs: calc(13.4px * var(--fit-scale, 1)); }");
  });
});

/** 分区顺序的前端归一化：与后端 `resume_sections.py` 同一套规则的两份实现，
 *  这里钉住前端这份的行为（补齐、去重、调序边界）。 */

import { describe, expect, it } from "vitest";
import {
  DEFAULT_RESUME_SECTION_ORDER,
  moveSection,
  normalizeSectionOrder,
} from "./resumeSectionOrder";

describe("normalizeSectionOrder", () => {
  it("缺失的键按默认顺序补齐——用户只调前两项，其余五项不该消失", () => {
    expect(normalizeSectionOrder(["projects", "experience"])).toEqual([
      "projects",
      "experience",
      "summary",
      "education",
      "campus_experience",
      "skills",
      "awards",
    ]);
  });

  it("未知键丢弃、重复键去重，而不是让整份版式配置报错", () => {
    expect(normalizeSectionOrder(["projects", "nope", "projects", "summary"])).toEqual([
      "projects",
      "summary",
      "education",
      "experience",
      "campus_experience",
      "skills",
      "awards",
    ]);
  });

  it("空值与非数组输入回到默认顺序", () => {
    expect(normalizeSectionOrder(undefined)).toEqual(DEFAULT_RESUME_SECTION_ORDER);
    expect(normalizeSectionOrder(null)).toEqual(DEFAULT_RESUME_SECTION_ORDER);
    expect(normalizeSectionOrder("projects")).toEqual(DEFAULT_RESUME_SECTION_ORDER);
    expect(normalizeSectionOrder({})).toEqual(DEFAULT_RESUME_SECTION_ORDER);
  });

  it("结果永远覆盖默认顺序的全部键", () => {
    expect(normalizeSectionOrder(["awards"]).slice().sort()).toEqual(
      [...DEFAULT_RESUME_SECTION_ORDER].sort(),
    );
  });
});

describe("moveSection", () => {
  const order = ["a", "b", "c"];

  it("交换相邻两项", () => {
    expect(moveSection(order, 1, -1)).toEqual(["b", "a", "c"]);
    expect(moveSection(order, 1, 1)).toEqual(["a", "c", "b"]);
  });

  it("越界时原样返回同一个引用（调用方靠引用相等跳过提交）", () => {
    expect(moveSection(order, 0, -1)).toBe(order);
    expect(moveSection(order, 2, 1)).toBe(order);
    expect(moveSection(order, -1, 1)).toBe(order);
  });

  it("不改动原数组", () => {
    moveSection(order, 0, 1);
    expect(order).toEqual(["a", "b", "c"]);
  });
});

import { describe, expect, it } from "vitest";
import {
  RESUME_GENERATION_STAGES,
  stageForProgressMessage,
  stageIndexOf,
} from "./resumeGenerationStages";

describe("stageForProgressMessage", () => {
  it("maps the real backend progress messages to their stages", () => {
    // 与后端 resume_generator.py 里的 progress 文案一一对应。
    expect(stageForProgressMessage("正在整理完整资料…")).toBe("prepare");
    expect(stageForProgressMessage("正在分析岗位要求与资料匹配度…")).toBe("prepare");
    expect(stageForProgressMessage("已整理 2 段实习/工作、1 个项目…")).toBe("select");
    expect(stageForProgressMessage("已从完整资料中筛选 2 段实习/工作…")).toBe("select");
    expect(stageForProgressMessage("正在调用模型 fake-model 生成简历…")).toBe("generate");
    expect(stageForProgressMessage("输出格式不符合要求，正在自动修复…")).toBe("repair");
    expect(stageForProgressMessage("生成内容较简略，正在重新生成…")).toBe("repair");
    expect(stageForProgressMessage("生成结果里有空话或套话，正在改写…")).toBe("repair");
  });

  it("returns null for a message it cannot map, instead of guessing", () => {
    expect(stageForProgressMessage("")).toBeNull();
    expect(stageForProgressMessage("一段后端未来新增、尚未认识的进度文案")).toBeNull();
  });
});

describe("stageIndexOf", () => {
  it("returns the step number for a known stage and 0 for null", () => {
    expect(RESUME_GENERATION_STAGES.map((stage) => stage.key)).toEqual([
      "prepare",
      "select",
      "generate",
      "repair",
      "done",
    ]);
    expect(stageIndexOf("prepare")).toBe(0);
    expect(stageIndexOf("generate")).toBe(2);
    expect(stageIndexOf("done")).toBe(4);
    // 后端没发任何 progress 时，阶段条停在第一步，而不是抛异常。
    expect(stageIndexOf(null)).toBe(0);
  });
});

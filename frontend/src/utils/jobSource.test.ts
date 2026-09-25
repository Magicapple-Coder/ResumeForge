/** 岗位来源规则：列表角标与"从备选岗位导入"用的是同一份判断。 */

import { describe, expect, it } from "vitest";
import { candidateImportSource, jobSourceKind } from "./jobSource";

describe("jobSourceKind", () => {
  it("两个采集来源都算「采集」", () => {
    expect(jobSourceKind({ recognition_source: "岗位采集" } as never)).toBe("collected");
    expect(jobSourceKind({ recognition_source: "官网采集" } as never)).toBe("collected");
  });

  it("手动与各类识别结果算「手动」", () => {
    for (const value of ["手动填写", "粘贴文本识别", "图片识别", "文档识别", "备选岗位导入"]) {
      expect(jobSourceKind({ recognition_source: value } as never)).toBe("manual");
    }
    expect(jobSourceKind({ recognition_source: "" } as never)).toBe("manual");
  });
});

describe("candidateImportSource", () => {
  it("采集任务带回来的候选写「岗位采集」——不能写「备选岗位导入」，否则列表挂「手动」角标", () => {
    expect(candidateImportSource({ source: "BOSS直聘", collect_task_id: 7 })).toBe("岗位采集");
  });

  it("官网采集的候选保留更具体的「官网采集」", () => {
    expect(candidateImportSource({ source: "官网采集", collect_task_id: null })).toBe("官网采集");
  });

  it("用户自己粘贴的候选才算「备选岗位导入」", () => {
    expect(candidateImportSource({ source: "手动录入", collect_task_id: null })).toBe(
      "备选岗位导入",
    );
  });

  it("导入后一定是「采集」角标的那两种来源，彼此一致", () => {
    const collected = candidateImportSource({ source: "智联招聘", collect_task_id: 3 });
    expect(jobSourceKind({ recognition_source: collected } as never)).toBe("collected");
    const official = candidateImportSource({ source: "官网采集", collect_task_id: null });
    expect(jobSourceKind({ recognition_source: official } as never)).toBe("collected");
  });
});

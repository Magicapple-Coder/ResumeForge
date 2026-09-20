/** ATS 本地检测面板：免责声明、三类结论、JD 关键词覆盖。 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AtsCheckPanel from "./AtsCheckPanel";

const apiMocks = vi.hoisted(() => ({ runAtsCheck: vi.fn() }));

vi.mock("../api/ats", () => apiMocks);

const RESULT = {
  resume_id: 7,
  issues: [
    {
      category: "format",
      severity: "high",
      title: "缺少姓名",
      detail: "姓名缺失会被 ATS 判为不合格",
      evidence: [],
    },
    {
      category: "position",
      severity: "medium",
      title: "缺少求职意向",
      detail: "求职意向应放在顶部",
      evidence: [],
    },
    {
      category: "keyword",
      severity: "medium",
      title: "关键词覆盖不足",
      detail: "有 1 个常见关键词未命中",
      evidence: ["Python"],
    },
  ],
  matched_keywords: ["MySQL"],
  missing_keywords: ["Python"],
  score: 76,
  disclaimer: "本地规则估计，不代表真实 ATS 解析结果",
  summary: { format: 1, position: 1, keyword: 1 },
};

beforeEach(() => {
  apiMocks.runAtsCheck.mockReset();
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("AtsCheckPanel", () => {
  it("渲染免责声明与三类结论", async () => {
    apiMocks.runAtsCheck.mockResolvedValue(RESULT);
    render(<AtsCheckPanel resumeId={7} />);

    expect(await screen.findByText("本地规则估计，不代表真实 ATS 解析结果")).toBeInTheDocument();
    expect(screen.getByText("缺少姓名")).toBeInTheDocument();
    expect(screen.getByText("缺少求职意向")).toBeInTheDocument();
    expect(screen.getByText("关键词覆盖不足")).toBeInTheDocument();
    expect(screen.getByText("MySQL")).toBeInTheDocument();
    expect(screen.getAllByText("Python").length).toBeGreaterThan(0);
    expect(apiMocks.runAtsCheck).toHaveBeenCalledWith(7, "");
  });

  it("填写 JD 后点击检测按 JD 重新检测", async () => {
    apiMocks.runAtsCheck.mockResolvedValue(RESULT);
    render(<AtsCheckPanel resumeId={7} />);
    await screen.findByText("本地规则估计，不代表真实 ATS 解析结果");

    fireEvent.change(screen.getByLabelText("JD 文本"), {
      target: { value: "要求熟悉 Python" },
    });
    fireEvent.click(screen.getByRole("button", { name: /开始检测/ }));

    expect(await screen.findByText("本地规则估计，不代表真实 ATS 解析结果")).toBeInTheDocument();
    expect(apiMocks.runAtsCheck).toHaveBeenCalledWith(7, "要求熟悉 Python");
  });
});

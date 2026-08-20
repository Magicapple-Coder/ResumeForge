import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Job } from "../types";
import JobRequirementPanel from "./JobRequirementPanel";

const JOB: Job = {
  id: 8,
  title: "产品运营专员",
  company: "示例消费品公司",
  location: "上海",
  salary: "12k-18k",
  job_type: "校招",
  description: "负责新品上市策划与跨部门项目推进。",
  requirements: "具备数据分析能力，能够清晰表达业务判断。",
  additional_info: "提供业务轮岗和导师培养计划。",
  keywords: [
    { name: "数据分析", category: "通用能力" },
    { name: "项目管理", category: "通用能力" },
  ],
  source: "手动添加",
  source_url: "",
  posted_at: "2026-08-20",
  status: "开放中",
  note: "",
  favorite: false,
  created_at: "2026-08-20T09:00:00",
  updated_at: "2026-08-20T09:00:00",
};

describe("JobRequirementPanel", () => {
  it("shows the current job facts needed while writing a resume", () => {
    render(<JobRequirementPanel job={JOB} />);

    expect(
      screen.getByRole("complementary", { name: `岗位要求参考：${JOB.title}` }),
    ).toBeInTheDocument();
    expect(screen.getByText(JOB.company)).toBeInTheDocument();
    expect(screen.getByText(JOB.description)).toBeInTheDocument();
    expect(screen.getByText(JOB.requirements)).toBeInTheDocument();
    expect(screen.getByText("数据分析")).toBeInTheDocument();
    expect(screen.getByText("项目管理")).toBeInTheDocument();
    expect(screen.getByText(JOB.additional_info)).toBeInTheDocument();
  });

  it("keeps all reference sections understandable when optional content is empty", () => {
    render(
      <JobRequirementPanel
        job={{
          ...JOB,
          description: "",
          requirements: "",
          additional_info: "",
          keywords: [],
        }}
      />,
    );

    expect(screen.getByText("暂无岗位职责")).toBeInTheDocument();
    expect(screen.getByText("暂无任职要求")).toBeInTheDocument();
    expect(screen.getByText("暂无技能标签")).toBeInTheDocument();
    expect(screen.getByText("暂无其他信息")).toBeInTheDocument();
  });
});

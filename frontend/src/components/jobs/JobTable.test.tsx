/** 岗位表格：来源角标 + 悬停显示导入时间。 */

import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Job, Page } from "../../types";
import JobTable from "./JobTable";

const BASE_JOB: Job = {
  id: 1,
  title: "护士",
  company: "示例医院",
  location: "杭州市余杭区",
  salary: "",
  job_type: "社招",
  description: "负责病区护理工作。",
  requirements: "持有护士执业资格证。",
  additional_info: "",
  keywords: [],
  source: "手动添加",
  source_url: "",
  posted_at: "2026年8月20日",
  status: "开放中",
  note: "",
  note_images: [],
  recognition_source: "",
  favorite: false,
  created_at: "2026-08-19T08:00:00",
  updated_at: "2026-08-21T09:30:00",
};

function makeJob(overrides: Partial<Job> = {}): Job {
  return { ...BASE_JOB, ...overrides };
}

const noop = () => undefined;

function renderTable(jobs: Job[]) {
  const page: Page<Job> = { items: jobs, total: jobs.length };
  return render(
    <AntdApp>
      <JobTable
        jobs={page}
        loading={false}
        selectionMode={false}
        rowSelection={{} as never}
        batchAction={null}
        favoriteJobId={null}
        page={1}
        pageSize={10}
        onToggleFavorite={noop}
        onOpenDetail={noop}
        onGenerate={noop}
        onWrite={noop}
        onViewResumes={noop}
        onEdit={noop}
        onDelete={noop}
        onPageChange={noop}
      />
    </AntdApp>,
  );
}

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

describe("JobTable 来源角标", () => {
  it("采集来的岗位标「采集」", () => {
    renderTable([makeJob({ recognition_source: "岗位采集", source: "BOSS直聘" })]);

    expect(screen.getByText("采集")).toBeInTheDocument();
    expect(screen.queryByText("手动")).not.toBeInTheDocument();
  });

  it("手动添加的岗位标「手动」", () => {
    renderTable([makeJob({ recognition_source: "", source: "手动添加" })]);

    expect(screen.getByText("手动")).toBeInTheDocument();
    expect(screen.queryByText("采集")).not.toBeInTheDocument();
  });
});

describe("JobTable 悬停导入时间", () => {
  it("悬停职位标题时显示导入时间", async () => {
    renderTable([makeJob({ created_at: "2026-08-19T08:00:00" })]);

    fireEvent.mouseEnter(screen.getByRole("button", { name: "护士" }));

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(/导入于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}/);
  });

  it("悬停职位格里的关键字标签（不在标题上）同样显示导入时间", async () => {
    renderTable([makeJob({ created_at: "2026-08-19T08:00:00" })]);
    await screen.findByText("护士");

    // 用户不会只在标题那两个字上悬停；整格都该给提示。
    // Tooltip 的触发器是格子里的那层 div，所以悬停要落在它身上。
    const trigger = screen.getByText("手动").closest("td")?.firstElementChild;
    expect(trigger).toBeTruthy();
    fireEvent.mouseEnter(trigger as HTMLElement);

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent(/导入于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}/);
  });
});

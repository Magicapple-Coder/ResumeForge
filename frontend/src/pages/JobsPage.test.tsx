import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Job } from "../types";
import JobsPage from "./JobsPage";

const mocks = vi.hoisted(() => ({
  reload: vi.fn(),
  startBackfill: vi.fn(),
  jobs: [] as Job[],
}));

vi.mock("../hooks/useApi", () => ({
  useApi: () => ({
    data: { items: mocks.jobs, total: mocks.jobs.length },
    loading: false,
    reload: mocks.reload,
    error: null,
  }),
}));

// 只替换要断言的 `startBackfill`，其余导出（addToQueue / QueueConflictError）保持真实，
// 免得漏掉某个导出让 `import` 变成 undefined。
vi.mock("../api/apply", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/apply")>();
  return { ...actual, startBackfill: mocks.startBackfill };
});

const BASE_JOB: Job = {
  id: 1,
  title: "护士",
  company: "示例医院",
  location: "杭州市余杭区",
  salary: "",
  job_type: "社招",
  description: "负责病区护理工作。",
  requirements: "持有护士执业资格证。",
  additional_info: "提供岗位培训。",
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

function renderPage() {
  return render(
    <AntdApp>
      <MemoryRouter>
        <JobsPage />
      </MemoryRouter>
    </AntdApp>,
  );
}

describe("JobsPage", () => {
  // 本仓库没有全局 auto-cleanup（见 ApplyPage.test.tsx），必须显式清理，
  // 否则前一个用例渲染出的 DOM 会留在 document 里，让后面的 getByRole 命中多个元素。
  afterEach(cleanup);

  beforeEach(() => {
    mocks.jobs = [makeJob()];
    mocks.startBackfill.mockReset();
    mocks.startBackfill.mockResolvedValue({} as never);
  });

  it("shows the recruitment posted date instead of the local update timestamp", () => {
    renderPage();

    expect(screen.getAllByText("发布时间").length).toBeGreaterThan(0);
    expect(screen.getByText("2026年8月20日")).toBeInTheDocument();
    expect(screen.queryByText("更新时间")).not.toBeInTheDocument();
    expect(screen.queryByText("2026-08-21 17:30")).not.toBeInTheDocument();
  });

  it("有 JD 为空的岗位时显示「补齐详情」按钮", () => {
    mocks.jobs = [makeJob({ id: 7, title: "后端开发", description: "" })];
    renderPage();

    expect(screen.getByRole("button", { name: "补齐详情" })).toBeInTheDocument();
  });

  it("所有岗位都有职位描述时不显示「补齐详情」按钮", () => {
    mocks.jobs = [makeJob({ description: "有正文的岗位描述" })];
    renderPage();

    expect(screen.queryByRole("button", { name: "补齐详情" })).not.toBeInTheDocument();
  });

  it("选择模式下有勾选时只补勾选的岗位，而不是本页所有空 JD", async () => {
    mocks.jobs = [
      makeJob({ id: 1, title: "空A", description: "" }),
      makeJob({ id: 2, title: "空B", description: "" }),
    ];
    renderPage();

    fireEvent.click(screen.getByText("选择"));
    // 第 0 个复选框是全选表头，第 1 个才是第一行；只勾第一行。
    fireEvent.click(screen.getAllByRole("checkbox")[1]);

    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() => expect(mocks.startBackfill).toHaveBeenCalledTimes(1));
    // 勾选了就只补勾选的：不能把本页所有空 JD 也一起送出去。
    expect(mocks.startBackfill).toHaveBeenCalledWith([1]);
  });

  it("选择模式下没有勾选时退回补本页所有空 JD", async () => {
    mocks.jobs = [makeJob({ id: 1, description: "" }), makeJob({ id: 2, description: "" })];
    renderPage();

    fireEvent.click(screen.getByText("选择"));
    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() => expect(mocks.startBackfill).toHaveBeenCalledTimes(1));
    expect(mocks.startBackfill).toHaveBeenCalledWith([1, 2]);
  });

  it("本页没有空 JD 时不出现按钮（即使进了选择模式），因而不存在提交空数组的路径", () => {
    // 空数组会被后端 400 拒绝。若按钮常驻，用户就会看到一个"点得动、点了报错"的按钮。
    // 这里证明了那条路径不存在：没有空 JD → 按钮不渲染 → 连点击入口都没有。
    mocks.jobs = [makeJob({ id: 1, description: "有正文" })];
    renderPage();

    fireEvent.click(screen.getByText("选择"));

    expect(screen.queryByRole("button", { name: "补齐详情" })).not.toBeInTheDocument();
    expect(mocks.startBackfill).not.toHaveBeenCalled();
  });

  it("点「补齐详情」只把这页 JD 为空的岗位 id 交给后端", async () => {
    mocks.jobs = [
      makeJob({ id: 1, title: "有正文的岗位", description: "正文" }),
      makeJob({ id: 2, title: "空的岗位", description: "" }),
      makeJob({ id: 3, title: "只有空白的岗位", description: "   " }),
    ];
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() => expect(mocks.startBackfill).toHaveBeenCalledTimes(1));
    // 只送"描述为空"的两条；有正文的那条不该被带上。
    expect(mocks.startBackfill).toHaveBeenCalledWith([2, 3]);
  });

  it("后端拒绝时提示错误而不是谎报成功", async () => {
    mocks.jobs = [makeJob({ id: 5, description: "" })];
    mocks.startBackfill.mockRejectedValueOnce(new Error("一次最多补齐 200 个岗位的详情"));
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "补齐详情" }));

    await waitFor(() =>
      expect(screen.getByText(/一次最多补齐 200 个岗位的详情/)).toBeInTheDocument(),
    );
  });
});

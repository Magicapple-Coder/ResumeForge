/**
 * 「本次采集结果」：勾选后导入岗位广场。
 *
 * 这一块要守住两条：**采集结果不会自动进岗位广场**（必须由用户勾选），以及导入结果
 * **逐条**如实反馈——勾了 3 条只进去 2 条时，用户必须能看出是哪一条、为什么。
 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CandidateJob } from "../../types";
import CollectResultPanel from "./CollectResultPanel";

const apiMocks = vi.hoisted(() => ({
  listCandidateJobs: vi.fn(),
  importCandidateJobs: vi.fn(),
}));

vi.mock("../../api/candidateJob", () => ({
  listCandidateJobs: apiMocks.listCandidateJobs,
  importCandidateJobs: apiMocks.importCandidateJobs,
}));

function candidate(overrides: Partial<CandidateJob> = {}): CandidateJob {
  return {
    id: 1,
    title: "全栈工程师",
    company: "天津云际",
    location: "天津·西青区",
    salary: "23-26K",
    raw_text: "",
    description: "岗位职责：负责前后端开发。",
    requirements: "任职要求：三年经验。",
    images: [],
    note: "",
    source: "BOSS直聘",
    source_url: "https://www.zhipin.com/job_detail/x.html",
    collect_task_id: 7,
    status: "pending",
    imported_job_id: null,
    created_at: "2026-09-18T10:00:00",
    updated_at: "2026-09-18T10:00:00",
    ...overrides,
  };
}

function renderPanel(props: Partial<React.ComponentProps<typeof CollectResultPanel>> = {}) {
  return render(
    <AntdApp>
      <CollectResultPanel taskId={7} {...props} />
    </AntdApp>,
  );
}

beforeEach(() => {
  apiMocks.listCandidateJobs.mockReset();
  apiMocks.importCandidateJobs.mockReset();
});

afterEach(cleanup);

describe("CollectResultPanel", () => {
  it("只按本次批次拉取待处理的候选", async () => {
    apiMocks.listCandidateJobs.mockResolvedValue([candidate()]);
    renderPanel();

    expect(await screen.findByText("全栈工程师")).toBeInTheDocument();
    expect(apiMocks.listCandidateJobs).toHaveBeenCalledWith({
      collectTaskId: 7,
      status: "pending",
    });
  });

  it("没有勾选任何岗位时不能导入", async () => {
    apiMocks.listCandidateJobs.mockResolvedValue([candidate()]);
    renderPanel();
    await screen.findByText("全栈工程师");

    expect(screen.getByRole("button", { name: /导入选中的岗位/ })).toBeDisabled();
  });

  it("导入后逐条反馈没进去的那几条以及原因", async () => {
    apiMocks.listCandidateJobs.mockResolvedValue([
      candidate({ id: 1, title: "新岗位" }),
      candidate({ id: 2, title: "已存在岗位", source_url: "https://example.com/2" }),
    ]);
    apiMocks.importCandidateJobs.mockResolvedValue({
      imported: 1,
      duplicate: 1,
      invalid: 0,
      missing: 0,
      results: [
        { candidate_id: 1, title: "新岗位", outcome: "imported", job_id: 11 },
        { candidate_id: 2, title: "已存在岗位", outcome: "duplicate", job_id: 12 },
      ],
    });
    renderPanel();
    await screen.findByText("新岗位");

    // 全选后导入。
    fireEvent.click(screen.getByRole("button", { name: "全选" }));
    fireEvent.click(screen.getByRole("button", { name: /导入选中的 2 个岗位/ }));

    await waitFor(() => expect(apiMocks.importCandidateJobs).toHaveBeenCalledWith([1, 2]));
    // 「已存在」那一条必须具名出现，而不是仅仅汇报"导入了 1 条"。
    // 用 getAllByText：岗位名在表格行与问题清单里各出现一次（这正是"逐条反馈"的形态）。
    expect(await screen.findByText(/有 1 个岗位没有新建/)).toBeInTheDocument();
    expect(screen.getByText(/已关联到已有那条/)).toBeInTheDocument();
    expect(screen.getAllByText("已存在岗位").length).toBeGreaterThan(0);
  });

  it("一条都没有时给出空态而不是一张空表", async () => {
    apiMocks.listCandidateJobs.mockResolvedValue([]);
    renderPanel();

    expect(await screen.findByText(/这次采集还没有待导入的岗位/)).toBeInTheDocument();
  });

  it("同一批次完成后按 refreshKey 重新读取结果", async () => {
    apiMocks.listCandidateJobs.mockResolvedValue([candidate()]);
    const view = renderPanel({ refreshKey: "running" });
    await screen.findByText("全栈工程师");
    expect(apiMocks.listCandidateJobs).toHaveBeenCalledTimes(1);

    view.rerender(
      <AntdApp>
        <CollectResultPanel taskId={7} refreshKey="completed" />
      </AntdApp>,
    );

    await waitFor(() => expect(apiMocks.listCandidateJobs).toHaveBeenCalledTimes(2));
  });

  it("切换采集批次时清空上一批的选择", async () => {
    apiMocks.listCandidateJobs.mockImplementation(
      ({ collectTaskId }: { collectTaskId?: number }) => {
        const batchId = collectTaskId ?? 0;
        return Promise.resolve([
          candidate({
            id: batchId,
            collect_task_id: batchId,
            title: batchId === 7 ? "第一批岗位" : "第二批岗位",
          }),
        ]);
      },
    );
    const view = renderPanel({ taskId: 7 });
    await screen.findByText("第一批岗位");
    fireEvent.click(screen.getAllByRole("checkbox")[1]);
    expect(screen.getByRole("button", { name: /导入选中的 1 个岗位/ })).toBeEnabled();

    view.rerender(
      <AntdApp>
        <CollectResultPanel taskId={8} />
      </AntdApp>,
    );

    await screen.findByText("第二批岗位");
    expect(screen.getByRole("button", { name: /导入选中的岗位/ })).toBeDisabled();
  });

  it("没有批次时不渲染", () => {
    apiMocks.listCandidateJobs.mockResolvedValue([]);
    const { container } = renderPanel({ taskId: null });

    // 用类名判断而不是 toBeEmptyDOMElement：外层套了 <AntdApp>，容器里本来就有一个包装节点。
    expect(container.querySelector(".apply-collect-result")).toBeNull();
    expect(apiMocks.listCandidateJobs).not.toHaveBeenCalled();
  });
});

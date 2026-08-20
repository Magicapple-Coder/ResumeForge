import { App as AntdApp } from "antd";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import JobFormModal from "./JobFormModal";

const apiMocks = vi.hoisted(() => ({
  createJob: vi.fn(),
  parseJobText: vi.fn(),
  updateJob: vi.fn(),
}));

vi.mock("../api/jobs", () => apiMocks);

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

beforeEach(() => {
  apiMocks.createJob.mockReset();
  apiMocks.parseJobText.mockReset();
  apiMocks.updateJob.mockReset();
});

afterEach(() => cleanup());

describe("JobFormModal", () => {
  it("fills additional recruitment information returned by text parsing", async () => {
    apiMocks.parseJobText.mockResolvedValue({
      title: "门店店长",
      company: "示例超市",
      location: "成都市武侯区",
      salary: "",
      job_type: "社招",
      description: "负责门店经营",
      requirements: "三年零售经验",
      additional_info: "提供员工宿舍，面试包含门店案例分析",
      source_url: "",
      posted_at: "2026-08-20",
      status: "开放中",
      warnings: [],
    });
    render(
      <AntdApp>
        <JobFormModal open initial={null} onClose={vi.fn()} onSaved={vi.fn()} />
      </AntdApp>,
    );

    fireEvent.change(
      screen.getByPlaceholderText("粘贴职位名称、地点、职位描述、职位要求等完整招聘信息"),
      {
        target: { value: "门店店长招聘信息" },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    await waitFor(() => expect(apiMocks.parseJobText).toHaveBeenCalledOnce());
    expect(screen.getByLabelText("其他招聘信息（选填）")).toHaveValue(
      "提供员工宿舍，面试包含门店案例分析",
    );
    expect(screen.getByLabelText("发布时间（选填）")).toHaveValue("2026-08-20");
  });

  it("submits only once when the save button is activated repeatedly", async () => {
    const pending = deferred();
    apiMocks.createJob.mockReturnValue(pending.promise);
    const onClose = vi.fn();
    const onSaved = vi.fn();
    render(
      <AntdApp>
        <JobFormModal open initial={null} onClose={onClose} onSaved={onSaved} />
      </AntdApp>,
    );

    fireEvent.change(screen.getByLabelText("职位名称"), { target: { value: "前端工程师" } });
    fireEvent.change(screen.getByLabelText("职位描述（JD）"), {
      target: { value: "负责前端应用开发" },
    });
    const saveButton = screen.getByText(/保\s*存/).closest("button");
    if (!saveButton) throw new Error("保存按钮未渲染");
    fireEvent.click(saveButton);
    fireEvent.click(saveButton);

    await waitFor(() => expect(apiMocks.createJob).toHaveBeenCalledTimes(1));
    await act(async () => pending.resolve());
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce());
    expect(onClose).toHaveBeenCalledOnce();
  });
});

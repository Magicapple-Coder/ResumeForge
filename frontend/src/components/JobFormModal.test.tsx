import { App as AntdApp } from "antd";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("JobFormModal", () => {
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

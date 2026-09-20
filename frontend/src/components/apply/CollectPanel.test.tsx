/** 采集条件历史：保存写入 localStorage、去重、回填、清空。 */
import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { CollectConfigOut } from "../../types";
import CollectPanel from "./CollectPanel";

const apiMocks = vi.hoisted(() => ({
  getCollectConfig: vi.fn(),
  updateCollectConfig: vi.fn(),
  createCollectTask: vi.fn(),
}));

vi.mock("../../api/apply", () => ({
  getCollectConfig: apiMocks.getCollectConfig,
  updateCollectConfig: apiMocks.updateCollectConfig,
  createCollectTask: apiMocks.createCollectTask,
}));

const CONFIG: CollectConfigOut = {
  keywords: ["后端"],
  city: "北京",
  salary_min: null,
  experience: "",
  education: "",
  per_task_limit: 50,
  interval_seconds: 3,
  interval_jitter_seconds: 1,
  job_type: "社招",
  defaults: {} as CollectConfigOut,
};

const HISTORY_KEY = "rf.collect.configHistory";

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  apiMocks.getCollectConfig.mockResolvedValue(CONFIG);
  apiMocks.updateCollectConfig.mockResolvedValue(CONFIG);
  apiMocks.createCollectTask.mockResolvedValue({ id: 1 });
});

afterEach(() => {
  cleanup();
  document.body.innerHTML = "";
});

function renderPanel() {
  return render(
    <AntdApp>
      <CollectPanel disabled={false} onStarted={vi.fn()} collectTask={null} />
    </AntdApp>,
  );
}

describe("CollectPanel 条件历史", () => {
  it("保存条件成功后把整份表单快照写入 localStorage", async () => {
    renderPanel();

    fireEvent.click(await screen.findByRole("button", { name: /保存条件/ }));

    await waitFor(() => expect(localStorage.getItem(HISTORY_KEY)).not.toBeNull());
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) as string);
    expect(history).toHaveLength(1);
    expect(history[0].config.city).toBe("北京");
    expect(history[0].config.keywords).toEqual(["后端"]);
    expect(typeof history[0].savedAt).toBe("string");
  });

  it("与上一条完全相同的条件不重复入栈（去重）", async () => {
    renderPanel();
    const saveBtn = await screen.findByRole("button", { name: /保存条件/ });

    fireEvent.click(saveBtn);
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem(HISTORY_KEY) as string)).toHaveLength(1),
    );
    fireEvent.click(saveBtn);
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem(HISTORY_KEY) as string)).toHaveLength(1),
    );
  });

  it("历史下拉回填表单字段", async () => {
    renderPanel();
    const saveBtn = await screen.findByRole("button", { name: /保存条件/ });
    // 保存「北京」，改成「上海」再保存一条 → 两条历史（各自自动选中）。
    fireEvent.click(saveBtn);
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem(HISTORY_KEY) as string)).toHaveLength(1),
    );
    const cityInput = (await screen.findByPlaceholderText("例如：北京")) as HTMLInputElement;
    fireEvent.change(cityInput, { target: { value: "上海" } });
    fireEvent.click(saveBtn);
    await waitFor(() =>
      expect(JSON.parse(localStorage.getItem(HISTORY_KEY) as string)).toHaveLength(2),
    );

    // 选中第一条（北京）历史：当前已选中「上海」，切到「北京」才会触发 onChange 回填。
    const select = screen.getByRole("combobox", { name: "历史条件" });
    fireEvent.mouseDown(select, { button: 0 });
    const option = await screen.findByText(
      (content, element) =>
        content.includes("北京") && !!element?.closest(".ant-select-item-option"),
    );
    fireEvent.click(option);

    await waitFor(() => expect(cityInput.value).toBe("北京"));
  });

  it("清空历史按钮可删除全部快照", async () => {
    renderPanel();
    const saveBtn = await screen.findByRole("button", { name: /保存条件/ });
    fireEvent.click(saveBtn);
    await waitFor(() => expect(localStorage.getItem(HISTORY_KEY)).not.toBeNull());

    fireEvent.click(screen.getByRole("button", { name: /清空历史/ }));
    fireEvent.click(await screen.findByRole("button", { name: /^清\s*空$/ }));

    await waitFor(() => expect(localStorage.getItem(HISTORY_KEY)).toBeNull());
  });
});

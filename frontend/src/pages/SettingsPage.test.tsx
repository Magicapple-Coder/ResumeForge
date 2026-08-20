import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./SettingsPage";

const apiMocks = vi.hoisted(() => ({
  deleteLLMConfigRecord: vi.fn(),
  getLLMConfig: vi.fn(),
  listLLMConfigRecords: vi.fn(),
  saveLLMConfig: vi.fn(),
  saveLLMConfigRecord: vi.fn(),
  testLLM: vi.fn(),
}));

vi.mock("../api/settings", () => apiMocks);

const llmConfig = {
  provider: "openai",
  base_url: "https://api.openai.com/v1",
  api_key: "********",
  model: "gpt-4o-mini",
  temperature: 0.1,
  timeout_seconds: 120,
  max_tokens: 4096,
};

function tooltipTriggerFor(label: string): HTMLElement {
  const labelNode = screen.getByText(label).closest("label");
  const trigger = labelNode?.querySelector<HTMLElement>(".ant-form-item-tooltip");
  if (!trigger) throw new Error(`未找到“${label}”的提示入口`);
  return trigger;
}

beforeEach(() => {
  apiMocks.getLLMConfig.mockResolvedValue(llmConfig);
  apiMocks.listLLMConfigRecords.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SettingsPage parameter help", () => {
  it.each([
    [
      "创意度 temperature",
      "控制输出的随机性。值越低越稳定，适合事实型简历；值越高表达更发散，也会增加内容不一致或虚构风险。",
    ],
    [
      "超时时间（秒）",
      "等待模型返回响应数据的最长时间；超过后请求会终止。网络较慢或生成内容较长时可适当调大，但调大不会让模型生成得更快。",
    ],
    [
      "最大输出 Token",
      "限制模型单次回复的最大输出 Token 数。值越大可能增加费用；过小可能导致内容被截断。它不是模型的上下文长度上限。",
    ],
  ])("shows help for %s on hover", async (label, helpText) => {
    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    fireEvent.mouseEnter(tooltipTriggerFor(label));

    expect(await screen.findByRole("tooltip")).toHaveTextContent(helpText);
  });
});

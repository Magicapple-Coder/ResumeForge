import { App as AntdApp } from "antd";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./SettingsPage";

const apiMocks = vi.hoisted(() => ({
  activateDataset: vi.fn(),
  deleteDataset: vi.fn(),
  deleteLLMConfigRecord: vi.fn(),
  exportDataset: vi.fn(),
  getLLMConfig: vi.fn(),
  importDataset: vi.fn(),
  listDatasets: vi.fn(),
  listLLMConfigRecords: vi.fn(),
  renameDataset: vi.fn(),
  revealLLMApiKey: vi.fn(),
  saveLLMConfig: vi.fn(),
  saveLLMConfigRecord: vi.fn(),
  testLLM: vi.fn(),
}));

vi.mock("../api/settings", () => apiMocks);

const skillMocks = vi.hoisted(() => ({
  deleteSkill: vi.fn(),
  importSkill: vi.fn(),
  listSkills: vi.fn(),
  setSkillEnabled: vi.fn(),
}));

vi.mock("../api/skill", () => skillMocks);

const navigationMocks = vi.hoisted(() => ({ reloadPage: vi.fn() }));

// 整页重载在 jsdom 里不可用，换成可断言的替身。
vi.mock("../utils/navigation", () => navigationMocks);

const mainDataset = {
  id: "main",
  name: "主数据",
  source: "本机",
  size_bytes: 4_947_968,
  created_at: null,
  is_active: true,
  exists: true,
};

const llmConfig = {
  provider: "openai",
  base_url: "https://api.openai.com/v1",
  api_key: "********",
  model: "gpt-4o-mini",
  temperature: 0.1,
  timeout_seconds: 120,
  max_tokens: 4096,
};

/**
 * 选一个快速预设。
 *
 * 预设现在有 17 项，antd 的下拉是虚拟列表：末尾的两项（自定义模型、纯手动配置）
 * 不滚到就根本没渲染，直接 findByText 是找不到的。先打字筛选——这也正是用户
 * 在这个长度的列表里会做的事，顺带覆盖了搜索本身。
 */
async function choosePreset(label: string) {
  const combobox = screen.getByRole("combobox", { name: /快速预设/ });
  fireEvent.mouseDown(combobox);
  fireEvent.change(combobox, { target: { value: label } });
  // 用回车选中筛出来的那一项，而不是点击选项节点：下拉是虚拟列表，过滤后会重渲染，
  // 查到的节点可能在点击前就失效了（点了个空）。
  fireEvent.keyDown(combobox, { key: "Enter", code: "Enter", keyCode: 13 });
}

function tooltipTriggerFor(label: string): HTMLElement {
  const labelNode = screen.getByText(label).closest("label");
  const trigger = labelNode?.querySelector<HTMLElement>(".ant-form-item-tooltip");
  if (!trigger) throw new Error(`未找到“${label}”的提示入口`);
  return trigger;
}

beforeEach(() => {
  apiMocks.getLLMConfig.mockResolvedValue(llmConfig);
  apiMocks.listLLMConfigRecords.mockResolvedValue([]);
  apiMocks.listDatasets.mockResolvedValue([mainDataset]);
  apiMocks.revealLLMApiKey.mockResolvedValue({ api_key: "sk-revealed" });
  skillMocks.listSkills.mockResolvedValue([]);
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
      "限制模型单次回复的最大输出 Token 数。值越大可能增加费用；过小可能导致内容被截断。它不是模型的上下文长度上限。勾选「不限制」后不再发送该参数，改由服务商决定上限，但并非真的无限——部分服务商的默认值可能比手动设置的值更小。",
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

  it("explains the unlimited-token checkbox itself, not just the number field", async () => {
    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    // 这段解释原本只挂在上面那个数字输入框的 tooltip 上：勾选框自己不说，
    // 而"不限制"的行为恰恰与直觉相反。
    const checkbox = screen.getByRole("checkbox", { name: /不限制（由服务商决定上限）/ });
    fireEvent.mouseEnter(checkbox);

    expect(await screen.findByRole("tooltip")).toHaveTextContent("由服务商决定上限");
    expect(await screen.findByRole("tooltip")).toHaveTextContent("不是真的无限");
  });
});

describe("SettingsPage model presets", () => {
  it("recognizes a legacy custom config that uses the official DeepSeek endpoint", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({
      ...llmConfig,
      provider: "custom",
      base_url: "https://api.deepseek.com/",
      api_key: "********:record:1",
      model: "deepseek-v4-flash",
    });
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );

    expect(await screen.findByText("DeepSeek（深度求索）")).toBeInTheDocument();
    expect(screen.getByLabelText("模型名称")).toHaveValue("deepseek-v4-flash");

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "custom",
          api_key: "********:record:1",
          model: "deepseek-v4-flash",
        }),
      ),
    );
  });

  it("shows an unknown saved configuration as a custom OpenAI-compatible model", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({
      ...llmConfig,
      provider: "private-cloud",
      base_url: "https://llm.example.com/v1",
      model: "company-chat",
    });

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );

    expect(await screen.findByText("自定义模型（OpenAI 兼容）")).toBeInTheDocument();
    expect(screen.getByLabelText("Base URL")).toHaveValue("https://llm.example.com/v1");
    expect(screen.getByLabelText("模型名称")).toHaveValue("company-chat");
  });

  it("clears the preset fields for a manual configuration", async () => {
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    await choosePreset("纯手动配置（不套用任何预设）");

    // 关键区别：自定义模型保留当前内容，纯手动配置要一套空的
    expect(screen.getByLabelText("Base URL")).toHaveValue("");
    expect(screen.getByLabelText("模型名称")).toHaveValue("");
    // 预设本来就不碰密钥，这里也不该替用户清掉它
    expect(screen.getByLabelText("API Key（选填）")).toHaveValue("********");

    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "https://relay.example.com/v1" },
    });
    fireEvent.change(screen.getByLabelText("模型名称"), { target: { value: "my-model" } });
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "manual",
          base_url: "https://relay.example.com/v1",
          model: "my-model",
        }),
      ),
    );
  }, 15_000);

  it("keeps showing 纯手动配置 after it is saved", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({
      ...llmConfig,
      provider: "manual",
      base_url: "https://relay.example.com/v1",
      model: "my-model",
    });

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );

    // 保存后再打开，下拉要停在自己那一项，而不是跳回「自定义模型」
    expect(await screen.findByText("纯手动配置（不套用任何预设）")).toBeInTheDocument();
  });

  it("saves the provider that belongs to the selected preset", async () => {
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    await choosePreset("DeepSeek（深度求索）");
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "deepseek",
          base_url: "https://api.deepseek.com",
          model: "deepseek-chat",
        }),
      ),
    );
  }, 15_000);

  it("saves a custom local model without an API key", async () => {
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    await choosePreset("自定义模型（OpenAI 兼容）");

    expect(screen.getByLabelText("Base URL")).toHaveValue("https://api.openai.com/v1");
    fireEvent.change(screen.getByLabelText("Base URL"), {
      target: { value: "http://localhost:11434/v1" },
    });
    fireEvent.change(screen.getByLabelText("模型名称"), {
      target: { value: "private-model" },
    });
    fireEvent.change(screen.getByLabelText("API Key（选填）"), {
      target: { value: "" },
    });
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: "custom",
          base_url: "http://localhost:11434/v1",
          api_key: "",
          model: "private-model",
        }),
      ),
    );
  }, 15_000);
});

describe("SettingsPage API key reveal", () => {
  function passwordToggle(): HTMLElement {
    const input = screen.getByLabelText("API Key（选填）");
    const toggle = input
      .closest(".ant-input-affix-wrapper")
      ?.querySelector<HTMLElement>(".ant-input-password-icon");
    if (!toggle) throw new Error("未找到 API Key 显示按钮");
    return toggle;
  }

  it("reveals the saved key only on demand and keeps the form reference masked", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({
      ...llmConfig,
      provider: "custom",
      base_url: "https://api.deepseek.com",
      api_key: "********:record:1",
      model: "deepseek-v4-flash",
    });
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );

    const input = await screen.findByLabelText("API Key（选填）");
    await waitFor(() => expect(input).toHaveValue("********"));
    expect(apiMocks.revealLLMApiKey).not.toHaveBeenCalled();

    fireEvent.click(passwordToggle());

    await waitFor(() => expect(apiMocks.revealLLMApiKey).toHaveBeenCalledOnce());
    await waitFor(() => expect(input).toHaveValue("sk-revealed"));
    expect(input).toHaveAttribute("type", "text");

    fireEvent.click(passwordToggle());
    await waitFor(() => expect(input).toHaveValue("********"));
    expect(input).toHaveAttribute("type", "password");

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    fireEvent.click(passwordToggle());
    await waitFor(() => expect(input).toHaveValue("sk-revealed"));
    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({ api_key: "********:record:1" }),
      ),
    );
  });

  it("keeps the key masked when the explicit reveal request fails", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({
      ...llmConfig,
      api_key: "********:record:1",
    });
    apiMocks.revealLLMApiKey.mockRejectedValue(new Error("读取密钥失败"));

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );

    const input = await screen.findByLabelText("API Key（选填）");
    // 必须先等掩码值写进表单：配置加载完成前点击显示按钮，掩码值为空，
    // 组件会直接切到明文态而不发起读取请求，这里也就永远等不到错误提示。
    await waitFor(() => expect(input).toHaveValue("********"));
    fireEvent.click(passwordToggle());

    expect(await screen.findByText("读取密钥失败")).toBeInTheDocument();
    expect(input).toHaveValue("********");
    expect(input).toHaveAttribute("type", "password");
  });
});

describe("SettingsPage configuration record lifecycle", () => {
  it("refreshes the current config after deleting the active record", async () => {
    const record = {
      id: 7,
      name: "DeepSeek 校招",
      provider: "deepseek",
      base_url: "https://api.deepseek.com",
      api_key: "********:record:7",
      model: "deepseek-chat",
      temperature: 0.1,
      timeout_seconds: 120,
      max_tokens: 4096,
      created_at: "2026-08-20T10:00:00",
      updated_at: "2026-08-20T10:00:00",
    };
    apiMocks.getLLMConfig.mockResolvedValueOnce({ ...llmConfig, ...record }).mockResolvedValueOnce({
      ...llmConfig,
      provider: "deepseek",
      base_url: record.base_url,
      model: record.model,
    });
    apiMocks.listLLMConfigRecords.mockResolvedValue([record]);
    apiMocks.deleteLLMConfigRecord.mockResolvedValue(undefined);
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );

    await screen.findByText("DeepSeek 校招");
    fireEvent.click(screen.getByRole("button", { name: "删除配置记录 DeepSeek 校招" }));
    const confirmDelete = await waitFor(() => {
      const button = document.querySelector<HTMLButtonElement>(
        ".ant-popconfirm-buttons .ant-btn-primary",
      );
      if (!button) throw new Error("未找到删除确认按钮");
      return button;
    });
    fireEvent.click(confirmDelete);

    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledTimes(2), { timeout: 1000 });
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "删除配置记录 DeepSeek 校招" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.queryByText("DeepSeek 校招")).not.toBeInTheDocument();
    expect(screen.getByLabelText("API Key（选填）")).toHaveValue("********");
  });
});

describe("SettingsPage output limit", () => {
  it("saves the unlimited value and disables the input when the checkbox is ticked", async () => {
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    // 非编辑态必须仍然只读：InputNumber 的 disabled 只在为 true 时覆盖 Form 的
    // disabled 上下文，写成 disabled={unlimitedTokens} 传 false 会让这里可编辑。
    const limitInput = screen.getByLabelText("最大输出 Token");
    expect(limitInput).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    expect(limitInput).not.toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: /不限制/ }));
    expect(limitInput).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({ max_tokens: 0 }),
      ),
    );
  });

  it("restores the default limit when the checkbox is cleared", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({ ...llmConfig, max_tokens: 0 });
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    const checkbox = screen.getByRole("checkbox", { name: /不限制/ });
    await waitFor(() => expect(checkbox).toBeChecked());
    expect(screen.getByLabelText("最大输出 Token")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    fireEvent.click(checkbox);
    expect(screen.getByLabelText("最大输出 Token")).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({ max_tokens: 4096 }),
      ),
    );
  });

  it("restores the value the user had before ticking the checkbox", async () => {
    apiMocks.getLLMConfig.mockResolvedValue({ ...llmConfig, max_tokens: 8192 });
    apiMocks.saveLLMConfig.mockImplementation(async (config) => config);

    render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.getLLMConfig).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: /编辑设置/ }));
    const checkbox = screen.getByRole("checkbox", { name: /不限制/ });
    fireEvent.click(checkbox);
    fireEvent.click(checkbox);

    fireEvent.click(screen.getByRole("button", { name: /保存配置/ }));

    await waitFor(() =>
      expect(apiMocks.saveLLMConfig).toHaveBeenCalledWith(
        expect.objectContaining({ max_tokens: 8192 }),
      ),
    );
  });
});

describe("SettingsPage datasets", () => {
  const imported = {
    id: "0123456789abcdef",
    name: "备份 A",
    source: "导入",
    size_bytes: 2_048_000,
    created_at: "2026-09-15T10:00:00+08:00",
    is_active: false,
    exists: true,
  };

  function chooseBackupFile(container: HTMLElement) {
    // 设置页上有多个上传入口（技能、数据集），按 aria-label 定位而不是取第一个。
    const input = container.querySelector(
      'input[type="file"][aria-label="选择备份文件"]',
    ) as HTMLInputElement;
    const file = new File(["zip-bytes"], "backup.zip", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [file] } });
    return file;
  }

  async function renderPage() {
    const view = render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(apiMocks.listDatasets).toHaveBeenCalled());
    return view;
  }

  it("lists the available datasets and marks the active one", async () => {
    apiMocks.listDatasets.mockResolvedValue([mainDataset, imported]);
    await renderPage();

    expect(await screen.findByText("主数据")).toBeInTheDocument();
    expect(screen.getByText("备份 A")).toBeInTheDocument();
    expect(screen.getByText("当前")).toBeInTheDocument();
  });

  it("downloads the active dataset", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    apiMocks.exportDataset.mockResolvedValue({
      blob: new Blob(["zip-bytes"], { type: "application/zip" }),
      filename: "resumeforge-backup-20260915.zip",
    });
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: /导出当前数据集/ }));

    await waitFor(() => expect(apiMocks.exportDataset).toHaveBeenCalledWith("main"));
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();
  });

  it("imports a chosen archive as a new dataset without switching to it", async () => {
    apiMocks.importDataset.mockResolvedValue(imported);
    const { container } = await renderPage();

    const file = chooseBackupFile(container);

    await waitFor(() => expect(apiMocks.importDataset).toHaveBeenCalledOnce());
    // antd 会把 File 包一层再交给 beforeUpload，按属性断言更稳。
    expect((apiMocks.importDataset.mock.calls[0][0] as File).name).toBe(file.name);
    expect(apiMocks.importDataset.mock.calls[0][1]).toBe("backup");
    // 导入只新增数据集：既不会切过去，也不会重载页面。
    expect(apiMocks.activateDataset).not.toHaveBeenCalled();
    expect(navigationMocks.reloadPage).not.toHaveBeenCalled();
  });

  it("switches to another dataset and reloads the page", async () => {
    apiMocks.listDatasets.mockResolvedValue([mainDataset, imported]);
    apiMocks.activateDataset.mockResolvedValue({ ...imported, is_active: true });
    await renderPage();

    // 列表顺序即渲染顺序：主数据在前，可切换的那份在后。
    fireEvent.click(screen.getAllByRole("button", { name: /切换/ })[1]);

    await waitFor(() => expect(apiMocks.activateDataset).toHaveBeenCalledWith(imported.id));
    await waitFor(() => expect(navigationMocks.reloadPage).toHaveBeenCalled(), { timeout: 3000 });
  });

  it("renames a dataset", async () => {
    apiMocks.listDatasets.mockResolvedValue([mainDataset, imported]);
    apiMocks.renameDataset.mockResolvedValue({ ...imported, name: "校招专用" });
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: `重命名 ${imported.name}` }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "校招专用" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() =>
      expect(apiMocks.renameDataset).toHaveBeenCalledWith(imported.id, "校招专用"),
    );
  });

  it("keeps the rename dialog open when renaming fails", async () => {
    apiMocks.listDatasets.mockResolvedValue([mainDataset, imported]);
    apiMocks.renameDataset.mockRejectedValue(new Error("名称不能为空"));
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: `重命名 ${imported.name}` }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => expect(apiMocks.renameDataset).toHaveBeenCalledOnce());
    // 失败时弹窗保留，用户可以改个名字重试。
    expect(screen.getByText("重命名数据集")).toBeInTheDocument();
  });

  it("deletes a dataset only after confirmation", async () => {
    apiMocks.listDatasets.mockResolvedValue([mainDataset, imported]);
    apiMocks.deleteDataset.mockResolvedValue(undefined);
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: `删除数据集 ${imported.name}` }));

    expect(apiMocks.deleteDataset).not.toHaveBeenCalled();
    const confirm = await waitFor(() =>
      document.querySelector<HTMLButtonElement>(".ant-popconfirm-buttons .ant-btn-primary")!,
    );
    fireEvent.click(confirm);

    await waitFor(() => expect(apiMocks.deleteDataset).toHaveBeenCalledWith(imported.id));
  });

  it("does not offer switching or deleting the active dataset", async () => {
    await renderPage();

    expect(screen.getByRole("button", { name: /切换/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "删除数据集 主数据" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重命名 主数据" })).toBeDisabled();
  });
});

describe("SettingsPage skills", () => {
  const interviewSkill = {
    id: 1,
    name: "面试模拟官",
    description: "练面试时使用",
    enabled: true,
    source_name: "面试模拟官.zip",
    prompt_chars: 120,
    files: ["题库.md", "模板.txt"],
    updated_at: "2026-09-15T10:00:00+08:00",
  };

  // 不带知识文件的技能，用来覆盖「仅提示词」那一支的展示。
  const disabledSkill = {
    ...interviewSkill,
    id: 2,
    name: "简历诊断",
    enabled: false,
    prompt_chars: 80,
    files: [],
  };

  async function renderPage(skills = [interviewSkill]) {
    skillMocks.listSkills.mockResolvedValue(skills);
    const view = render(
      <AntdApp>
        <SettingsPage />
      </AntdApp>,
    );
    await waitFor(() => expect(skillMocks.listSkills).toHaveBeenCalled());
    return view;
  }

  it("lists skills with their status and knowledge file count", async () => {
    await renderPage([interviewSkill, disabledSkill]);

    expect(await screen.findByText("面试模拟官")).toBeInTheDocument();
    expect(screen.getByText("启用中")).toBeInTheDocument();
    expect(screen.getByText("已停用")).toBeInTheDocument();
    expect(screen.getByText(/2 份知识文件/)).toBeInTheDocument();
    expect(screen.getByText(/仅提示词/)).toBeInTheDocument();
  });

  it("shows an empty state before anything is imported", async () => {
    await renderPage([]);

    expect(await screen.findByText("还没有导入技能")).toBeInTheDocument();
  });

  it("imports the chosen file and refreshes the list", async () => {
    skillMocks.importSkill.mockResolvedValue(interviewSkill);
    const { container } = await renderPage([]);
    const input = container.querySelector(
      'input[type="file"][aria-label="选择技能文件"]',
    ) as HTMLInputElement;
    const file = new File(["skill-bytes"], "面试模拟官.zip", { type: "application/zip" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(skillMocks.importSkill).toHaveBeenCalledOnce());
    // 类型判定在后端，前端只负责把文件原样送过去。
    expect((skillMocks.importSkill.mock.calls[0][0] as File).name).toBe(file.name);
    // 导入成功后重新拉一次列表，让新技能出现在界面上。
    await waitFor(() => expect(skillMocks.listSkills).toHaveBeenCalledTimes(2));
  });

  it("toggles a skill without reloading the list", async () => {
    skillMocks.setSkillEnabled.mockResolvedValue(disabledSkill);
    await renderPage([interviewSkill, disabledSkill]);

    fireEvent.click(screen.getByRole("switch", { name: "停用技能 面试模拟官" }));

    await waitFor(() => expect(skillMocks.setSkillEnabled).toHaveBeenCalledWith(1, false));
    expect(await screen.findByText("已停用")).toBeInTheDocument();
  });

  it("deletes a skill only after confirmation", async () => {
    skillMocks.deleteSkill.mockResolvedValue(undefined);
    await renderPage();

    fireEvent.click(screen.getByRole("button", { name: "删除技能 面试模拟官" }));

    expect(skillMocks.deleteSkill).not.toHaveBeenCalled();
    const confirm = await waitFor(() =>
      document.querySelector<HTMLButtonElement>(".ant-popconfirm-buttons .ant-btn-primary")!,
    );
    fireEvent.click(confirm);

    await waitFor(() => expect(skillMocks.deleteSkill).toHaveBeenCalledWith(1));
    // 删除后就地移除，不需要再拉一次列表。
    await waitFor(() => expect(screen.queryByText("面试模拟官")).not.toBeInTheDocument());
  });

  it("warns what deleting a skill takes with it, before the click", async () => {
    await renderPage();

    // 只有图标，说明只能靠悬停给；删除范围（含知识文件）此前要点开确认框才知道。
    fireEvent.mouseEnter(screen.getByRole("button", { name: "删除技能 面试模拟官" }));

    expect(await screen.findByRole("tooltip")).toHaveTextContent("提示词与知识文件一起删除");
  });
});

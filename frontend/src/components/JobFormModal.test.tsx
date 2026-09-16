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

    fireEvent.change(screen.getByLabelText("完整招聘信息"), {
      target: { value: "门店店长招聘信息" },
    });
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

const DRAFT = {
  title: "门店店长",
  company: "示例超市",
  location: "成都市武侯区",
  salary: "",
  job_type: "社招",
  description: "负责门店经营",
  requirements: "三年零售经验",
  additional_info: "",
  source_url: "",
  posted_at: "",
  status: "开放中",
  warnings: ["识别结果来自截图，请对照截图核对后再保存。"],
  recognition_source: "ai" as const,
  recognized_text: "门店店长 示例超市 成都市武侯区",
};

function renderModal(onSaved = vi.fn()) {
  const view = render(
    <AntdApp>
      <JobFormModal open initial={null} onClose={vi.fn()} onSaved={onSaved} />
    </AntdApp>,
  );
  return view;
}

function pasteScreenshot(textarea: HTMLElement, name = "shot.png") {
  const file = new File([new Uint8Array(64)], name, { type: "image/png" });
  fireEvent.paste(textarea, {
    clipboardData: { items: [{ kind: "file", type: "image/png", getAsFile: () => file }] },
  });
}

describe("JobFormModal 图片识别", () => {
  it("sends pasted screenshots even when the textarea is empty", async () => {
    apiMocks.parseJobText.mockResolvedValue(DRAFT);
    renderModal();
    const textarea = screen.getByLabelText("完整招聘信息");

    pasteScreenshot(textarea);
    await waitFor(() => expect(screen.getByAltText("shot.png")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    await waitFor(() => expect(apiMocks.parseJobText).toHaveBeenCalledOnce());
    const payload = apiMocks.parseJobText.mock.calls[0][0];
    expect(payload.text).toBe("");
    expect(payload.images).toHaveLength(1);
    expect(payload.images[0].name).toBe("shot.png");
    expect(payload.images[0].data.startsWith("data:image/png;base64,")).toBe(true);
    // 只有图片、没有文本时不该再提示"请先粘贴招聘信息"
    expect(screen.queryByText("请先粘贴招聘信息，或添加截图、上传文档")).not.toBeInTheDocument();
    expect(screen.getByLabelText("职位名称")).toHaveValue("门店店长");
  });

  it("sends an uploaded document in its own field", async () => {
    apiMocks.parseJobText.mockResolvedValue(DRAFT);
    renderModal();
    const input = document.querySelector(
      'input[type="file"][aria-label="添加截图或文档"]',
    ) as HTMLInputElement;
    const file = new File([new Uint8Array(64)], "jd.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });

    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByText("jd.docx")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    await waitFor(() => expect(apiMocks.parseJobText).toHaveBeenCalledOnce());
    const payload = apiMocks.parseJobText.mock.calls[0][0];
    // 图片与文档是两个请求字段：后端对它们的处理方式完全不同
    expect(payload.images).toEqual([]);
    expect(payload.documents).toHaveLength(1);
    expect(payload.documents[0].name).toBe("jd.docx");
  });

  it("accepts an image chosen from the file picker and lets it be removed", async () => {
    renderModal();
    // 弹窗内容被 portal 到 body，不能用 render 的 container 查
    const input = document.querySelector(
      'input[type="file"][aria-label="添加截图或文档"]',
    ) as HTMLInputElement;
    const file = new File([new Uint8Array(64)], "picker.png", { type: "image/png" });

    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByAltText("picker.png")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "移除文件 picker.png" }));
    await waitFor(() => expect(screen.queryByAltText("picker.png")).not.toBeInTheDocument());
  });

  it("shows the text the model read and never submits it as a job field", async () => {
    apiMocks.parseJobText.mockResolvedValue(DRAFT);
    apiMocks.createJob.mockResolvedValue({});
    renderModal();
    const textarea = screen.getByLabelText("完整招聘信息");

    pasteScreenshot(textarea);
    await waitFor(() => expect(screen.getByAltText("shot.png")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    // 折叠块默认收起，点开后能看到模型抄录的原文
    const toggle = await screen.findByText("查看模型识别到的原文（请对照截图核对）");
    fireEvent.click(toggle);
    expect(await screen.findByText("门店店长 示例超市 成都市武侯区")).toBeInTheDocument();

    // 按 role 找按钮：警告条里也有"保存"两个字
    fireEvent.click(screen.getByRole("button", { name: /保\s*存/ }));

    await waitFor(() => expect(apiMocks.createJob).toHaveBeenCalledOnce());
    expect(apiMocks.createJob.mock.calls[0][0]).not.toHaveProperty("recognized_text");
    expect(JSON.stringify(apiMocks.createJob.mock.calls[0][0])).not.toContain("门店店长 示例超市");
  });

  it("keeps saying where the fields came from after the toast is gone", async () => {
    apiMocks.parseJobText.mockResolvedValue(DRAFT);
    renderModal();

    pasteScreenshot(screen.getByLabelText("完整招聘信息"));
    await waitFor(() => expect(screen.getByAltText("shot.png")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    // 提示条会自己消失，而"AI 识别的还是本地规则认的"决定这些字段要核对到什么程度，
    // 所以必须留在表单上。
    const badge = await screen.findByText("AI 识别");
    expect(badge).toBeInTheDocument();

    fireEvent.mouseEnter(badge);
    expect(await screen.findByRole("tooltip")).toHaveTextContent("校验过能在你给的内容里找到出处");
  });

  it("marks local-rule results as less trustworthy", async () => {
    apiMocks.parseJobText.mockResolvedValue({
      ...DRAFT,
      recognition_source: "local" as const,
      recognized_text: "",
      warnings: [],
    });
    renderModal();

    fireEvent.change(screen.getByLabelText("完整招聘信息"), { target: { value: "门店店长" } });
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    const badge = await screen.findByText("本地规则");
    fireEvent.mouseEnter(badge);

    expect(await screen.findByRole("tooltip")).toHaveTextContent("准确度低于 AI 识别");
  });

  it("drops the source badge once the pasted text changes", async () => {
    apiMocks.parseJobText.mockResolvedValue(DRAFT);
    renderModal();
    const textarea = screen.getByLabelText("完整招聘信息");
    fireEvent.change(textarea, { target: { value: "门店店长" } });
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));
    expect(await screen.findByText("AI 识别")).toBeInTheDocument();

    // 换了内容，上一次识别的来源不再描述现在表单里的东西。
    fireEvent.change(textarea, { target: { value: "另一家公司" } });

    expect(screen.queryByText("AI 识别")).not.toBeInTheDocument();
  });

  it("keeps typed values when recognition comes back empty", async () => {
    apiMocks.parseJobText.mockResolvedValue({
      ...DRAFT,
      title: "",
      company: "",
      location: "",
      description: "",
      requirements: "",
      recognized_text: "",
      recognition_source: "local" as const,
    });
    renderModal();
    fireEvent.change(screen.getByLabelText("职位名称"), { target: { value: "我手填的岗位" } });

    pasteScreenshot(screen.getByLabelText("完整招聘信息"));
    await waitFor(() => expect(screen.getByAltText("shot.png")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /识别并填充/ }));

    // 什么都没识别出来时不能把用户已经填好的内容抹掉
    await waitFor(() => expect(apiMocks.parseJobText).toHaveBeenCalledOnce());
    expect(screen.getByLabelText("职位名称")).toHaveValue("我手填的岗位");
  });
});
